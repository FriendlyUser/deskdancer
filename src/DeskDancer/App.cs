using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Styling;
using Avalonia.Threading;
using Avalonia.Themes.Fluent;
using DeskDancer.Characters;
using DeskDancer.Engine;
using DeskDancer.Tools;
using DeskDancer.Ui;
using DeskDancer.Updates;

namespace DeskDancer;

/// <summary>Owns the shared state (settings, characters, beat clock) and every mate window.</summary>
public sealed class App : Application
{
    IClassicDesktopStyleApplicationLifetime? _desktop;

    public static App Instance => (App)Current!;
    public static CliOptions Options { get; set; } = new();

    public Settings Settings { get; private set; } = new();
    public CharacterLibrary Library { get; } = new();
    public BeatClock Clock { get; } = new();
    public Conductor Conductor { get; private set; } = null!;
    public List<MateWindow> Mates { get; } = [];
    /// <summary>The Settings window while it is open.</summary>
    public SettingsWindow? SettingsWindow { get; private set; }

    Updater? _updater;
    /// <summary>Keeps the program up to date from its releases; see <see cref="Updates.Updater"/>.</summary>
    public Updater Updater => _updater ??= new Updater(Options.UpdateFeed, Environment.GetCommandLineArgs().Skip(1).ToArray());

    /// <summary>How long after starting the first look for a newer version is taken, and how often after that.</summary>
    static readonly TimeSpan FirstUpdateCheck = TimeSpan.FromSeconds(30), UpdateCheckEvery = TimeSpan.FromHours(6);

