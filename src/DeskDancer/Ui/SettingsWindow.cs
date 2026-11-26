using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input.Platform;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform.Storage;
using DeskDancer.Characters;
using DeskDancer.Platform;
using DeskDancer.Updates;

namespace DeskDancer.Ui;

/// <summary>
/// The Settings window: the handful of things most people want to change, on one clean page.
/// Right-click a mate and choose Settings... to open it. The cards:
/// <list type="bullet">
/// <item>This mate: which character it is and how big.</item>
/// <item>What the mates do: wandering, dancing and acting on their own, gravity, sparkles, the tempo.</item>
/// <item>On the desktop: always on top, click-through.</item>
/// <item>Your characters: where they are kept, with buttons to open that folder, copy its
/// path, choose another one and look for characters again.</item>
/// <item>Saving: whether changes are saved as they are made, Save now, Reset to defaults,
/// and where the settings file is.</item>
/// <item>Updates: which version this is, whether it keeps itself up to date, a button to
/// look for a newer one now, and one to restart into a version that has been downloaded.</item>
/// </list>
/// Everything takes effect straight away. The switches live in <see cref="Settings"/>, which
/// the mates read as they go; <see cref="App.ApplySettings"/> passes on the two that something
/// else has to be told about.
/// </summary>
public sealed class SettingsWindow : Window
{
    // The window's colours. Change these to restyle it.
    static readonly IBrush Page = Brush("#1d2033"), CardFill = Brush("#2a2e45"), CardEdge = Brush("#474c6b"),
        Field = Brush("#171a2a"), Accent = Brush("#3cf2ff"), AccentDark = Brush("#1f8a99"), Ink = Brush("#e8ebff"),
        Muted = Brush("#9aa0c3"), Warning = Brush("#ffb85c"), ButtonFill = Brush("#343955"), ButtonHover = Brush("#42486b");

    static SolidColorBrush Brush(string colour) => new(Color.Parse(colour));

    readonly App _app;
    readonly Dictionary<string, ToggleSwitch> _switches = [];
    readonly Border _mateCard;
    readonly ComboBox _character = Choice(), _size = Choice(), _tempo = Choice();
    readonly SelectableTextBlock _folder = PathText();
    readonly Button _usualFolder, _checkNow, _restart;
    readonly TextBlock _autoNote, _saved, _status, _version, _updateNote;
    List<CharacterInfo> _characters = [];
    MateWindow? _mate;
    bool _loading;      // true while the controls are being filled in, so that is not taken for a change

