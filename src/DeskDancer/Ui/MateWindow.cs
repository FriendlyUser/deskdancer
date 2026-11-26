using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform;
using Avalonia.Threading;
using DeskDancer.Characters;
using DeskDancer.Engine;
using DeskDancer.Platform;

namespace DeskDancer.Ui;

/// <summary>
/// One mate: a borderless, transparent, always-on-top window that follows its brain
/// around the screen. The window is a small "stage" around the character; walking moves
/// the window, while jumps and spins are drawn inside it.
/// </summary>
public sealed class MateWindow : Window
{
    readonly App _app;
    readonly MateView _view = new();
    readonly ContextMenu _menu = new();
    readonly Stopwatch _watch = Stopwatch.StartNew();
    readonly Random _rng = new();

    ICharacter _character;
    double _lastTick, _stageW, _stageH, _feetY, _heightDip, _screenCheckIn;
    Screen? _screen;
    PixelPoint _lastPos = new(int.MinValue, int.MinValue);
    bool _closed, _pressed, _dragging, _skippedFrame;
    PixelRect? _solidArea;
    bool _solidAreaApplied;
    PixelPoint _pressAt;
    double _grabDx, _grabDy;

    public MateWindow(App app, MateSettings settings)
    {
        _app = app;
        Settings = settings;

        Title = "DeskDancer";
        WindowDecorations = WindowDecorations.None;
        Background = Brushes.Transparent;
        TransparencyLevelHint = [WindowTransparencyLevel.Transparent];
        Topmost = app.Settings.AlwaysOnTop;
        ShowInTaskbar = false;
        ShowActivated = false;
        CanResize = false;
        WindowStartupLocation = WindowStartupLocation.Manual;
        Content = _view;

        _character = app.Library.Load(settings.Character);
        Brain = new MateBrain(app.Clock, app.Conductor, app.Settings, _character, _rng);
        _view.Brain = Brain;
        ApplyCharacter();

        // Refresh the menu just before it opens. This handler is added before the menu is
        // attached so that it runs ahead of the one that actually shows the menu.
        ContextRequested += (_, _) => RebuildMenu();
        ContextMenu = _menu;
        RebuildMenu();

        PointerPressed += OnPointerPressed;
        PointerMoved += OnPointerMoved;
        PointerReleased += OnPointerReleased;
        PointerCaptureLost += (_, _) => FinishPress(clicked: false);
        PointerExited += (_, _) => Brain.SetHover(false);

        Opened += (_, _) =>
        {
            ApplyPosition();
            _lastTick = _watch.Elapsed.TotalSeconds;
            RequestAnimationFrame(OnFrame);
        };
        Closed += (_, _) => _closed = true;
    }

    public MateSettings Settings { get; }
    public MateBrain Brain { get; }
    public ICharacter Character => _character;
    /// <summary>Frames drawn so far; the smoke test uses this to prove the window is alive.</summary>
    public int FrameCount { get; private set; }

    /// <summary>Opens the right-click menu as if the user had asked for it.</summary>
    public void OpenMenu()
    {
        RebuildMenu();
        _menu.Open(this);
    }

    // ---- Layout ----

    void ApplyCharacter()
    {
        _view.Character = _character;
        Brain.Character = _character;
        RenderOptions.SetBitmapInterpolationMode(_view,
            _character.PixelArt ? BitmapInterpolationMode.None : BitmapInterpolationMode.HighQuality);
        ApplyLayout();
    }

    /// <summary>Sizes the stage: wide enough for arms and side steps, tall enough for a backflip.</summary>
    void ApplyLayout()
    {
        double h = _heightDip = Math.Clamp(_character.PreferredHeight * Settings.Scale, 24, 1200);
        _stageW = Math.Ceiling(Math.Max(1.7 * h, (_character.AspectRatio + 1.0) * h));
        _stageH = Math.Ceiling(1.95 * h);
        _feetY = _stageH - Math.Round(0.14 * h);
        Width = _stageW;
        Height = _stageH;
        _view.CharacterHeight = h;
    }

