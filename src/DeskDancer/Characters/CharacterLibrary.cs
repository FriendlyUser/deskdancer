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
    /// <summary>How long a clip's frames stay in memory after the last time they were shown.</summary>
    public static readonly TimeSpan KeepUnused = TimeSpan.FromSeconds(60);

    readonly Dictionary<string, SpriteCharacter> _loaded = new(StringComparer.OrdinalIgnoreCase);
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
    /// <summary>The image packs that have been loaded since the last scan.</summary>
    public IReadOnlyCollection<SpriteCharacter> LoadedPacks => _loaded.Values;

    /// <summary>Why a pack failed to load, or what is wrong with one of its clips, if anything is.</summary>
    public string? ErrorFor(string id) => _errors.GetValueOrDefault(id) ?? _loaded.GetValueOrDefault(id)?.Problem;

    public void Scan()
    {
        // Whatever was loaded is read afresh after this, so its pictures can go now. That
        // includes a pack another thread is still opening, once it has finished.
        foreach (var character in _loaded.Values) character.ReleaseUnused(long.MaxValue);
        foreach (var opening in _opening.Values)
        {
            opening.ContinueWith(static done =>
            {
                if (done.IsCompletedSuccessfully) done.Result.ReleaseUnused(long.MaxValue);
                else _ = done.Exception;
            }, TaskScheduler.Default);
        }
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

    CharacterInfo? Find(string id) => _available.FirstOrDefault(c => c.Id.Equals(id, StringComparison.OrdinalIgnoreCase));

    /// <summary>
    /// Starts opening a pack on another thread, so that <see cref="Load"/> has less to
    /// wait for, or nothing, when it is asked for the same character a moment later.
    /// <paramref name="firstClip"/> is the clip the mate will be showing to begin with,
    /// if that is known: it is fetched as well, so the very first frame can have it.
    /// </summary>
    public void Preload(string id, string? firstClip = null)
    {
        if (string.IsNullOrEmpty(id) || _loaded.ContainsKey(id) || _opening.ContainsKey(id)) return;
        if (Find(id) is not { Folder: { } folder } info) return;
        _opening[id] = Task.Run(() =>
        {
            var character = SpritePackLoader.Load(info.Id, folder);
            if (firstClip != null) character.Prepare(firstClip);
            return character;
        });
    }

    /// <summary>
    /// Loads a character, falling back to the built-in one if the pack is missing or broken.
    /// A pack comes back ready to be shown, with its idle clip in memory. Its other clips
    /// are decoded when a mate first needs them, unless <paramref name="everyClip"/> asks
    /// for them all to be there before this returns.
    /// </summary>
    public ICharacter Load(string id, bool everyClip = false)
    {
        if (string.IsNullOrEmpty(id) || id.Equals(CharacterIds.BuiltIn, StringComparison.OrdinalIgnoreCase)) return _builtIn;

        if (!_loaded.TryGetValue(id, out var character))
        {
            var info = Find(id);
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
                // Waiting for another thread here is safe: opening a pack never needs this one.
                character = _opening.Remove(id, out var opening)
                    ? opening.GetAwaiter().GetResult()
                    : SpritePackLoader.Load(info.Id, info.Folder);
                _loaded[id] = character;
                _errors.Remove(id);
            }
            catch (Exception ex)
            {
                _errors[id] = ex.Message;
                Log.Error($"Could not load character '{id}' from {info.Folder}", ex);
                return _builtIn;
            }
        }

        // A character nobody has drawn for a while has let go of its frames, so this may
        // be where its idle clip is read again.
        if (!character.LoadNow(everyClip))
        {
            _loaded.Remove(id);
            _errors[id] = character.Problem ?? "The idle clip could not be read.";
            return _builtIn;
        }
        return character;
    }

    /// <summary>
    /// Lets go of the frames of every clip that nothing has shown for
    /// <paramref name="unusedFor"/>, <see cref="KeepUnused"/> if not given, and returns how
    /// many bytes that gave up. A character on screen keeps its idle clip and whatever it
    /// has been doing lately; one that no mate is using any more ends up holding nothing.
    /// </summary>
    public long ReleaseUnused(TimeSpan? unusedFor = null)
    {
        long since = Environment.TickCount64 - (long)(unusedFor ?? KeepUnused).TotalMilliseconds;
        long bytes = 0;
        foreach (var character in _loaded.Values) bytes += character.ReleaseUnused(since);
        PictureMemory.Return();
        return bytes;
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