    public SettingsWindow(App app, MateWindow? mate)
    {
        _app = app;
        _mate = mate;

        Title = "DeskDancer - Settings";
        Width = 920;
        Height = 700;
        MinWidth = 640;
        MinHeight = 420;
        Background = Page;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        Restyle();

        var left = Column();
        var right = Column();

        // This mate.
        var mateRows = Card(left, "This mate", out _mateCard);
        foreach (double scale in MateSettings.Sizes) _size.Items.Add($"{scale * 100:0}%");
        mateRows.Children.Add(Row("Character", _character));
        mateRows.Children.Add(Row("Size", _size));
        _character.SelectionChanged += (_, _) =>
        {
            if (!_loading && Mate is { } m && _character.SelectedIndex is >= 0 and var i && i < _characters.Count)
            {
                m.SetCharacter(_characters[i].Id);
                ShowSaving();
            }
        };
        _size.SelectionChanged += (_, _) =>
        {
            if (!_loading && Mate is { } m && _size.SelectedIndex is >= 0 and var i)
            {
                m.SetScale(MateSettings.Sizes[i]);
                ShowSaving();
            }
        };

        // What the mates do.
        var settings = app.Settings;
        var doing = Card(left, "What the mates do", out _);
        doing.Children.Add(Switch("Wander around", nameof(Settings.Wander), () => settings.Wander, on => settings.Wander = on));
        doing.Children.Add(Switch("Dance on its own", nameof(Settings.AutoDance), () => settings.AutoDance, on => settings.AutoDance = on));
        doing.Children.Add(Switch("Do actions on its own", nameof(Settings.AutoActions), () => settings.AutoActions, on => settings.AutoActions = on));
        // These two are for when there is more than one mate.
        doing.Children.Add(Switch("Bump into each other", nameof(Settings.Collide), () => settings.Collide, on => settings.Collide = on));
        doing.Children.Add(Switch("Meet up and dance together", nameof(Settings.Mingle), () => settings.Mingle, on => settings.Mingle = on));
        doing.Children.Add(Switch("Fall to the floor when dropped", nameof(Settings.Gravity), () => settings.Gravity, on => settings.Gravity = on));
        doing.Children.Add(Switch("Notes and sparkles", nameof(Settings.Effects), () => settings.Effects, on => settings.Effects = on));
        foreach (int bpm in Settings.Tempos) _tempo.Items.Add($"{bpm} BPM");
        doing.Children.Add(Row("Tempo", _tempo));
        _tempo.SelectionChanged += (_, _) =>
        {
            if (!_loading && _tempo.SelectedIndex is >= 0 and var i)
            {
                settings.Bpm = Settings.Tempos[i];
                Changed();
            }
        };

        // On the desktop.
        var desktop = Card(left, "On the desktop", out _);
        desktop.Children.Add(Switch("Always on top", nameof(Settings.AlwaysOnTop), () => settings.AlwaysOnTop, on => settings.AlwaysOnTop = on));
        if (ClickThrough.Supported)
            desktop.Children.Add(Switch("Click through empty space", nameof(Settings.ClickThrough), () => settings.ClickThrough, on => settings.ClickThrough = on));

        // Your characters.
        var characters = Card(right, "Your characters", out _);
        characters.Children.Add(Text("Characters of your own are kept in:"));
        characters.Children.Add(PathBox(_folder));
        _usualFolder = Press("Use the usual folder", () => SetFolder(null));
        characters.Children.Add(Buttons(
            Press("Open folder", () => Say(_app.OpenCharactersFolder())),
            Press("Copy path", () => Copy(_folder.Text)),
            Press("Change...", ChooseFolder),
            _usualFolder));
        characters.Children.Add(Buttons(Press("Reload characters", () =>
        {
            _app.ReloadCharacters();
            Refresh();
            Say($"Found {_app.Library.Available.Count} characters.", problem: false);
        })));
        characters.Children.Add(Note("Each character is a folder of pictures in there. The ones that come with DeskDancer are always found as well."));

        // Saving.
        var saving = Card(right, "Saving", out _);
        saving.Children.Add(Switch("Save changes as I make them", nameof(Settings.AutoSave), () => settings.AutoSave, on => settings.AutoSave = on));
        _autoNote = Note("Changes now last until you quit, unless you press \"Save now\".");
        saving.Children.Add(_autoNote);
        saving.Children.Add(Buttons(Press("Save now", SaveNow), Press("Reset to defaults", AskToReset)));
        saving.Children.Add(Text("Settings are saved in:"));
        var file = PathText();
        file.Text = Settings.FilePath;
        saving.Children.Add(PathBox(file));
        saving.Children.Add(Buttons(Press("Open folder", () => Say(_app.OpenFolder(Settings.ConfigDir)))));
        _saved = Note("");
        saving.Children.Add(_saved);

        // Updates.
        var updates = Card(right, "Updates", out _);
        _version = Text("");
        updates.Children.Add(_version);
        updates.Children.Add(Switch("Update automatically", nameof(Settings.AutoUpdate), () => settings.AutoUpdate, on => settings.AutoUpdate = on));
        _checkNow = Press("Check now", () => _ = _app.Updater.CheckAsync());
        _restart = Press("Restart to update", _app.RestartToUpdate);
        updates.Children.Add(Buttons(_checkNow, _restart, Press("Downloads page", () => Say(_app.OpenPage(Updater.DownloadPage)))));
        _updateNote = Note("");
        updates.Children.Add(_updateNote);
        _app.Updater.Changed += ShowUpdates;
        Closed += (_, _) => _app.Updater.Changed -= ShowUpdates;

        // The page: a title with a line saying what just happened, over two columns of cards.
        // (The margin keeps the cards clear of the scroll bar, when the window is too short for them all.)
        var columns = new Grid { ColumnDefinitions = new ColumnDefinitions("*,12,*"), Margin = new Thickness(0, 0, 14, 0) };
        Grid.SetColumn(left, 0);
        Grid.SetColumn(right, 2);
        columns.Children.Add(left);
        columns.Children.Add(right);
        _status = new TextBlock
        {
            Foreground = Muted,
            VerticalAlignment = VerticalAlignment.Center,
            TextAlignment = TextAlignment.Right,
            TextTrimming = TextTrimming.CharacterEllipsis,
        };
        var title = new TextBlock { Text = Title, Foreground = Accent, FontSize = 22, FontWeight = FontWeight.SemiBold, Margin = new Thickness(0, 0, 16, 0) };
        var bar = new DockPanel { Margin = new Thickness(0, 0, 0, 10) };
        DockPanel.SetDock(title, Dock.Left);
        bar.Children.Add(title);
        bar.Children.Add(_status);
        var page = new DockPanel { Margin = new Thickness(14, 10, 0, 14) };
        DockPanel.SetDock(bar, Dock.Top);
        page.Children.Add(bar);
        page.Children.Add(new ScrollViewer { Content = columns, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled });
        Content = new Border { Background = Page, Child = page };

        Refresh();
        // The menu can change the same settings while this window is out of sight.
        Activated += (_, _) => Refresh();
    }

