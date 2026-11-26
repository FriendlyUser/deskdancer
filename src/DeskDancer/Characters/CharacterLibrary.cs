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
    readonly Dictionary<string, SpriteCharacter> _loaded = new(StringComparer.OrdinalIgnoreCase);
    readonly Dictionary<string, Task<SpriteCharacter>> _opening = new(StringComparer.OrdinalIgnoreCase);
    readonly Dictionary<string, string> _errors = new(StringComparer.OrdinalIgnoreCase);
    readonly RemixCharacter _builtIn = new();
    List<CharacterInfo> _available = [];

    /// <summary>Extra folder to scan, from the command line.</summary>
    public string? ExtraFolder { get; set; }

    /// <summary>
    /// Where the packs that come with the program are, if not <see cref="AppFolder"/>: on
    /// Android, the copies unpacked from the APK. Like those, they give way to a pack of the
    /// same name in the user's own folder.
    /// </summary>
    public string? ShippedFolder { get; set; }

    /// <summary>
    /// True while mates are on screen. An image pack loaded from then on comes back with only
    /// its idle clip decoded: the others are read when a mate first needs them, and
    /// <see cref="ReleaseUnusedClips"/> lets them go again. The offline tools leave this off
    /// and get every frame of a pack up front.
    /// </summary>
    public bool ClipsOnDemand { get; set; }

    /// <summary>How long a clip stays in memory after it was last drawn.</summary>
    static readonly TimeSpan ClipLifetime = TimeSpan.FromSeconds(60);

    /// <summary>
    /// The packs that ship with the program: a "characters" folder next to it or, in a
    /// macOS app bundle, in the bundle's Resources folder beside the one the program is in.
    /// </summary>
    public static string AppFolder
    {
        get
        {
            string beside = Path.Combine(AppContext.BaseDirectory, "characters");
            if (Directory.Exists(beside)) return beside;
            string bundled = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "Resources", "characters"));
            return Directory.Exists(bundled) ? bundled : beside;
        }
    }

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
        // includes a pack that is still being opened, once that has finished.
        foreach (var character in _loaded.Values) character.ReleaseUnused(TimeSpan.Zero);
        foreach (var opening in _opening.Values)
        {
            opening.ContinueWith(static done =>
            {
                if (done.IsCompletedSuccessfully) done.Result.ReleaseUnused(TimeSpan.Zero);
                else _ = done.Exception;
            }, TaskScheduler.Default);
        }
        _loaded.Clear();
        _opening.Clear();
        _errors.Clear();
        var list = new List<CharacterInfo> { new(CharacterIds.BuiltIn, _builtIn.DisplayName, null) };
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { CharacterIds.BuiltIn };

        // Later folders win nothing: the first pack with a given folder name is the one used.
        foreach (var root in new[] { ExtraFolder, UserFolder, ShippedFolder ?? AppFolder })
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
    /// Starts opening a pack on the decoding thread, so that <see cref="Load"/> has less to
    /// wait for, or nothing, when it is asked for the same character a moment later.
    /// <paramref name="firstClip"/> is the clip the mate will be showing to begin with,
    /// if that is known: it is fetched as well, so the very first frame can have it.
    /// </summary>
    public void Preload(string id, string? firstClip = null)
    {
        if (string.IsNullOrEmpty(id) || _loaded.ContainsKey(id) || _opening.ContainsKey(id)) return;
        if (Find(id) is not { Folder: { } folder } info) return;
        _opening[id] = DecodeThread.Run(() =>
        {
            var character = SpritePackLoader.Load(info.Id, folder);
            if (firstClip != null) character.Prepare(firstClip);
            return character;
        });
    }

    /// <summary>
    /// Loads a character, falling back to the built-in one if the pack is missing or broken.
    /// A pack comes back ready to be shown, with its idle clip in memory. With
    /// <see cref="ClipsOnDemand"/> its other clips are decoded when a mate first needs
    /// them; without, they are all there when this returns.
    /// </summary>
    public ICharacter Load(string id)
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
                if (_opening.Remove(id, out var opening))
                {
                    character = opening.GetAwaiter().GetResult();
                }
                else
                {
                    character = SpritePackLoader.Load(info.Id, info.Folder);
                    // That was decoded on this thread, which leaves memory behind that the C
                    // library will hand back if asked.
                    FreedMemory.Return();
                }
                _loaded[id] = character;
                _errors.Remove(id);
                // Only the idle clip has been decoded. The rest are gone through behind the
                // scenes, so that a damaged one is still reported now, as the pack is loaded.
                if (ClipsOnDemand) character.CheckClips();
            }
            catch (Exception ex)
            {
                _errors[id] = ex.Message;
                Log.Error($"Could not load character '{id}' from {info.Folder}", ex);
                return _builtIn;
            }
        }

        // A character nobody has drawn for a while has let go of its frames, so this may be
        // where its idle clip is read again. And with every clip wanted up front, as the
        // offline tools want them, a pack that cannot supply one of them is no use at all.
        if (!character.LoadNow(everyClip: !ClipsOnDemand) || !ClipsOnDemand && character.Problem != null)
        {
            _loaded.Remove(id);
            _errors[id] = character.Problem ?? "The idle clip could not be read.";
            character.ReleaseUnused(TimeSpan.Zero);
            Log.Error($"Character '{id}' cannot be used ({_errors[id]}); using the built-in one");
            return _builtIn;
        }
        return character;
    }

    /// <summary>
    /// Lets go of the frames of clips that nothing has drawn for a while, and returns how
    /// many bytes that gave up. They come back by themselves the next time they are drawn.
    /// A character on screen keeps its idle clip and whatever it has been doing lately; one
    /// that no mate is using any more ends up holding nothing.
    /// </summary>
    public long ReleaseUnusedClips(TimeSpan? unusedFor = null)
    {
        long bytes = 0;
        foreach (var character in _loaded.Values) bytes += character.ReleaseUnused(unusedFor ?? ClipLifetime);
        // The frames were bitmaps the C library allocated, so it is asked to hand them back.
        if (bytes > 0) FreedMemory.Return();
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
