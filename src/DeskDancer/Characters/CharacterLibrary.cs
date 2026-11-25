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
    readonly Dictionary<string, Task<SpriteCharacter>> _opening = new(StringComparer.OrdinalIgnoreCase);
    readonly Dictionary<string, string> _errors = new(StringComparer.OrdinalIgnoreCase);
    readonly RemixCharacter _builtIn = new();
    List<CharacterInfo> _available = [];

    /// <summary>Extra folder to scan, from the command line.</summary>
    public string? ExtraFolder { get; set; }

    public static string AppFolder => Path.Combine(AppContext.BaseDirectory, "characters");
    public static string UserFolder => Path.Combine(Settings.ConfigDir, "characters");

    public IReadOnlyList<CharacterInfo> Available => _available;
    public ICharacter BuiltIn => _builtIn;

    /// <summary>
    /// Why a pack failed to load, if it did. A pack is refused as a whole when it is opened;
    /// one whose clip turns out to be unreadable later, when that clip is first wanted, keeps
    /// going without it and reports the clip here.
    /// </summary>
    public string? ErrorFor(string id) =>
        _errors.GetValueOrDefault(id) ?? (_loaded.GetValueOrDefault(id) as SpriteCharacter)?.Error;

    public void Scan()
    {
        // The packs are about to be read afresh, so what was loaded from them is let go of
        // now, not left for the garbage collector to find. The caller gives every mate its
        // new character straight afterwards.
        foreach (var character in _loaded.Values) (character as IDisposable)?.Dispose();
        foreach (var opening in _opening.Values) DisposeWhenOpened(opening);
        _loaded.Clear();
        _opening.Clear();
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

    /// <summary>
    /// Starts opening a pack on another thread, for a caller that is about to <see cref="Load"/>
    /// it and has other work to do first. For a new mate that work is building its window,
    /// which takes longer than the pack does, so the pack ends up costing no time at all.
    /// </summary>
    public void Preload(string id)
    {
        if (string.IsNullOrEmpty(id) || id.Equals(CharacterIds.BuiltIn, StringComparison.OrdinalIgnoreCase)) return;
        if (_loaded.ContainsKey(id) || _opening.ContainsKey(id)) return;
        var info = _available.FirstOrDefault(c => c.Id.Equals(id, StringComparison.OrdinalIgnoreCase));
        if (info?.Folder is not { } folder) return;
        _opening[id] = Task.Run(() => SpritePackLoader.Load(info.Id, folder));
    }

    static void DisposeWhenOpened(Task<SpriteCharacter> opening) =>
        opening.ContinueWith(done => done.Result.Dispose(), TaskContinuationOptions.OnlyOnRanToCompletion);

    /// <summary>
    /// Lets go of every loaded pack that is not among <paramref name="inUse"/>: the ones no
    /// mate is showing any more. Such a pack is opened again, which is quick, if it is asked
    /// for later.
    /// </summary>
    public void KeepOnly(IEnumerable<ICharacter> inUse)
    {
        var keep = new HashSet<ICharacter>(inUse, ReferenceEqualityComparer.Instance);
        foreach (var (id, character) in _loaded.ToList())
        {
            if (keep.Contains(character)) continue;
            _loaded.Remove(id);
            (character as IDisposable)?.Dispose();
        }
    }

    /// <summary>Loads a character, falling back to the built-in one if the pack is missing or broken.</summary>
    public ICharacter Load(string id)
    {
        if (string.IsNullOrEmpty(id) || id.Equals(CharacterIds.BuiltIn, StringComparison.OrdinalIgnoreCase)) return _builtIn;
        if (_loaded.TryGetValue(id, out var cached)) return cached;

        var info = _available.FirstOrDefault(c => c.Id.Equals(id, StringComparison.OrdinalIgnoreCase));
        if (info?.Folder == null)
        {
            // The default character is a pack on disk. A copy of the program without its
            // characters folder has nothing wrong with it; the built-in one just stands in.
            if (id.Equals(CharacterIds.Default, StringComparison.OrdinalIgnoreCase))
            {
                Log.Info($"The default character '{id}' is not installed; using the built-in one");
                return _builtIn;
            }
            _errors[id] = "Character folder not found.";
            Log.Error($"Character '{id}' was not found; using the built-in one");
            return _builtIn;
        }

        try
        {
            // Waiting for a pack that Preload started gives the same result, and the same
            // error, as opening it here would.
            var character = _opening.Remove(id, out var opening)
                ? opening.GetAwaiter().GetResult()
                : SpritePackLoader.Load(info.Id, info.Folder);
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