    /// <summary>The switches on the page, by the name of the setting each one changes.</summary>
    public IReadOnlyDictionary<string, ToggleSwitch> Switches => _switches;

    /// <summary>The characters folder the page is showing.</summary>
    public string ShownFolder => _folder.Text ?? "";

    /// <summary>The mate whose character and size the page changes, if it is still on the desktop.</summary>
    MateWindow? Mate => _mate != null && _app.Mates.Contains(_mate) ? _mate : _mate = _app.Mates.FirstOrDefault();

    /// <summary>Makes <paramref name="mate"/> the mate whose character and size the page changes.</summary>
    public void ShowFor(MateWindow mate)
    {
        _mate = mate;
        Refresh();
    }

    /// <summary>Fills every control in from the settings as they are now.</summary>
    public void Refresh()
    {
        var settings = _app.Settings;
        _loading = true;
        try
        {
            foreach (var (name, box) in _switches) box.IsChecked = (bool)typeof(Settings).GetProperty(name)!.GetValue(settings)!;
            _tempo.SelectedIndex = Nearest(Settings.Tempos.Select(t => (double)t), settings.Bpm);
            _folder.Text = _app.Library.SaveFolder;
            _usualFolder.IsEnabled = !string.IsNullOrWhiteSpace(settings.CharactersFolder);

            var mate = Mate;
            _mateCard.IsVisible = mate != null;
            if (mate != null)
            {
                _characters = [.. _app.Library.Available];
                _character.ItemsSource = _characters.Select(c => c.Name).ToList();
                _character.SelectedIndex = _characters.FindIndex(c => c.Id.Equals(mate.Settings.Character, StringComparison.OrdinalIgnoreCase));
                _size.SelectedIndex = Nearest(MateSettings.Sizes, mate.Settings.Scale);
            }
        }
        finally
        {
            _loading = false;
        }
        ShowSaving();
        ShowUpdates();
    }

    /// <summary>What the Updates card is saying.</summary>
    public string UpdateNote => _updateNote.Text ?? "";

    /// <summary>Says, on the Updates card, which version this is and how keeping it up to date is going.</summary>
    void ShowUpdates()
    {
        var updater = _app.Updater;
        _version.Text = $"This is DeskDancer {updater.Version}.";
        _switches[nameof(Settings.AutoUpdate)].IsEnabled = updater.CanUpdate;
        _checkNow.IsEnabled = updater.CanUpdate && updater.State is not (UpdateState.Checking or UpdateState.Downloading);
        _restart.IsVisible = updater.State == UpdateState.Ready;
        string looked = updater.LastChecked is { } at ? $" Last looked at {at:HH:mm}." : "";
        _updateNote.Text = updater.State switch
        {
            UpdateState.Unavailable => "This copy cannot update itself: it was not put in by one of DeskDancer's own downloads. New versions are on the downloads page.",
            UpdateState.Checking => "Looking for a newer version...",
            UpdateState.Downloading => $"Downloading version {updater.NewVersion}: {updater.Progress}%",
            UpdateState.Ready => _app.Settings.AutoUpdate
                ? $"Version {updater.NewVersion} is ready. It goes in the next time the mates are at rest, or now if you press \"Restart to update\"."
                : $"Version {updater.NewVersion} is ready. It goes in the next time DeskDancer starts, or now if you press \"Restart to update\".",
            UpdateState.Failed => $"Could not update: {updater.Problem}",
            _ => (updater.LastChecked != null ? "This is the newest version." : _app.Settings.AutoUpdate ? "It looks for a newer version a few times a day." : "It only looks for a newer version when you ask.") + looked,
        };
        _updateNote.Foreground = updater.State == UpdateState.Failed ? Warning : Muted;
    }

    static int Nearest(IEnumerable<double> choices, double value) =>
        choices.Select((choice, index) => (Distance: Math.Abs(choice - value), index)).Min().index;