    public override void Initialize()
    {
        Name = "DeskDancer";
        RequestedThemeVariant = ThemeVariant.Dark;
        // The party dances only the moves that are switched on; Settings is read each time, as
        // it is replaced once the saved settings are loaded.
        Conductor = new Conductor(Clock) { Pool = () => Settings.BuiltInMoves() };
        if (!Options.IsTool)
        {
            // Test runs start from defaults and never write to the user's settings file.
            bool throwaway = Options.SmokeTest || Options.Fresh;
            Settings = throwaway ? new Settings { Persist = false } : Settings.Load();
            if (Options.Character != null)
            {
                Settings.Mates = [new MateSettings { Character = Options.Character }];
                Settings.Persist = false;
            }
            // The settings say where the user keeps their own characters, so they are read first.
            Library.ChosenFolder = Settings.CharactersFolder;
        }
        Library.ExtraFolder = Options.CharactersFolder;
        Library.Scan();

        if (!Options.IsTool)
        {
            Clock.Bpm = Settings.Bpm;

            // With mates on screen an image pack holds only the clips it is showing; see
            // CharacterLibrary. The mates' packs start being read here, on a thread of
            // their own, while this one gets on with the theme and the windows. By the time
            // the first window asks for its character, there is usually nothing left to
            // wait for. A mate arrives by dropping in, so falling is the clip it shows first.
            Library.ClipsOnDemand = true;
            foreach (var mate in Settings.Mates) Library.Preload(mate.Character, "fall");
        }

        Styles.Add(new FluentTheme());
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            _desktop = desktop;
            desktop.ShutdownMode = ShutdownMode.OnExplicitShutdown;

            // Every so often the clips that have gone unshown for a while are dropped.
            DispatcherTimer.Run(() =>
            {
                Library.ReleaseUnusedClips();
                return true;
            }, TimeSpan.FromSeconds(10));

            int index = 0, count = Settings.Mates.Count;
            foreach (var mate in Settings.Mates.ToList())
                Spawn(mate, count > 1 ? (index++ + 1.0) / (count + 1) : null);

            if (Options.SmokeTest)
            {
                SmokeTest.Start(this, Options);
            }
            else
            {
                // A bug in one menu action should not take the mate off the desktop.
                Dispatcher.UIThread.UnhandledException += (_, e) =>
                {
                    Log.Error("Unhandled error", e.Exception);
                    e.Handled = true;
                };
                KeepUpToDate();
            }
        }
        base.OnFrameworkInitializationCompleted();
    }

    MateWindow Spawn(MateSettings settings, double? fraction = null)
    {
        var window = new MateWindow(this, settings);
        Mates.Add(window);
        window.PlaceOnScreen(fraction);
        window.Show();
        return window;
    }

    public MateWindow AddMate(string characterId)
    {
        var settings = new MateSettings { Character = characterId };
        Settings.Mates.Add(settings);
        Settings.Save();
        return Spawn(settings);
    }

    public void RemoveMate(MateWindow window)
    {
        if (Mates.Count <= 1) return;
        Mates.Remove(window);
        Settings.Mates.Remove(window.Settings);
        Settings.Save();
        window.Close();
    }

    public void SetParty(bool on) => Conductor.SetParty(on);

    public void SetTempo(double bpm)
    {
        Settings.Bpm = bpm;
        Settings.Save();
        ApplySettings();
    }

    public void SetAlwaysOnTop(bool on)
    {
        Settings.AlwaysOnTop = on;
        Settings.Save();
        ApplySettings();
    }

    /// <summary>
    /// Passes on the settings that something other than <see cref="Settings"/> has to know
    /// about: the tempo to the clock, and "always on top" to the windows. The rest are read
    /// from it as they are needed. Called after any setting has changed.
    /// </summary>
    public void ApplySettings()
    {
        if (Math.Abs(Clock.Bpm - Math.Clamp(Settings.Bpm, 40, 240)) > 0.001) Clock.Bpm = Settings.Bpm;
        foreach (var mate in Mates) mate.Topmost = Settings.AlwaysOnTop;
    }

    /// <summary>
    /// Opens the Settings window, or brings it to the front. <paramref name="mate"/> is the
    /// mate whose menu asked for it: the window can change that mate's character and size.
    /// </summary>
    public SettingsWindow OpenSettings(MateWindow? mate = null)
    {
        if (SettingsWindow is { } open)
        {
            if (mate != null) open.ShowFor(mate);
            open.Activate();
            return open;
        }
        var window = new SettingsWindow(this, mate ?? Mates.FirstOrDefault());
        window.Closed += (_, _) => SettingsWindow = null;
        SettingsWindow = window;
        window.Show();
        return window;
    }

    /// <summary>
    /// Keeps the user's own characters in <paramref name="folder"/> from now on, or in the
    /// usual folder for null, and looks for characters again. The folder is made if it is
    /// not there. Returns what went wrong, or null if nothing did (and then nothing changes).
    /// </summary>
    public string? SetCharactersFolder(string? folder)
    {
        if (string.IsNullOrWhiteSpace(folder)) folder = null;
        if (folder != null)
        {
            try
            {
                folder = Path.GetFullPath(folder.Trim());
                Directory.CreateDirectory(folder);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException or NotSupportedException)
            {
                return $"Characters cannot be kept in {folder}: {ex.Message}";
            }
            // Choosing the usual folder is the same as choosing none.
            if (Path.GetFullPath(CharacterLibrary.UserFolder).Equals(folder, PathComparison)) folder = null;
        }
        Settings.CharactersFolder = folder;
        Library.ChosenFolder = folder;
        Settings.Save();
        ReloadCharacters();
        return null;
    }

    /// <summary>How folder names are compared here: Windows and macOS do not tell capitals apart, Linux does.</summary>
    static StringComparison PathComparison =>
        OperatingSystem.IsLinux() ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;

    public void ReloadCharacters()
    {
        Library.Scan();
        // Start on all of them now, so none waits for the window of the one before it.
        foreach (var mate in Mates) Library.Preload(mate.Settings.Character);
        foreach (var mate in Mates) mate.ReloadCharacter();
    }

    /// <summary>Shows the folder the user's own characters are kept in, making it first if need be.</summary>
    public string? OpenCharactersFolder()
    {
        try
        {
            return OpenFolder(Library.EnsureSaveFolder());
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Log.Error("Could not make the characters folder", ex);
            return "Could not make the characters folder: " + ex.Message;
        }
    }

    /// <summary>Shows a folder in the system's file manager. Returns what went wrong, or null.</summary>
    public string? OpenFolder(string folder)
    {
        try
        {
            Process.Start(new ProcessStartInfo { FileName = folder, UseShellExecute = true });
            return null;
        }
        catch (Exception ex)
        {
            Log.Error($"Could not open the folder {folder}", ex);
            return $"Could not open the folder {folder}: {ex.Message}";
        }
    }

    /// <summary>Shows a web page in the browser. Returns what went wrong, or null.</summary>
    public string? OpenPage(string address)
    {
        try
        {
            Process.Start(new ProcessStartInfo { FileName = address, UseShellExecute = true });
            return null;
        }
        catch (Exception ex)
        {
            Log.Error($"Could not open {address}", ex);
            return $"Could not open {address}: {ex.Message}";
        }
    }

    /// <summary>
    /// The self-update loop. A mate can be left on the desktop for weeks, so being up to date
    /// cannot wait for the program to be started again: it looks for a newer version shortly
    /// after starting and a few times a day after that, downloads one it finds, and restarts
    /// into it at a quiet moment. All of that is switched off by "Update automatically" on the
    /// Settings window, which then only looks when asked.
    /// </summary>
    void KeepUpToDate()
    {
        if (!Updater.CanUpdate) return;
        void Look()
        {
            if (Settings.AutoUpdate) _ = Updater.CheckAsync();
        }
        // A feed given on the command line is there to try updates out, so it is looked at straight away.
        DispatcherTimer.RunOnce(Look, Options.UpdateFeed != null ? TimeSpan.FromSeconds(2) : FirstUpdateCheck);
        DispatcherTimer.Run(() =>
        {
            Look();
            return true;
        }, UpdateCheckEvery);
        DispatcherTimer.Run(() =>
        {
            if (Settings.AutoUpdate && Updater.State == UpdateState.Ready && AtRest()) RestartToUpdate();
            return true;
        }, TimeSpan.FromSeconds(2));
    }

    /// <summary>
    /// True when nobody would mind the mates going away for a moment: none is being carried,
    /// thrown, or in the middle of a dance or an action, no menu or Settings window is open,
    /// and nothing has been changed that would be lost by closing.
    /// </summary>
    bool AtRest() =>
        SettingsWindow == null && !Settings.Unsaved
        && Mates.All(m => !m.MenuOpen && m.Brain.State is MateState.Idle or MateState.Walk or MateState.Sit or MateState.Sleep);

    /// <summary>
    /// Closes the program so that the version that has been downloaded can go in; Velopack's
    /// updater then starts the new one. Nothing happens if no newer version is ready.
    /// </summary>
    public void RestartToUpdate()
    {
        if (Updater.State != UpdateState.Ready) return;
        Settings.Save();
        if (Updater.BeginRestart()) Quit();
    }

    public void Quit(int exitCode = 0)
    {
        Settings.Save();
        _desktop?.Shutdown(exitCode);
    }
}
