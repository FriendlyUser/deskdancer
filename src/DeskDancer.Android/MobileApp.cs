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
    static ISharedPreferences? _prefs;

    /// <summary>Phones are held closer than monitors, so mates start a little smaller there.</summary>
    public const double PhoneScale = 0.8;

    public static Settings Settings { get; private set; } = new();
    public static CharacterLibrary Library { get; } = new();
    public static BeatClock Clock { get; } = new();
    public static Conductor Conductor { get; private set; } = null!;

    public static void EnsureReady(Context context)
    {
        if (_ready) return;
        _prefs = context.GetSharedPreferences("deskdancer", FileCreationMode.Private);
        // Read each frame at about the size it is shown (a mate of the usual height, plus a
        // quarter for squash and stretch), so it is smoothed once, here, and not every frame.
        double density = context.Resources!.DisplayMetrics!.Density;
        SpritePackLoader.MaxFrameSide = Math.Clamp((int)Math.Round(150 * PhoneScale * density * 1.25), 160, 640);
        // The characters in the APK, which, as on the desktop, give way to one of the user's own
        // of the same name (see CharacterFolder).
        Library.ShippedFolder = CharacterAssets.Unpack(context);
        Library.Scan();
        Settings = Settings.Load();
        Clock.Bpm = Settings.Bpm;
        // The party dances only the moves that are switched on, as on the desktop.
        Conductor = new Conductor(Clock) { Pool = () => Settings.BuiltInMoves() };
        // As on the desktop: a pack keeps only the clips it is showing in memory.
        Library.ClipsOnDemand = true;
        _ready = true;
    }

    /// <summary>
    /// Draw the mate at full strength. Otherwise, from Android 12, it is drawn slightly
    /// see-through, which Android requires for taps to reach the app underneath it.
    /// </summary>
    public static bool Solid
    {
        get => _prefs?.GetBoolean("solid", false) ?? false;
        set => _prefs?.Edit()?.PutBoolean("solid", value)?.Apply();
    }

    /// <summary>
    /// The folder of the user's own characters, chosen in Android's folder picker: the picker's
    /// address for it (a content:// tree URI), or null if none has been chosen.
    /// </summary>
    public static string? CharactersFolder
    {
        get => _prefs?.GetString("characters-folder", null);
        set => _prefs?.Edit()?.PutString("characters-folder", value)?.Apply();
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