    /// <summary>Saves what this window looks like to a PNG.</summary>
    public void Snapshot(string path)
    {
        if (Content is not Control content || content.Bounds.Width < 1 || content.Bounds.Height < 1) return;
        double s = RenderScaling;
        using var target = new RenderTargetBitmap(
            new PixelSize((int)Math.Ceiling(content.Bounds.Width * s), (int)Math.Ceiling(content.Bounds.Height * s)), new Vector(96 * s, 96 * s));
        target.Render(content);
        target.Save(path, new PngBitmapEncoderOptions());
    }

    // ---- Changing things ----

    /// <summary>Remembers that a setting changed, and lets the app act on it.</summary>
    void Changed(bool saveNow = false)
    {
        bool saved = _app.Settings.Save(saveNow);
        _app.ApplySettings();
        ShowUpdates();
        if (saved) ShowSaving();
        else Say("The settings could not be saved; the log says why.");
    }

    void SaveNow()
    {
        if (_app.Settings.Save(now: true)) ShowSaving($"Saved to {Settings.FilePath}");
        else Say("The settings could not be saved; the log says why.");
    }

    async void AskToReset()
    {
        if (await Confirm("Reset to defaults",
                "Put the tempo, every switch and the moves back to how they started?\n\nYour characters and mates are kept."))
            ResetToDefaults();
    }

    /// <summary>Puts the tempo, every switch and the moves back to how a new copy of the program has them.</summary>
    public void ResetToDefaults()
    {
        _app.Settings.ResetToDefaults();
        bool saved = _app.Settings.Save(now: true);
        _app.ApplySettings();
        Refresh();
        if (saved) ShowSaving("Everything is back to its default.");
        else Say("The settings could not be saved; the log says why.");
    }

