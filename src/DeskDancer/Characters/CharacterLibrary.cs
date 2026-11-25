using DeskDancer.Platform;

namespace DeskDancer.Characters;

/// <summary>A character the user can pick, before any of its images are loaded.</summary>
public sealed record CharacterInfo(string Id, string Name, string? Folder);

/// <summary>
/// Finds character packs and loads them on demand. Packs live in a "characters" folder
/// next to the executable and in the per-user one under the settings directory.
/// </summary>
public sealed class CharacterLibrary
{
    readonly Dictionary<string, ICharacter> _loaded = new(StringComparer.OrdinalIgnoreCase);
    readonly Dictionary<string, string> _errors = new(StringComparer.OrdinalIgnoreCase);
    readonly RemixCharacter _builtIn = new();
    List<CharacterInfo> _available = [];

    /// <summary>Extra folder to scan, from the command line.</summary>
    public string? ExtraFolder { get; set; }

    public static string AppFolder => Path.Combine(AppContext.BaseDirectory, "characters");
    public static string UserFolder => Path.Combine(Settings.ConfigDir, "characters");

    public IReadOnlyList<CharacterInfo> Available => _available;
    public ICharacter BuiltIn => _builtIn;

    /// <summary>Why a pack failed to load, if it did.</summary>
    public string? ErrorFor(string id) => _errors.GetValueOrDefault(id);

    public void Scan()
    {
        _loaded.Clear();
        _errors.Clear();
        var list = new List<CharacterInfo> { new(CharacterIds.BuiltIn, _builtIn.DisplayName, null) };
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { CharacterIds.BuiltIn };

        // Later folders win nothing: the first pack with a given folder name is the one used.
        foreach (var root in new[] { ExtraFolder, UserFolder, AppFolder })
        {
            if (string.IsNullOrEmpty(root) || !Directory.Exists(root)) continue;
            try
            {
                foreach (var dir in Directory.EnumerateDirectories(root).OrderBy(d => d, StringComparer.OrdinalIgnoreCase))
                {
                    string id = Path.GetFileName(dir);
                    if (id.StartsWith('.') || id.StartsWith('_') || !seen.Add(id)) continue;
                    if (!SpritePackLoader.LooksLikePack(dir)) continue;
                    list.Add(new CharacterInfo(id, SpritePackLoader.ReadDisplayName(dir), dir));
                }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                Log.Error($"Could not scan {root}", ex);
            }
        }
        _available = list;
    }

    /// <summary>Loads a character, falling back to the built-in one if the pack is missing or broken.</summary>
    public ICharacter Load(string id)
    {
        if (string.IsNullOrEmpty(id) || id.Equals(CharacterIds.BuiltIn, StringComparison.OrdinalIgnoreCase)) return _builtIn;
        if (_loaded.TryGetValue(id, out var cached)) return cached;

        var info = _available.FirstOrDefault(c => c.Id.Equals(id, StringComparison.OrdinalIgnoreCase));
        if (info?.Folder == null)
        {
            _errors[id] = "Character folder not found.";
            Log.Error($"Character '{id}' was not found; using the built-in one");
            return _builtIn;
        }

        try
        {
            var character = SpritePackLoader.Load(info.Id, info.Folder);
            _loaded[id] = character;
            _errors.Remove(id);
            return character;
        }
        catch (Exception ex)
        {
            _errors[id] = ex.Message;
            Log.Error($"Could not load character '{id}' from {info.Folder}", ex);
            return _builtIn;
        }
        finally
        {
            // Decoding a pack goes through far more memory than the pack ends up holding.
            FreedMemory.Return();
        }
    }

    /// <summary>Creates the per-user characters folder with a short how-to in it, and returns its path.</summary>
    public static string EnsureUserFolder()
    {
        Directory.CreateDirectory(UserFolder);
        string readme = Path.Combine(UserFolder, "README.txt");
        if (!File.Exists(readme))
        {
            File.WriteAllText(readme, """
                DeskDancer characters
                =====================

                Each character is a folder in here. Put your own image files in it:

                    my-character/
                        idle.png              the only file you really need (transparent background)
                        walk.gif              optional animations: walk, sit, sleep, drag, fall
                        dance_spin.gif        anything else becomes an extra dance move

                Sprite sheets work too: name them with the grid size, e.g. walk_8x1.png.
                A folder of numbered frames works as well: walk/001.png, walk/002.png, ...

                Then right-click the mate and choose Character > Reload characters.

                An optional character.json lets you set the name, size, frame rate and more;
                see characters/README.md in the project for every option.

                """.Replace("\n", Environment.NewLine));
        }
        return UserFolder;
    }
}
