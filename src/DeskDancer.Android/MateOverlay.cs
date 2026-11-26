using Android.Content;
using Android.Graphics;
using Android.OS;
using Android.Runtime;
using Android.Util;
using Android.Views;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using DeskDancer.Characters;
using DeskDancer.Engine;
using DeskDancer.Ui;
using AView = Android.Views.View;

namespace DeskDancer.Droid;

/// <summary>
/// One mate on the phone's screen. It is two overlay windows that move together:
/// <list type="bullet">
/// <item>the stage, a transparent window a little bigger than the character, showing what
/// the shared <see cref="MateView"/> draws (see <see cref="StageCanvas"/>). It never takes
/// touches, so taps around the character reach the app underneath.</item>
/// <item>the hit box, an empty window over the character's body that takes its touches:
/// drag to carry and throw, tap to poke, double-tap to dance, long-press for settings.</item>
/// </list>
/// The desktop program does the same with one window and a clickable region inside it;
/// Android has no clickable regions, so the region is a window of its own.
/// </summary>
public sealed class MateOverlay : Java.Lang.Object, Choreographer.IFrameCallback
{
    public const string Tag = "DeskDancer";

    readonly Context _context;
    readonly IWindowManager _windows;
    readonly StageCanvas _stage;
    readonly AView _hitBox;
    readonly MateView _view = new();
    readonly WindowManagerLayoutParams _stageLp, _hitLp;
    readonly Random _rng = new();
    readonly Handler _handler = new(Looper.MainLooper!);
    readonly float _density;
    readonly int _touchSlop;
    readonly Action _longPress;

    ICharacter _character;
    double _stageW, _stageH, _feetY, _heightDip;
    double _areaCheckIn, _releaseIn = 10, _logIn;
    long _lastFrameNanos;
    readonly System.Diagnostics.Stopwatch _renderTime = new();
    int _framesSinceLog;
    double _logElapsed;
    bool _attached, _closed, _skippedFrame;

    bool _pressed, _dragging, _longPressed;
    float _downX, _downY;
    double _grabDx, _grabDy;
    long _lastTapAt;

    public MateOverlay(Context context, string characterId)
    {
        _context = context;
        _windows = context.GetSystemService(Context.WindowService).JavaCast<IWindowManager>()!;
        _density = context.Resources!.DisplayMetrics!.Density;
        _touchSlop = ViewConfiguration.Get(context)!.ScaledTouchSlop;
        _longPress = OnLongPress;

        _character = Stage.Library.Load(characterId);
        Brain = new MateBrain(Stage.Clock, Stage.Conductor, Stage.Settings, _character, _rng);
        _view.Brain = Brain;

        _stage = new StageCanvas(context, _density);
        _stageLp = NewParams(touchable: false);
        _stageLp.Alpha = StageAlpha();

        _hitBox = new AView(context);
        _hitBox.Touch += OnTouch;
        _hitLp = NewParams(touchable: true);

        ApplyCharacter();
        UpdateArea();
        double width = Brain.Right - Brain.Left, height = Brain.Floor - Brain.Top;
        Brain.Place(Brain.Left + width * (0.2 + 0.6 * _rng.NextDouble()), Brain.Top + height * 0.4);
        Brain.Drop();
        ApplyPosition();
        ApplyHitBox();

        _windows.AddView(_stage, _stageLp);
        _windows.AddView(_hitBox, _hitLp);
        _attached = true;
        Choreographer.Instance!.PostFrameCallback(this);
        Android.Util.Log.Info(Tag, $"mate '{_character.Id}' on screen, area {Brain.Left:0},{Brain.Top:0} to {Brain.Right:0},{Brain.Floor:0}, density {_density}");
    }

    public MateBrain Brain { get; }
    public ICharacter Character => _character;
    public int FrameCount { get; private set; }

    static WindowManagerLayoutParams NewParams(bool touchable)
    {
        var flags = WindowManagerFlags.NotFocusable | WindowManagerFlags.LayoutNoLimits
                    | WindowManagerFlags.LayoutInScreen | WindowManagerFlags.HardwareAccelerated;
        if (!touchable) flags |= WindowManagerFlags.NotTouchable;
        var lp = new WindowManagerLayoutParams(WindowManagerTypes.ApplicationOverlay, flags, Format.Translucent)
        {
            Gravity = GravityFlags.Top | GravityFlags.Left,
            Width = 1,
            Height = 1,
        };
        if (OperatingSystem.IsAndroidVersionAtLeast(30))
            lp.LayoutInDisplayCutoutMode = LayoutInDisplayCutoutMode.Always;
        else if (OperatingSystem.IsAndroidVersionAtLeast(28))
            lp.LayoutInDisplayCutoutMode = LayoutInDisplayCutoutMode.ShortEdges;
        return lp;
    }