    /// <summary>Picks a starting spot on the primary screen and lets the mate drop in from above.</summary>
    public void PlaceOnScreen(double? fraction = null)
    {
        _screen = Screens.Primary ?? Screens.All.FirstOrDefault();
        var area = _screen?.WorkingArea ?? new PixelRect(0, 0, 1280, 720);
        double scaling = _screen?.Scaling ?? 1;
        UpdateWorld(scaling);
        double x = area.X + area.Width * (fraction ?? 0.2 + 0.6 * _rng.NextDouble());
        Brain.Place(x, area.Y + area.Height * 0.4);
        Brain.Drop();
        ApplyPosition(scaling);
    }

    void UpdateWorld(double scaling)
    {
        var area = _screen?.WorkingArea ?? new PixelRect(0, 0, 1280, 720);
        Brain.H = _heightDip * scaling;
        Brain.Left = area.X;
        Brain.Right = area.Right;
        Brain.Top = area.Y;
        // Stand a few pixels above the edge of the work area so the whole shadow is visible.
        Brain.Floor = area.Bottom - Math.Round(0.04 * Brain.H);
    }

    void ApplyPosition(double? scalingOverride = null)
    {
        double scaling = scalingOverride ?? RenderScaling;
        var pos = new PixelPoint(
            (int)Math.Round(Brain.FootX - _stageW / 2 * scaling),
            (int)Math.Round(Brain.FootY - _feetY * scaling));
        if (pos != _lastPos)
        {
            Position = pos;
            _lastPos = pos;
        }
        // Whatever fraction of a pixel the window could not move is made up when drawing.
        _view.Scaling = scaling;
        _view.OriginX = pos.X;
        _view.OriginY = pos.Y;
    }

    // ---- Frame loop ----

    void OnFrame(TimeSpan _)
    {
        if (_closed) return;
        // Standing around does not need 60 frames a second; halve the work while nothing is moving fast.
        if (IsCalm && !_skippedFrame && !_pressed)
        {
            _skippedFrame = true;
            RequestAnimationFrame(OnFrame);
            return;
        }
        _skippedFrame = false;

        double now = _watch.Elapsed.TotalSeconds, dt = now - _lastTick;
        _lastTick = now;
        try
        {
            Step(dt);
        }
        catch (Exception ex)
        {
            Log.Error("Frame update failed", ex);
        }
        RequestAnimationFrame(OnFrame);
    }

    void Step(double dt)
    {
        double scaling = RenderScaling;

        // Work out which monitor the mate is on. While it is being carried or thrown it can
        // cross monitors, so check every frame then and only occasionally otherwise.
        _screenCheckIn -= dt;
        if (_screen == null || _screenCheckIn <= 0 || Brain.State is MateState.Drag or MateState.Fall)
        {
            var probe = new PixelPoint((int)Brain.FootX, (int)(Brain.FootY - Brain.H * 0.5));
            _screen = Screens.ScreenFromPoint(probe) ?? _screen ?? Screens.Primary ?? Screens.All.FirstOrDefault();
            _screenCheckIn = 0.5;
        }

        UpdateWorld(scaling);
        Brain.Update(dt);
        ApplyPosition(scaling);
        UpdateClickThrough(scaling);
        _view.InvalidateVisual();
        FrameCount++;
    }

    /// <summary>Nothing energetic going on: not dancing, walking or being carried.</summary>
    bool IsCalm => Brain.State is MateState.Idle or MateState.Sit or MateState.Sleep && Brain.Energy < 0.02;

    /// <summary>The rectangle of the window, in pixels, that holds the character and its shadow.</summary>
    public PixelRect? SolidArea => _solidArea;