    async void ChooseFolder()
    {
        var picked = await StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
        {
            Title = "Choose a folder for your characters",
            AllowMultiple = false,
        });
        if (picked.Count > 0 && picked[0].TryGetLocalPath() is { } path) SetFolder(path);
    }

    /// <summary>Keeps the user's characters in <paramref name="folder"/> from now on (null: the usual folder).</summary>
    void SetFolder(string? folder)
    {
        string? problem = _app.SetCharactersFolder(folder);
        Refresh();
        if (problem != null) Say(problem);
        else Say($"Your characters are now kept in {_app.Library.SaveFolder}", problem: false);
    }

    async void Copy(string? text)
    {
        if (string.IsNullOrEmpty(text) || Clipboard is not { } clipboard) return;
        await clipboard.SetTextAsync(text);
        Say("Copied.", problem: false);
    }

    /// <summary>Shows a message at the top of the window: a problem, unless told otherwise. Null clears it.</summary>
    void Say(string? message, bool problem = true)
    {
        _status.Text = message ?? "";
        _status.Foreground = problem ? Warning : Muted;
    }

    /// <summary>Says, on the Saving card, whether what is on the page has been written to disk.</summary>
    void ShowSaving(string? message = null)
    {
        var settings = _app.Settings;
        _autoNote.IsVisible = !settings.AutoSave;
        _saved.Text = !settings.Persist ? "This run was started without saved settings, so nothing here is saved."
            : message ?? (settings.Unsaved ? "Not saved yet." : "Saved.");
    }

    /// <summary>Asks a yes or no question in a small window of its own.</summary>
    async Task<bool> Confirm(string title, string question)
    {
        bool yes = false;
        var dialog = new Window
        {
            Title = title,
            SizeToContent = SizeToContent.WidthAndHeight,
            CanResize = false,
            ShowInTaskbar = false,
            Background = Page,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
        };
        var answers = Buttons(
            Press("OK", () =>
            {
                yes = true;
                dialog.Close();
            }),
            Press("Cancel", dialog.Close));
        answers.HorizontalAlignment = HorizontalAlignment.Right;
        var words = Text(question);
        words.MaxWidth = 420;
        dialog.Content = new StackPanel { Margin = new Thickness(20), Spacing = 16, Children = { words, answers } };
        foreach (var (key, value) in Resources) dialog.Resources[key] = value;
        await dialog.ShowDialog(this);
        return yes;
    }

    // ---- Building blocks ----

    /// <summary>
    /// Gives the buttons, lists and switches of this window its own colours, by overriding
    /// the theme's for this window alone: the mates' menu keeps the look it has.
    /// </summary>
    void Restyle()
    {
        foreach (string key in new[] { "ButtonBackground", "ComboBoxBackground" }) Resources[key] = ButtonFill;
        foreach (string key in new[] { "ButtonBackgroundPointerOver", "ComboBoxBackgroundPointerOver" }) Resources[key] = ButtonHover;
        foreach (string key in new[] { "ButtonBorderBrush", "ButtonBorderBrushPointerOver", "ComboBoxBorderBrush", "ComboBoxBorderBrushPointerOver" })
            Resources[key] = AccentDark;
        foreach (string key in new[] { "ButtonForeground", "ButtonForegroundPointerOver", "ComboBoxForeground" }) Resources[key] = Ink;
        Resources["ButtonBackgroundPressed"] = Accent;
        Resources["ButtonForegroundPressed"] = Brushes.Black;
        // A switch that is on shows the accent colour, so on and off can be told apart at a glance.
        foreach (string key in new[] { "ToggleSwitchFillOn", "ToggleSwitchFillOnPointerOver", "ToggleSwitchFillOnPressed",
                     "ToggleSwitchStrokeOn", "ToggleSwitchStrokeOnPointerOver", "ToggleSwitchStrokeOnPressed" })
            Resources[key] = Accent;
        foreach (string key in new[] { "ToggleSwitchKnobFillOn", "ToggleSwitchKnobFillOnPointerOver", "ToggleSwitchKnobFillOnPressed" })
            Resources[key] = Field;
    }

    static StackPanel Column() => new() { Spacing = 12 };

    /// <summary>A card: a rounded panel with a heading, for one group of settings. Returns the column its rows go in.</summary>
    static StackPanel Card(Panel parent, string title, out Border card)
    {
        var rows = new StackPanel { Spacing = 8 };
        rows.Children.Add(new TextBlock { Text = title, Foreground = Accent, FontSize = 18, FontWeight = FontWeight.SemiBold });
        card = new Border
        {
            Background = CardFill,
            BorderBrush = CardEdge,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(12),
            Padding = new Thickness(16, 12, 16, 14),
            Child = rows,
        };
        parent.Children.Add(card);
        return rows;
    }

    static TextBlock Text(string text) => new() { Text = text, Foreground = Ink, TextWrapping = TextWrapping.Wrap };

    /// <summary>A quieter line, for explanations.</summary>
    static TextBlock Note(string text) => new() { Text = text, Foreground = Muted, TextWrapping = TextWrapping.Wrap };

    static ComboBox Choice() => new() { MinWidth = 190, HorizontalAlignment = HorizontalAlignment.Right };

    static SelectableTextBlock PathText() => new() { Foreground = Ink, TextWrapping = TextWrapping.Wrap };

    /// <summary>A box showing a folder's path, which wraps instead of running off the edge, and can be selected.</summary>
    static Border PathBox(Control path) => new()
    {
        Background = Field,
        CornerRadius = new CornerRadius(6),
        Padding = new Thickness(10, 8),
        Child = path,
    };

    /// <summary>A row with its caption on the left and a control on the right.</summary>
    static DockPanel Row(string caption, Control control)
    {
        var row = new DockPanel { MinHeight = 34 };
        DockPanel.SetDock(control, Dock.Right);
        row.Children.Add(control);
        row.Children.Add(new TextBlock { Text = caption, Foreground = Ink, VerticalAlignment = VerticalAlignment.Center });
        return row;
    }

    /// <summary>A row with an on/off switch, which reads and changes one setting.</summary>
    DockPanel Switch(string caption, string setting, Func<bool> get, Action<bool> set)
    {
        var box = new ToggleSwitch { OnContent = null, OffContent = null, MinWidth = 0, IsChecked = get(), VerticalAlignment = VerticalAlignment.Center };
        box.IsCheckedChanged += (_, _) =>
        {
            if (_loading) return;
            set(box.IsChecked == true);
            // Switching automatic saving on or off is itself saved, so the choice is still there next time.
            Changed(saveNow: setting == nameof(Settings.AutoSave));
        };
        _switches[setting] = box;
        return Row(caption, box);
    }

    static Button Press(string text, Action pressed)
    {
        var button = new Button { Content = text, CornerRadius = new CornerRadius(8), Padding = new Thickness(12, 6), Margin = new Thickness(0, 0, 8, 0) };
        button.Click += (_, _) => pressed();
        return button;
    }

    /// <summary>A row of buttons, which wraps onto the next line when the window is narrow.</summary>
    static WrapPanel Buttons(params Button[] buttons)
    {
        var row = new WrapPanel { Orientation = Orientation.Horizontal, ItemSpacing = 0, LineSpacing = 8 };
        foreach (var button in buttons) row.Children.Add(button);
        return row;
    }
}