    /// <summary>
    /// From Android 12 a touch only gets through another app's window when that window is
    /// see-through enough, so the stage is normally drawn just under that limit. A solid
    /// mate is drawn at full strength, and Android then keeps taps right around it from
    /// the app underneath.
    /// </summary>
    float StageAlpha()
    {
        if (Stage.Solid || !OperatingSystem.IsAndroidVersionAtLeast(31)) return 1f;
        return _context.GetSystemService(Context.InputService) is Android.Hardware.Input.InputManager input
            ? Math.Min(1f, input.MaximumObscuringOpacityForTouch)
            : 0.8f;
    }

    /// <summary>Picks up settings changed on the settings screen.</summary>
    public void Refresh()
    {
        float alpha = StageAlpha();
        if (alpha == _stageLp.Alpha) return;
        _stageLp.Alpha = alpha;
        if (_attached) _windows.UpdateViewLayout(_stage, _stageLp);
    }

    // ---- Character and layout ----

    public void SetCharacter(string id)
    {
        _character = Stage.Library.Load(id);
        Brain.Character = _character;
        ApplyCharacter();
        if (_attached) _windows.UpdateViewLayout(_stage, _stageLp);
    }

    void ApplyCharacter()
    {
        _view.Character = _character;
        // Plain bilinear smoothing. The desktop asks for more, which Skia does with mipmaps; on
        // the phone the mate is drawn on the processor, where that cost about 12 ms a frame
        // against half a millisecond. Frames are read at about the size they are shown (see
        // Stage.EnsureReady), and at that size mipmaps add nothing to how it looks.
        RenderOptions.SetBitmapInterpolationMode(_view,
            _character.PixelArt ? BitmapInterpolationMode.None : BitmapInterpolationMode.LowQuality);
        double scale = Stage.Settings.Mates.Count > 0 ? Stage.Settings.Mates[0].Scale : 1;
        // Same stage as on the desktop: wide enough for arms and side steps, tall enough for a backflip.
        double h = _heightDip = Math.Clamp(_character.PreferredHeight * scale * Stage.PhoneScale, 24, 1200);
        _stageW = Math.Ceiling(Math.Max(1.7 * h, (_character.AspectRatio + 1.0) * h));
        _stageH = Math.Ceiling(1.95 * h);
        _feetY = _stageH - Math.Round(0.14 * h);
        _stageLp.Width = (int)Math.Ceiling(_stageW * _density);
        _stageLp.Height = (int)Math.Ceiling(_stageH * _density);
        _view.CharacterHeight = h;
        _view.Scaling = _density;
        // The view is drawn off-screen, outside any window, so it is given its size by hand.
        _view.Measure(new Avalonia.Size(_stageW, _stageH));
        _view.Arrange(new Avalonia.Rect(0, 0, _stageW, _stageH));
        Brain.H = h * _density;
    }

    /// <summary>The part of the screen the mate lives in: all of it, less the status and navigation bars.</summary>
    void UpdateArea()
    {
        int left, top, right, bottom;
        if (OperatingSystem.IsAndroidVersionAtLeast(30))
        {
            var metrics = _windows.CurrentWindowMetrics;
            var bounds = metrics.Bounds;
            var insets = metrics.WindowInsets.GetInsetsIgnoringVisibility(
                WindowInsets.Type.SystemBars() | WindowInsets.Type.DisplayCutout());
            left = bounds.Left + insets.Left;
            top = bounds.Top + insets.Top;
            right = bounds.Right - insets.Right;
            bottom = bounds.Bottom - insets.Bottom;
        }
        else
        {
            var dm = new DisplayMetrics();
#pragma warning disable CA1422 // the replacement is the API 30 branch above
            _windows.DefaultDisplay!.GetRealMetrics(dm);
#pragma warning restore CA1422
            left = 0;
            top = SystemDimension("status_bar_height");
            right = dm.WidthPixels;
            bottom = dm.HeightPixels - SystemDimension("navigation_bar_height");
        }
        Brain.H = _heightDip * _density;
        Brain.Left = left;
        Brain.Right = right;
        Brain.Top = top;
        // Stand a little above the navigation bar so the whole shadow shows.
        Brain.Floor = bottom - Math.Round(0.04 * Brain.H);
    }