    /// <summary>
    /// Keeps clicks on the empty part of the stage from being swallowed. Where narrowing the
    /// clickable area would also clip drawing, it is only narrowed while the character is
    /// within its resting outline.
    /// </summary>
    void UpdateClickThrough(double scaling)
    {
        PixelRect? wanted = null;
        bool resting = Brain.State is MateState.Idle or MateState.Walk or MateState.Sit or MateState.Sleep
                       && Brain.Particles.Items.Count == 0 && Brain.Energy < 0.02;
        if (_app.Settings.ClickThrough && (resting || !ClickThrough.ClipsDrawing))
        {
            double h = Brain.H;
            double halfW = (Math.Max(0.5 * _character.AspectRatio, 0.2 + 0.2 * _character.AspectRatio) + 0.16) * h;
            double feetX = Brain.FootX - _view.OriginX, feetY = Brain.FootY - _view.OriginY;
            double top = feetY - (Brain.Body.Y + 1.22) * h, bottom = feetY + 0.1 * h;
            // Snap to a coarse grid so tiny movements do not make a new region every frame.
            int grid = Math.Max(4, (int)(h * 0.06));
            int Snap(double v, bool up) => (int)(up ? Math.Ceiling(v / grid) : Math.Floor(v / grid)) * grid;
            int x0 = Snap(feetX - halfW, false), x1 = Snap(feetX + halfW, true);
            int y0 = Snap(top, false), y1 = Snap(bottom, true);
            wanted = new PixelRect(x0, y0, x1 - x0, y1 - y0);
        }

        if (!(wanted == _solidArea && _solidAreaApplied) && !(wanted == null && !_solidAreaApplied))
        {
            if (ClickThrough.Apply(this, wanted))
            {
                _solidArea = wanted;
                _solidAreaApplied = wanted != null;
            }
            else
            {
                _solidArea = null;
                _solidAreaApplied = false;
            }
        }

        // On macOS the area is not something the window can be given once: it is switched to
        // take or ignore the mouse as the pointer comes and goes. While it is ignoring the
        // mouse it never hears that the pointer has left, so say so here.
        if (ClickThrough.FollowPointer(this, _pressed) == false) Brain.SetHover(false);
    }

    // ---- Mouse ----

    void OnPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        var point = e.GetCurrentPoint(this);
        if (!point.Properties.IsLeftButtonPressed) return;
        e.Handled = true;

        if (e.ClickCount >= 2)
        {
            FinishPress(clicked: false);
            ToggleDance();
            return;
        }

