using System.Text.Json;
using System.Text.Json.Serialization;

namespace DeskDancer;

/// <summary>One mate on the desktop.</summary>
public sealed class MateSettings
{
    /// <summary>Character id: "builtin" or the name of a folder under a characters directory.</summary>
    public string Character { get; set; } = CharacterIds.BuiltIn;
    /// <summary>Size multiplier on top of the character's own preferred height.</summary>
    public double Scale { get; set; } = 1.0;
}

public static class CharacterIds
{
    public const string BuiltIn = "builtin";
}

/// <summary>Everything the app remembers between runs.</summary>
public sealed class Settings
{
    public List<MateSettings> Mates { get; set; } = [new MateSettings()];
    public double Bpm { get; set; } = 120;
    public bool Wander { get; set; } = true;
    public bool AutoDance { get; set; } = true;
    public bool Gravity { get; set; } = true;
    public bool Effects { get; set; } = true;
    public bool AlwaysOnTop { get; set; } = true;
    /// <summary>Let clicks on the empty area around a mate reach the windows underneath.</summary>
    public bool ClickThrough { get; set; } = true;

    /// <summary>False for throwaway runs (smoke tests) that must not touch the user's saved settings.</summary>
    [JsonIgnore] public bool Persist { get; set; } = true;

    static readonly JsonSerializerOptions Json = new()
    {
        WriteIndented = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
    };

    /// <summary>Per-user folder: %APPDATA%\DeskDancer on Windows, ~/.config/DeskDancer on Linux.</summary>
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
