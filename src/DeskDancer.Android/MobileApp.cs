using Android.Content;
using Avalonia.Styling;
using Avalonia.Themes.Fluent;
using DeskDancer.Characters;
using DeskDancer.Engine;

namespace DeskDancer.Droid;

/// <summary>
/// The Avalonia application. It shows no windows of its own: the mate is drawn by an
/// Avalonia view inside the overlay that <see cref="MateService"/> puts on the screen.
/// </summary>
public sealed class MobileApp : Avalonia.Application
{
    public override void Initialize()
    {
        Name = "DeskDancer";
        RequestedThemeVariant = ThemeVariant.Dark;
        // The view that hosts the mate is a content control, which needs a theme to show its content.
        Styles.Add(new FluentTheme());
    }
}

/// <summary>What the desktop program keeps in its App: settings, characters and the beat.</summary>
public static class Stage
{
    static bool _ready;

    public static Settings Settings { get; private set; } = new();
    public static CharacterLibrary Library { get; } = new();
    public static BeatClock Clock { get; } = new();
    public static Conductor Conductor { get; private set; } = null!;

    public static void EnsureReady(Context context)
    {
        if (_ready) return;
        Library.ExtraFolder = CharacterAssets.Unpack(context);
        Library.Scan();
        Settings = Settings.Load();
        Clock.Bpm = Settings.Bpm;
        Conductor = new Conductor(Clock);
        // As on the desktop: a pack keeps only the clips it is showing in memory.
        Library.ClipsOnDemand = true;
        _ready = true;
    }

    public static string CharacterId
    {
        get => Settings.Mates.Count > 0 ? Settings.Mates[0].Character : new MateSettings().Character;
        set
        {
            if (Settings.Mates.Count == 0) Settings.Mates.Add(new MateSettings());
            Settings.Mates[0].Character = value;
            Settings.Save();
        }
    }
}