        var at = this.PointToScreen(point.Position);
        _pressed = true;
        _dragging = false;
        _pressAt = at;
        _grabDx = at.X - Brain.FootX;
        _grabDy = at.Y - Brain.FootY;
        e.Pointer.Capture(this);
    }

    void OnPointerMoved(object? sender, PointerEventArgs e)
    {
        var local = e.GetPosition(this);
        if (!_pressed)
        {
            // Eyes follow the pointer while it is over the stage.
            double s = RenderScaling, h = _heightDip;
            double feetX = (Brain.FootX - _view.OriginX) / s, feetY = (Brain.FootY - _view.OriginY) / s;
            Brain.SetHover(true, (local.X - feetX) / (0.5 * h), (feetY - 0.72 * h - local.Y) / (0.5 * h));
            return;
        }

        var at = this.PointToScreen(local);
        if (!_dragging && (Math.Abs(at.X - _pressAt.X) > 4 || Math.Abs(at.Y - _pressAt.Y) > 4))
        {
            _dragging = true;
            Brain.BeginDrag();
        }
        if (_dragging) Brain.DragTo(at.X - _grabDx, at.Y - _grabDy);
    }

    void OnPointerReleased(object? sender, PointerReleasedEventArgs e)
    {
        if (e.InitialPressMouseButton != MouseButton.Left) return;
        // Settle the press before letting go of the pointer: releasing the capture raises
        // PointerCaptureLost, which would otherwise cancel it and swallow the click.
        FinishPress(clicked: true);
        e.Pointer.Capture(null);
    }

    void FinishPress(bool clicked)
    {
        if (!_pressed) return;
        _pressed = false;
        if (_dragging)
        {
            _dragging = false;
            Brain.EndDrag();
        }
        else if (clicked)
        {
            Brain.Poke();
        }
    }

    // ---- Commands ----

    public void ToggleDance()
    {
        if (Brain.IsDancing)
        {
            if (_app.Conductor.PartyOn) _app.SetParty(false);
            Brain.StopDance();
        }
        else
        {
            Brain.StartRandomDance();
        }
    }

    public void SetCharacter(string id)
    {
        Settings.Character = id;
        _character = _app.Library.Load(id);
        ApplyCharacter();
        _app.Settings.Save();
    }

    /// <summary>Re-reads this mate's character after the library was rescanned.</summary>
    public void ReloadCharacter()
    {
        _character = _app.Library.Load(Settings.Character);
        ApplyCharacter();
    }

    public void SetScale(double scale)
    {
        Settings.Scale = scale;
        ApplyLayout();
        _app.Settings.Save();
    }

    /// <summary>Saves what this mate currently looks like to a PNG.</summary>
    public void Snapshot(string path)
    {
        double s = RenderScaling;
        using var target = new RenderTargetBitmap(
            new PixelSize((int)Math.Ceiling(_stageW * s), (int)Math.Ceiling(_stageH * s)), new Vector(96 * s, 96 * s));
        target.Render(_view);
        target.Save(path, new PngBitmapEncoderOptions());
    }

    // ---- Right-click menu ----

    static MenuItem Item(string header, Action action)
    {
        var item = new MenuItem { Header = header };
        item.Click += (_, _) => action();
        return item;
    }

    static MenuItem Check(string header, bool on, Action<bool> action)
    {
        var item = new MenuItem { Header = header, ToggleType = MenuItemToggleType.CheckBox, IsChecked = on };
        item.Click += (_, _) => action(!on);
        return item;
    }

    static MenuItem Sub(string header, IEnumerable<Control> children)
    {
        var item = new MenuItem { Header = header };
        foreach (var child in children) item.Items.Add(child);
        return item;
    }

    void RebuildMenu()
    {
        var menu = _menu;
        var settings = _app.Settings;
        void Toggle(Action<bool> set, bool value)
        {
            set(value);
            settings.Save();
        }

        var characters = _app.Library.Available;

        // The dances on offer leave out the moves that are switched off, and are filled in
        // again whenever one is switched on or off from the checklist below.
        var moveMenu = new MenuItem { Header = "Dance move" };
        var routineMenu = new MenuItem { Header = "Routine" };
        // The character's own actions, such as having a drink: not dances, so no beat and no notes.
        var actionMenu = new MenuItem { Header = "Actions" };
        void FillDances()
        {
            actionMenu.Items.Clear();
            foreach (var a in Brain.AvailableActions()) actionMenu.Items.Add(Item(a.Name, () => Brain.DoAction(a.Id)));
            actionMenu.IsVisible = actionMenu.Items.Count > 0;

            moveMenu.Items.Clear();
            foreach (var m in Brain.AvailableMoves()) moveMenu.Items.Add(Item(m.Name, () => Brain.StartDance([m, m])));
            // A routine plays without its switched-off moves, and goes if that leaves none.
            routineMenu.Items.Clear();
            var builtIn = settings.BuiltInMoves();
            foreach (var routine in Routine.All)
            {
                var steps = routine.Resolve(builtIn);
                if (steps.Count > 0) routineMenu.Items.Add(Item(routine.Name, () => Brain.StartDance(steps)));
            }
            routineMenu.IsVisible = routineMenu.Items.Count > 0;
        }
        FillDances();

        menu.Items.Clear();
        menu.Items.Add(Item(Brain.IsDancing ? "Stop dancing" : "Dance!", ToggleDance));
        menu.Items.Add(moveMenu);
        menu.Items.Add(routineMenu);
        menu.Items.Add(MovesToUse(FillDances));
        menu.Items.Add(Check("Dance party (everyone, non-stop)", _app.Conductor.PartyOn, _app.SetParty));
        menu.Items.Add(Sub("Tempo", DeskDancer.Settings.Tempos.Select(bpm =>
            (Control)Check($"{bpm} BPM", Math.Abs(settings.Bpm - bpm) < 0.5, _ => _app.SetTempo(bpm)))));
        menu.Items.Add(new Separator());

        menu.Items.Add(actionMenu);

        menu.Items.Add(Item("Sit down", Brain.Sit));
        menu.Items.Add(Item("Take a nap", Brain.Sleep));
        menu.Items.Add(Check("Wander around", settings.Wander, v => Toggle(x => settings.Wander = x, v)));
        menu.Items.Add(Check("Dance on its own", settings.AutoDance, v => Toggle(x => settings.AutoDance = x, v)));
        if (Brain.AllActions().Count > 0)
            menu.Items.Add(Check("Do actions on its own", settings.AutoActions, v => Toggle(x => settings.AutoActions = x, v)));
        menu.Items.Add(Check("Fall to the floor when dropped", settings.Gravity, v => Toggle(x => settings.Gravity = x, v)));
        menu.Items.Add(Check("Notes and sparkles", settings.Effects, v => Toggle(x => settings.Effects = x, v)));
        menu.Items.Add(new Separator());

        string Label(CharacterInfo c) => _app.Library.ErrorFor(c.Id) == null ? c.Name : $"{c.Name} (could not load, see log)";
        var characterItems = characters
            .Select(c => (Control)Check(Label(c), c.Id.Equals(_character.Id, StringComparison.OrdinalIgnoreCase), _ => SetCharacter(c.Id)))
            .ToList();
        characterItems.Add(new Separator());
        characterItems.Add(Item("Open characters folder", () => _app.OpenCharactersFolder()));
        characterItems.Add(Item("Reload characters", _app.ReloadCharacters));
        menu.Items.Add(Sub("Character", characterItems));

        menu.Items.Add(Sub("Size", MateSettings.Sizes.Select(scale =>
            (Control)Check($"{scale * 100:0}%", Math.Abs(Settings.Scale - scale) < 0.01, _ => SetScale(scale)))));
        menu.Items.Add(Sub("Add another mate", characters.Select(c => (Control)Item(c.Name, () => _app.AddMate(c.Id)))));
        if (_app.Mates.Count > 1) menu.Items.Add(Item("Remove this mate", () => _app.RemoveMate(this)));
        menu.Items.Add(Check("Always on top", settings.AlwaysOnTop, _app.SetAlwaysOnTop));
        if (ClickThrough.Supported)
            menu.Items.Add(Check("Click through empty space", settings.ClickThrough, v => Toggle(x => settings.ClickThrough = x, v)));
        menu.Items.Add(new Separator());
        menu.Items.Add(Item("Settings...", () => _app.OpenSettings(this)));
        menu.Items.Add(Item("Quit", () => _app.Quit()));
    }

    /// <summary>
    /// The "Moves to use" checklist: this character's own dances and actions and the
    /// built-in moves, each ticked if it is switched on. It stays open while boxes are ticked, so several can
    /// be changed in one go. The last built-in move still on cannot be switched off, so there
    /// is always something to dance. <paramref name="changed"/> runs after every change.
    /// </summary>
    MenuItem MovesToUse(Action changed)
    {
        var settings = _app.Settings;
        var all = Brain.AllMoves();
        var builtIn = all.Where(m => m.Clip == null).ToList();
        var boxes = new List<(MenuItem Box, string Key, bool BuiltIn)>();

        bool LastBuiltIn(string key) => settings.MoveEnabled(key) && builtIn.Count(m => settings.MoveEnabled(m.Id)) <= 1;

        void Refresh()
        {
            foreach (var (box, key, isBuiltIn) in boxes)
            {
                box.IsChecked = settings.MoveEnabled(key);
                box.IsEnabled = !(isBuiltIn && LastBuiltIn(key));
            }
        }

        void Changed()
        {
            settings.Save();
            changed();
            // Posted, so it comes after whatever ticking the menu item does by itself.
            Dispatcher.UIThread.Post(Refresh);
        }

        MenuItem Box(DanceMove move) => BoxFor(move.Name, Brain.KeyOf(move), move.Clip == null);

        MenuItem BoxFor(string name, string key, bool isBuiltIn)
        {
            var box = new MenuItem { Header = name, ToggleType = MenuItemToggleType.CheckBox, StaysOpenOnClick = true };
            box.Click += (_, _) =>
            {
                if (!(isBuiltIn && LastBuiltIn(key))) settings.SetMoveEnabled(key, !settings.MoveEnabled(key));
                Changed();
            };
            boxes.Add((box, key, isBuiltIn));
            return box;
        }

        static MenuItem Heading(string text) => new() { Header = text, IsEnabled = false };

        var items = new List<Control>();
        var own = all.Where(m => m.Clip != null).ToList();
        if (own.Count > 0)
        {
            items.Add(Heading($"{_character.DisplayName}'s own dances"));
            items.AddRange(own.Select(Box));
            items.Add(new Separator());
        }
        var actions = Brain.AllActions();
        if (actions.Count > 0)
        {
            items.Add(Heading($"{_character.DisplayName}'s actions"));
            items.AddRange(actions.Select(a => BoxFor(a.Name, Brain.KeyOf(a), false)));
            items.Add(new Separator());
        }
        items.Add(Heading("Built-in moves"));
        items.AddRange(builtIn.Select(Box));
        items.Add(new Separator());
        var allOn = new MenuItem { Header = "Switch them all back on", StaysOpenOnClick = true };
        allOn.Click += (_, _) =>
        {
            foreach (var (_, key, _) in boxes) settings.SetMoveEnabled(key, true);
            Changed();
        };
        items.Add(allOn);
        Refresh();
        return Sub("Moves to use", items);
    }
}
