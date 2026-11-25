using Android.Content;
using DeskDancer.Characters;
using DeskDancer.Engine;

namespace DeskDancer.Droid;

/// <summary>
/// The Avalonia application. It shows no windows of its own: Avalonia draws the mate
/// off-screen, and the overlay that <see cref="MateService"/> puts on the screen shows the
/// result (see <see cref="StageCanvas"/>). It needs no theme, as it has no controls.
/// </summary>
public sealed class MobileApp : Avalonia.Application
{
    public override void Initialize()
    {
        Name = "DeskDancer";
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