    int SystemDimension(string name)
    {
        var res = _context.Resources!;
        int id = res.GetIdentifier(name, "dimen", "android");
        return id > 0 ? res.GetDimensionPixelSize(id) : 0;
    }

    void ApplyPosition()
    {
        int x = (int)Math.Round(Brain.FootX - _stageW / 2 * _density);
        int y = (int)Math.Round(Brain.FootY - _feetY * _density);
        if (x != _stageLp.X || y != _stageLp.Y)
        {
            _stageLp.X = x;
            _stageLp.Y = y;
            if (_attached) _windows.UpdateViewLayout(_stage, _stageLp);
        }
        _view.OriginX = x;
        _view.OriginY = y;
    }

    /// <summary>Puts the hit box over the character's body, using the desktop's clickable outline.</summary>
    void ApplyHitBox()
    {
        double h = Brain.H;
        double halfW = (Math.Max(0.5 * _character.AspectRatio, 0.2 + 0.2 * _character.AspectRatio) + 0.16) * h;
        double top = Brain.FootY - (Brain.Body.Y + 1.22) * h, bottom = Brain.FootY + 0.1 * h;
        // Snap to a coarse grid so small movements do not move the window every frame.
        int grid = Math.Max(4, (int)(h * 0.06));
        int Snap(double v, bool up) => (int)(up ? Math.Ceiling(v / grid) : Math.Floor(v / grid)) * grid;
        int x0 = Snap(Brain.FootX - halfW, false), x1 = Snap(Brain.FootX + halfW, true);
        int y0 = Snap(top, false), y1 = Snap(bottom, true);
        if (x0 == _hitLp.X && y0 == _hitLp.Y && x1 - x0 == _hitLp.Width && y1 - y0 == _hitLp.Height) return;
        _hitLp.X = x0;
        _hitLp.Y = y0;
        _hitLp.Width = Math.Max(1, x1 - x0);
        _hitLp.Height = Math.Max(1, y1 - y0);
        if (_attached) _windows.UpdateViewLayout(_hitBox, _hitLp);
    }

    // ---- Frame loop ----

    /// <summary>Nothing energetic going on: not dancing, walking or being carried.</summary>
    bool IsCalm => Brain.State is MateState.Idle or MateState.Sit or MateState.Sleep && Brain.Energy < 0.02;

    public void DoFrame(long frameTimeNanos)
    {
        if (_closed) return;
        // Standing around does not need 60 frames a second; halve the work while nothing moves fast.
        if (IsCalm && !_skippedFrame && !_pressed)
        {
            _skippedFrame = true;
            Choreographer.Instance!.PostFrameCallback(this);
            return;
        }
        _skippedFrame = false;

        // The display stops sending frames while the screen is off, so the first one after
        // that can be a long way back; do not let the mate fly off over the gap.
        double dt = _lastFrameNanos == 0 ? 1 / 60.0 : Math.Clamp((frameTimeNanos - _lastFrameNanos) / 1e9, 0, 0.1);
        _lastFrameNanos = frameTimeNanos;
        try
        {
            Step(dt);
        }
        catch (Exception ex)
        {
            Log.Error("Frame update failed", ex);
        }
        Choreographer.Instance!.PostFrameCallback(this);
    }

    void Step(double dt)
    {
        // The screen can turn, so check its size now and then.
        _areaCheckIn -= dt;
        if (_areaCheckIn <= 0)
        {
            UpdateArea();
            _areaCheckIn = 0.5;
        }

        Brain.Update(dt);
        ApplyPosition();
        ApplyHitBox();
        _renderTime.Start();
        _stage.Render(_view, _stageLp.Width, _stageLp.Height);
        _renderTime.Stop();
        FrameCount++;
        _framesSinceLog++;
        _logElapsed += dt;

        _releaseIn -= dt;
        if (_releaseIn <= 0)
        {
            Stage.Library.ReleaseUnusedClips();
            _releaseIn = 10;
        }

        _logIn -= dt;
        if (_logIn <= 0)
        {
            _logIn = 2;
            double fps = _logElapsed > 0 ? _framesSinceLog / _logElapsed : 0;
            double renderMs = _framesSinceLog > 0 ? _renderTime.Elapsed.TotalMilliseconds / _framesSinceLog : 0;
            Android.Util.Log.Info(Tag, $"frame {FrameCount} state={Brain.State} clip={Brain.Clip} foot=({Brain.FootX:0},{Brain.FootY:0}) " +
                                       $"stage=({_stageLp.X},{_stageLp.Y} {_stageLp.Width}x{_stageLp.Height}) " +
                                       $"hit=({_hitLp.X},{_hitLp.Y} {_hitLp.Width}x{_hitLp.Height}) " +
                                       $"fps={fps:0} render={renderMs:0.0}ms");
            _framesSinceLog = 0;
            _logElapsed = 0;
            _renderTime.Reset();
        }
    }

