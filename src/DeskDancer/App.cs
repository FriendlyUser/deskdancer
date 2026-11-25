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
        Styles.Add(new FluentTheme());
        Conductor = new Conductor(Clock);
        Library.ExtraFolder = Options.CharactersFolder;
        Library.Scan();
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            _desktop = desktop;
            desktop.ShutdownMode = ShutdownMode.OnExplicitShutdown;

            // Test runs start from defaults and never write to the user's settings file.
            bool throwaway = Options.SmokeTest || Options.Fresh;
            Settings = throwaway ? new Settings { Persist = false } : Settings.Load();
            if (Options.Character != null)
            {
                Settings.Mates = [new MateSettings { Character = Options.Character }];
                Settings.Persist = false;
            }
            Clock.Bpm = Settings.Bpm;

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
            }
        }
        base.OnFrameworkInitializationCompleted();
    }

    MateWindow Spawn(MateSettings settings, double? fraction = null)
    {
        // The window asks for its character as soon as it exists. Building the window takes
        // longer than opening an image pack does, so the pack is opened on another thread
        // meanwhile and is there when it is asked for.
        Library.Preload(settings.Character);
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
        ForgetUnusedCharacters();
    }

    /// <summary>
    /// Lets go of the image packs that no mate is showing any more. Called when a mate has
    /// changed character or gone, which are the only times a pack can fall out of use.
    /// </summary>
    public void ForgetUnusedCharacters() => Library.KeepOnly(Mates.Select(mate => mate.Character));

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
