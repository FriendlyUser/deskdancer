using System.Text.Json;
using System.Text.Json.Serialization;
using DeskDancer.Engine;

namespace DeskDancer;

/// <summary>One mate on the desktop.</summary>
public sealed class MateSettings
{
    /// <summary>Character id: "builtin" or the name of a folder under a characters directory.</summary>
    public string Character { get; set; } = CharacterIds.Default;
    /// <summary>Size multiplier on top of the character's own preferred height.</summary>
    public double Scale { get; set; } = 1.0;
}

public static class CharacterIds
{
    /// <summary>The character drawn in code. Always there, so it is what every other one falls back to.</summary>
    public const string BuiltIn = "builtin";

    /// <summary>
    /// What a new mate starts as: the Mochi image pack in the characters folder next to the
    /// program. A mate whose saved settings name another character keeps that one.
    /// </summary>
    public const string Default = "mochi";
}

/// <summary>Everything the app remembers between runs.</summary>
public sealed class Settings
{
    public List<MateSettings> Mates { get; set; } = [new MateSettings()];
    public double Bpm { get; set; } = 120;
    public bool Wander { get; set; } = true;
    public bool AutoDance { get; set; } = true;
    /// <summary>Now and then do one of the character's own actions, such as having a drink, unasked.</summary>
    public bool AutoActions { get; set; } = true;
    public bool Gravity { get; set; } = true;
    public bool Effects { get; set; } = true;
    public bool AlwaysOnTop { get; set; } = true;
    /// <summary>Let clicks on the empty area around a mate reach the windows underneath.</summary>
    public bool ClickThrough { get; set; } = true;

    /// <summary>
    /// Dance moves and actions switched off. A built-in move is listed by its id
    /// ("backflip"), and a character's own dance or action by the character and its clip
    /// ("mochi/dance_spin", "domo/action_fart"), so that switching one off leaves other
    /// characters' alone. A move that is switched off is left out of the Dance move menu,
    /// random dances, dancing on its own, the dance party and routines; an action, out of
    /// the Actions menu and what the mate does on its own.
    /// </summary>
    public List<string> DisabledMoves { get; set; } = [];

    public bool MoveEnabled(string key) => !DisabledMoves.Contains(key, StringComparer.OrdinalIgnoreCase);

    public void SetMoveEnabled(string key, bool on)
    {
        DisabledMoves.RemoveAll(k => k.Equals(key, StringComparison.OrdinalIgnoreCase));
        if (!on) DisabledMoves.Add(key);
    }

    /// <summary>
    /// The built-in moves still switched on. The menu never lets the last of them go, but
    /// should the settings file switch every one off, they all count as on: there is
    /// always something to dance.
    /// </summary>
    public IReadOnlyList<DanceMove> BuiltInMoves()
    {
        var on = Moves.All.Where(m => MoveEnabled(m.Id)).ToList();
        return on.Count > 0 ? on : Moves.All;
    }

    /// <summary>False for throwaway runs (smoke tests) that must not touch the user's saved settings.</summary>
    [JsonIgnore] public bool Persist { get; set; } = true;

    static readonly JsonSerializerOptions Json = new()
    {
        WriteIndented = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
    };

    /// <summary>
    /// Per-user folder: %APPDATA%\DeskDancer on Windows, ~/.config/DeskDancer on Linux,
    /// ~/Library/Application Support/DeskDancer on macOS.
    /// </summary>
    public static string ConfigDir
    {
        get
        {
            string root = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            if (string.IsNullOrEmpty(root))
                root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".config");
            return Path.Combine(root, "DeskDancer");
        }
    }

    static string FilePath => Path.Combine(ConfigDir, "settings.json");

    public static Settings Load()
    {
        try
        {
            if (File.Exists(FilePath))
            {
                var loaded = JsonSerializer.Deserialize<Settings>(File.ReadAllText(FilePath), Json);
                if (loaded != null)
                {
                    loaded.Mates ??= [];
                    loaded.DisabledMoves ??= [];
                    // Something must be left to dance: a file that switches off every
                    // built-in move switches none of them off.
                    if (Moves.All.All(m => !loaded.MoveEnabled(m.Id)))
                        loaded.DisabledMoves.RemoveAll(k => Moves.All.Any(m => m.Id.Equals(k, StringComparison.OrdinalIgnoreCase)));
                    if (loaded.Mates.Count == 0) loaded.Mates.Add(new MateSettings());
                    foreach (var m in loaded.Mates) m.Scale = Math.Clamp(m.Scale, 0.25, 4);
                    return loaded;
                }
            }
        }
        catch (Exception ex)
        {
            Log.Error("Could not read settings, using defaults", ex);
        }
        return new Settings();
    }

    public void Save()
    {
        if (!Persist) return;
        try
        {
            Directory.CreateDirectory(ConfigDir);
            File.WriteAllText(FilePath, JsonSerializer.Serialize(this, Json));
        }
        catch (Exception ex)
        {
            Log.Error("Could not save settings", ex);
        }
    }
}

/// <summary>Minimal file logger; a windowed app on Windows has no console to print to.</summary>
public static class Log
{
    static readonly object Gate = new();
    public static bool Verbose { get; set; }

    static string FilePath => Path.Combine(Settings.ConfigDir, "deskdancer.log");

    public static void Info(string message)
    {
        if (Verbose) Console.Error.WriteLine(message);
    }

    public static void Error(string message, Exception? ex = null)
    {
        string line = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {message}{(ex == null ? "" : ": " + ex)}";
        Console.Error.WriteLine(line);
        try
        {
            lock (Gate)
            {
                Directory.CreateDirectory(Settings.ConfigDir);
                var info = new FileInfo(FilePath);
                if (info.Exists && info.Length > 512 * 1024) info.Delete();
                File.AppendAllText(FilePath, line + Environment.NewLine);
            }
        }
        catch
        {
            // Logging must never take the app down.
        }
    }
}
