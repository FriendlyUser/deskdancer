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

namespace DeskDancer;

/// <summary>Owns the shared state (settings, characters, beat clock) and every mate window.</summary>
public sealed class App : Application
{
    IClassicDesktopStyleApplicationLifetime? _desktop;
    DispatcherTimer? _tidy;

    public static App Instance => (App)Current!;
    public static CliOptions Options { get; set; } = new();

    public Settings Settings { get; private set; } = new();
    public CharacterLibrary Library { get; } = new();
    public BeatClock Clock { get; } = new();
    public Conductor Conductor { get; private set; } = null!;
    public List<MateWindow> Mates { get; } = [];

    public override void Initialize()
    {
        Name = "DeskDancer";
        RequestedThemeVariant = ThemeVariant.Dark;
        Conductor = new Conductor(Clock);
        Library.ExtraFolder = Options.CharactersFolder;
        Library.Scan();

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
            Clock.Bpm = Settings.Bpm;

            // The mates' pictures start being read here, on other threads, while this one
            // gets on with the theme and the windows. By the time the first window asks
            // for its character, there is usually nothing left to wait for. A mate
            // arrives by dropping in, so falling is the clip it shows first.
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

            int index = 0, count = Settings.Mates.Count;
            foreach (var mate in Settings.Mates.ToList())
                Spawn(mate, count > 1 ? (index++ + 1.0) / (count + 1) : null);

            // Pictures that nothing has shown for a while are dropped. Looking every few
            // seconds is plenty, and costs nothing when there is nothing to drop.
            _tidy = new DispatcherTimer { Interval = TimeSpan.FromSeconds(5) };
            _tidy.Tick += (_, _) => Library.ReleaseUnused();
            _tidy.Start();

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
        Clock.Bpm = bpm;
        Settings.Save();
    }

    public void SetAlwaysOnTop(bool on)
    {
        Settings.AlwaysOnTop = on;
        foreach (var mate in Mates) mate.Topmost = on;
        Settings.Save();
    }

    public void ReloadCharacters()
    {
        Library.Scan();
        // Start on all of them at once, so several different mates take no longer than one.
        foreach (var mate in Mates) Library.Preload(mate.Settings.Character);
        foreach (var mate in Mates) mate.ReloadCharacter();
    }

    public void OpenCharactersFolder()
    {
        try
        {
            string folder = CharacterLibrary.EnsureUserFolder();
            Process.Start(new ProcessStartInfo { FileName = folder, UseShellExecute = true });
        }
        catch (Exception ex)
        {
            Log.Error("Could not open the characters folder", ex);
        }
    }

    public void Quit(int exitCode = 0)
    {
        Settings.Save();
        _desktop?.Shutdown(exitCode);
    }
}