    // ---- Touch ----

    void OnTouch(object? sender, AView.TouchEventArgs e)
    {
        var ev = e.Event;
        e.Handled = true;
        if (ev == null) return;
        // Raw coordinates are on the screen, which is what the brain works in, and they stay
        // right while the hit box moves under the finger.
        float x = ev.RawX, y = ev.RawY;
        switch (ev.ActionMasked)
        {
            case MotionEventActions.Down:
                Android.Util.Log.Info(Tag, $"touch down at ({x:0},{y:0})");
                _pressed = true;
                _dragging = false;
                _longPressed = false;
                _downX = x;
                _downY = y;
                _grabDx = x - Brain.FootX;
                _grabDy = y - Brain.FootY;
                _handler.PostDelayed(_longPress, ViewConfiguration.LongPressTimeout);
                break;
            case MotionEventActions.Move:
                if (!_pressed) break;
                if (!_dragging && (Math.Abs(x - _downX) > _touchSlop || Math.Abs(y - _downY) > _touchSlop))
                {
                    _dragging = true;
                    _handler.RemoveCallbacks(_longPress);
                    Brain.BeginDrag();
                    Android.Util.Log.Info(Tag, "drag started");
                }
                if (_dragging) Brain.DragTo(x - _grabDx, y - _grabDy);
                break;
            case MotionEventActions.Up:
                FinishPress(clicked: true);
                break;
            case MotionEventActions.Cancel:
                FinishPress(clicked: false);
                break;
        }
    }

    void FinishPress(bool clicked)
    {
        if (!_pressed) return;
        _pressed = false;
        _handler.RemoveCallbacks(_longPress);
        if (_dragging)
        {
            _dragging = false;
            Brain.EndDrag();
            Android.Util.Log.Info(Tag, $"drag ended, state={Brain.State}");
            return;
        }
        if (!clicked || _longPressed) return;

        // As on the desktop: one tap pokes, and a second one soon after starts or stops a dance.
        long now = SystemClock.UptimeMillis();
        if (now - _lastTapAt <= ViewConfiguration.DoubleTapTimeout)
        {
            _lastTapAt = 0;
            ToggleDance();
        }
        else
        {
            _lastTapAt = now;
            Brain.Poke();
            Android.Util.Log.Info(Tag, "poked");
        }
    }

    /// <summary>A long press opens the settings screen, the phone's stand-in for the right-click menu.</summary>
    void OnLongPress()
    {
        if (!_pressed || _dragging) return;
        _longPressed = true;
        var intent = new Intent(_context, typeof(MainActivity));
        intent.AddFlags(ActivityFlags.NewTask);
        _context.StartActivity(intent);
    }

    // ---- Commands ----

    public void ToggleDance()
    {
        if (Brain.IsDancing)
        {
            if (Stage.Conductor.PartyOn) Stage.Conductor.SetParty(false);
            Brain.StopDance();
        }
        else
        {
            Brain.StartRandomDance();
        }
        Android.Util.Log.Info(Tag, $"dancing: {Brain.IsDancing}");
    }

    /// <summary>
    /// Does one of the character's actions, such as Domo's Bubble Tea: played once through,
    /// with no notes. A dance party carries on without the mate until it is done.
    /// </summary>
    public void DoAction(string id)
    {
        bool started = Brain.DoAction(id);
        Android.Util.Log.Info(Tag, started ? $"action '{id}' started" : $"'{_character.Id}' has no action '{id}'");
    }

    /// <summary>Ends a dance if one is going, and otherwise leaves the mate be.</summary>
    public void Rest()
    {
        if (!Brain.IsDancing) return;
        if (Stage.Conductor.PartyOn) Stage.Conductor.SetParty(false);
        Brain.StopDance();
        Android.Util.Log.Info(Tag, "dancing: False");
    }

    public void Close()
    {
        if (_closed) return;
        _closed = true;
        _handler.RemoveCallbacks(_longPress);
        Choreographer.Instance?.RemoveFrameCallback(this);
        if (!_attached) return;
        _attached = false;
        try { _windows.RemoveView(_hitBox); } catch (Exception ex) { Log.Error("Could not remove the hit box", ex); }
        try { _windows.RemoveView(_stage); } catch (Exception ex) { Log.Error("Could not remove the stage", ex); }
    }
}
