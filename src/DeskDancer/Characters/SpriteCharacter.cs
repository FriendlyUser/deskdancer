using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Text.RegularExpressions;
using Avalonia;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform;
using DeskDancer.Platform;
using SkiaSharp;

namespace DeskDancer.Characters;

/// <summary>One animation: a run of frames with their timings and where the feet are.</summary>
public sealed class SpriteClip
{
    public required Bitmap[] Frames { get; init; }
    /// <summary>Time in seconds at which each frame ends.</summary>
    public required double[] Ends { get; init; }
    public required string Name { get; init; }
    public bool Loop { get; init; } = true;
    /// <summary>Point between the feet, in frame pixels.</summary>
    public double AnchorX { get; init; }
    public double AnchorY { get; init; }
    /// <summary>Height of the drawn character in frame pixels.</summary>
    public double ContentHeight { get; init; }
    public double ContentWidth { get; init; }
    /// <summary>Extra scale so this clip matches the idle clip's size on screen.</summary>
    public double Scale { get; init; } = 1;

    public double Duration => Ends[^1];

    public Bitmap FrameAt(double time)
    {
        if (Frames.Length == 1) return Frames[0];
        double t = Loop ? time % Duration : Math.Min(time, Duration - 1e-6);
        if (t < 0) t = 0;
        int i = Array.BinarySearch(Ends, t);
        i = i < 0 ? ~i : i + 1;
        return Frames[Math.Min(i, Frames.Length - 1)];
    }

    /// <summary>
    /// Frees the frames; the clip cannot be drawn afterwards. Safe from any thread, and safe
    /// while a frame is still on screen: whatever is drawing a bitmap keeps its own hold on it.
    /// </summary>
    internal void Free()
    {
        foreach (var frame in Frames) frame.Dispose();
    }
}

/// <summary>
/// One of a pack's animations, and its frames while they are in memory. Opening a pack
/// reads only what each clip is called and how long it runs. The frames of everything but
/// the idle clip are decoded on a background thread the first time the clip is wanted, so
/// a clip that is never shown is never loaded, and they are let go of again once the clip
/// has gone unused for a while.
/// </summary>
sealed class ClipSlot
{
    // Background decoding leaves a core for the window, which is drawing all the while.
    static readonly int BackgroundThreads = Math.Max(1, Environment.ProcessorCount - 1);

    readonly Func<int, SpriteClip>? _decode;
    readonly string _pack;
    readonly object _gate = new();
    volatile SpriteClip? _clip;
    volatile string? _error;
    Task? _loading;
    bool _closed;
    long _used = Environment.TickCount64;

    /// <summary>A clip whose frames are decoded when it is first wanted.</summary>
    public ClipSlot(string pack, string key, string name, double seconds, Func<int, SpriteClip> decode)
    {
        _pack = pack;
        _decode = decode;
        Key = key;
        Name = name;
        Seconds = seconds;
    }

    /// <summary>A clip that is already decoded.</summary>
    public ClipSlot(string pack, string key, SpriteClip clip)
    {
        _pack = pack;
        _clip = clip;
        Key = key;
        Name = clip.Name;
        Seconds = clip.Duration;
    }

    public string Key { get; }
    public string Name { get; }
    /// <summary>How long the clip runs, from the headers of its files.</summary>
    public double Seconds { get; }
    /// <summary>The decoded clip, or null while its frames are not in memory.</summary>
    public SpriteClip? Clip => _clip;
    /// <summary>Why the frames could not be decoded, if that was tried and failed.</summary>
    public string? Error => _error;

    /// <summary>Notes that the clip is in use, which keeps its frames in memory for now.</summary>
    public void Touch() => Volatile.Write(ref _used, Environment.TickCount64);

    /// <summary>
    /// Starts decoding the frames in the background, unless they are here, on their way, or
    /// already known to be unreadable. Returns at once.
    /// </summary>
    public void Request()
    {
        Touch();
        if (_clip != null) return;
        lock (_gate)
        {
            if (_clip == null && _loading == null && _error == null && !_closed && _decode != null)
                _loading = Task.Run(Decode);
        }
    }

    /// <summary>Returns once the frames are in memory, or have failed to load.</summary>
    public void Load()
    {
        Request();
        Task? loading;
        lock (_gate) loading = _loading;
        loading?.Wait();
    }

    void Decode()
    {
        SpriteClip? clip = null;
        string? error = null;
        try
        {
            clip = _decode!(BackgroundThreads);
        }
        catch (Exception ex)
        {
            // Not tried again: the file will not have changed, and the idle clip stands in.
            error = $"{Key}: {ex.Message}";
            Log.Error($"Could not load the '{Key}' animation of character '{_pack}'", ex);
        }

        lock (_gate)
        {
            _loading = null;
            _error = error;
            if (!_closed)
            {
                _clip = clip;
                clip = null;
            }
        }
        clip?.Free();       // the character was let go of while this was being decoded
        NativeHeap.Trim();
    }

    /// <summary>
    /// Takes the frames away if the clip has not been used since <paramref name="tick"/>, and
    /// hands them to the caller to free. They are decoded again when the clip is next wanted.
    /// The idle clip, which everything else falls back on, is never given up this way.
    /// </summary>
    public SpriteClip? TakeIfUnusedSince(long tick)
    {
        if (_decode == null) return null;
        lock (_gate)
        {
            if (_clip == null || Volatile.Read(ref _used) > tick) return null;
            var clip = _clip;
            _clip = null;
            return clip;
        }
    }

    /// <summary>Takes the frames away for good and hands them to the caller to free.</summary>
    public SpriteClip? Close()
    {
        lock (_gate)
        {
            _closed = true;
            var clip = _clip;
            _clip = null;
            return clip;
        }
    }
}

/// <summary>A character made from the user's own image files.</summary>
public sealed class SpriteCharacter : ICharacter, IDisposable
{
    // Which clip stands in when the requested one was not supplied.
    static readonly Dictionary<string, string[]> Fallbacks = new()
    {
        ["fall"] = ["drag"],
        ["drag"] = ["fall"],
        ["sleep"] = ["sit"],
    };

    // A clip that has not been shown for this long gives its frames up, and they are decoded
    // again when it is next wanted. Long enough that a mate going about its day keeps the
    // clips it keeps coming back to (walking, the dance most moves share); short enough that
    // a dance it does a few times an hour is not held in memory in between.
    static readonly TimeSpan UnusedAfter = TimeSpan.FromMinutes(2);
    static readonly TimeSpan TidyEvery = TimeSpan.FromSeconds(10);

    readonly Dictionary<string, ClipSlot> _clips;
    readonly ClipSlot _idle;
    long _tidied = Environment.TickCount64;
    bool _keepEverything;

    internal SpriteCharacter(string id, string name, Dictionary<string, ClipSlot> clips, double height, int facing, bool pixelArt)
    {
        Id = id;
        DisplayName = name;
        _clips = clips;
        _idle = clips["idle"];
        // Everything is drawn relative to the idle clip, so the loader decodes that one itself.
        var idle = _idle.Clip ?? throw new ArgumentException("The idle clip has to be decoded before the character is made.", nameof(clips));
        PreferredHeight = height;
        NaturalFacing = facing;
        PixelArt = pixelArt;
        AspectRatio = Math.Clamp(idle.ContentWidth / Math.Max(1, idle.ContentHeight), 0.3, 2.5);
        DanceClips = clips
            .Where(c => c.Key.StartsWith("dance", StringComparison.Ordinal))
            .OrderBy(c => c.Key, StringComparer.Ordinal)
            .Select(c => new DanceClip(c.Key, c.Value.Name, c.Value.Seconds))
            .ToList();
    }

    public string Id { get; }
    public string DisplayName { get; }
    public double AspectRatio { get; }
    public double PreferredHeight { get; }
    public bool IsRigged => false;
    public bool PixelArt { get; }
    public int NaturalFacing { get; }
    public IReadOnlyList<DanceClip> DanceClips { get; }
    public IReadOnlyCollection<string> ClipNames => _clips.Keys;

    /// <summary>What went wrong with a clip that could not be decoded when it was wanted, if any could not.</summary>
    public string? Error => _clips.Values.Select(c => c.Error).FirstOrDefault(e => e != null);

    public bool HasClip(string clip) => _clips.ContainsKey(clip);

    /// <summary>True when the clip, or whatever stands in for one the pack lacks, can be drawn this instant.</summary>
    public bool IsReady(string clip) => Resolve(clip).Clip != null;

    /// <summary>Starts decoding a clip that is about to be shown, so it is ready by the time it is.</summary>
    public void Prepare(string clip) => Resolve(clip).Request();

    /// <summary>
    /// Decodes every clip, waits for them all and keeps them from then on. For the tools
    /// that draw each clip once and need the real frames on the first try.
    /// </summary>
    public void LoadAll()
    {
        _keepEverything = true;
        foreach (var slot in _clips.Values) slot.Request();
        foreach (var slot in _clips.Values) slot.Load();
    }

    /// <summary>
    /// Lets go of the frames of every clip that has not been shown or asked for in the last
    /// <paramref name="unusedFor"/>. The idle clip is always kept. This happens by itself
    /// as the character is drawn; calling it is for tests that cannot wait that long.
    /// </summary>
    public void ReleaseUnused(TimeSpan unusedFor)
    {
        if (_keepEverything) return;
        long since = Environment.TickCount64 - (long)unusedFor.TotalMilliseconds;
        List<SpriteClip>? unused = null;
        foreach (var slot in _clips.Values)
            if (slot.TakeIfUnusedSince(since) is { } clip) (unused ??= []).Add(clip);
        if (unused != null) Free(unused);
    }

    /// <summary>
    /// Lets go of every frame, for a character that no mate is showing any more. Drawing it
    /// afterwards draws nothing.
    /// </summary>
    public void Dispose() => Free(_clips.Values.Select(slot => slot.Close()).OfType<SpriteClip>().ToList());

    // Freeing a clip's worth of bitmaps and handing the memory back takes a millisecond or
    // two, which the thread that draws should not spend.
    static void Free(List<SpriteClip> clips)
    {
        if (clips.Count == 0) return;
        Task.Run(() =>
        {
            foreach (var clip in clips) clip.Free();
            NativeHeap.Trim();
        });
    }

    ClipSlot Resolve(string clip)
    {
        if (_clips.TryGetValue(clip, out var found)) return found;
        if (Fallbacks.TryGetValue(clip, out var alternatives))
            foreach (var alt in alternatives)
                if (_clips.TryGetValue(alt, out found)) return found;
        return _idle;
    }

    public void Draw(DrawingContext ctx, double height, in CharacterFrame frame)
    {
        var idle = _idle.Clip;
        if (idle == null) return;       // disposed

        var slot = Resolve(frame.Clip);
        var clip = slot.Clip;
        if (clip == null)
        {
            // Its frames are not in memory. Drawing must not wait for them, so ask for them
            // and stand still for the few frames it takes.
            slot.Request();
            clip = idle;
        }
        else
        {
            slot.Touch();
        }
        var bitmap = clip.FrameAt(frame.ClipTime);
        double s = height / idle.ContentHeight * clip.Scale;
        var size = bitmap.Size;
        var dest = new Rect(-clip.AnchorX * s, -clip.AnchorY * s, size.Width * s, size.Height * s);
        ctx.DrawImage(bitmap, new Rect(size), dest);

        long now = Environment.TickCount64;
        if (now - _tidied >= (long)TidyEvery.TotalMilliseconds)
        {
            _tidied = now;
            ReleaseUnused(UnusedAfter);
        }
    }
}

/// <summary>
/// Turns a folder of images into a <see cref="SpriteCharacter"/>. Works from file names
/// alone; an optional character.json fine-tunes it. See characters/README.md for the format.
/// </summary>
public static partial class SpritePackLoader
{
    public const string ManifestName = "character.json";

    static readonly string[] ImageExtensions = [".png", ".gif", ".webp", ".jpg", ".jpeg", ".bmp"];
    const int MaxFramesPerClip = 400;
    const int MaxFrameSide = 640;

    static readonly Dictionary<string, string> Aliases = new()
    {
        ["stand"] = "idle", ["standing"] = "idle", ["default"] = "idle", ["rest"] = "idle",
        ["walking"] = "walk", ["run"] = "walk", ["running"] = "walk",
        ["sitting"] = "sit",
        ["sleeping"] = "sleep", ["nap"] = "sleep",
        ["dragging"] = "drag", ["held"] = "drag", ["hold"] = "drag", ["grab"] = "drag", ["pickup"] = "drag",
        ["falling"] = "fall",
        ["dancing"] = "dance",
    };

    static readonly HashSet<string> KnownClips = ["idle", "walk", "sit", "sleep", "drag", "fall"];

    [GeneratedRegex(@"_(\d+)x(\d+)$")]
    private static partial Regex SheetSuffix();

    public static bool IsImage(string path) =>
        ImageExtensions.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase);

    /// <summary>True when the folder holds at least one image, directly or one level down.</summary>
    public static bool LooksLikePack(string dir)
    {
        try
        {
            return Directory.EnumerateFiles(dir).Any(IsImage)
                   || Directory.EnumerateDirectories(dir).Any(d =>
                       !Path.GetFileName(d).StartsWith('.') && !Path.GetFileName(d).StartsWith('_')
                       && Directory.EnumerateFiles(d).Any(IsImage));
        }
        catch (IOException) { return false; }
        catch (UnauthorizedAccessException) { return false; }
    }

    sealed class ClipSource
    {
        public required string Key;
        public string? File;
        public string? Folder;
        public int Columns = 1, Rows = 1, Count;
        public double? Fps;
        public bool Loop = true;
        public string? Name;
        public double Scale = 1;
        public double? AnchorX, AnchorY;
    }

    sealed class PackOptions
    {
        public string? Name;
        public double Height = 150;
        public int Facing = 1;
        public bool PixelArt;
        public double Fps = 10;
        /// <summary>null = decide automatically, otherwise forced on or off.</summary>
        public bool? RemoveBackground;
        public SKColor? KeyColor;
        public int Tolerance = 28;
        public bool Normalize;
    }

    /// <summary>Reads the display name without decoding any images.</summary>
    public static string ReadDisplayName(string dir)
    {
        try
        {
            string manifest = Path.Combine(dir, ManifestName);
            if (File.Exists(manifest))
            {
                using var doc = Parse(manifest);
                if (doc.RootElement.TryGetProperty("name", out var n) && n.ValueKind == JsonValueKind.String
                    && !string.IsNullOrWhiteSpace(n.GetString()))
                    return n.GetString()!;
            }
        }
        catch (Exception)
        {
            // A broken manifest is reported properly when the pack is actually loaded.
        }
        return Path.GetFileName(dir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
    }

    static JsonDocument Parse(string path) => JsonDocument.Parse(File.ReadAllText(path), new JsonDocumentOptions
    {
        CommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
    });

    public static SpriteCharacter Load(string id, string dir)
    {
        var options = new PackOptions();
        var sources = new Dictionary<string, ClipSource>();
        var claimed = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        string manifestPath = Path.Combine(dir, ManifestName);
        if (File.Exists(manifestPath))
        {
            try
            {
                ReadManifest(manifestPath, options, sources, claimed);
            }
            catch (JsonException ex)
            {
                throw new InvalidDataException($"{ManifestName} is not valid JSON: {ex.Message}", ex);
            }
        }

        Discover(dir, sources, claimed);
        if (sources.Count == 0) throw new InvalidDataException("No image files found in this folder.");

        // Opening the pack decodes the idle clip and nothing else. For every other clip only
        // the file headers are read: they give its length, which the dance menu needs, and
        // catch the usual mistakes (a missing file, a grid that does not fit) while the pack
        // can still be refused as a whole. Problems are reported in the order the clips were
        // found, so a pack reports the same one every time.
        int threads = Environment.ProcessorCount;
        var order = sources.Values.ToArray();
        var seconds = new double[order.Length];
        Each(order.Length, threads, i => seconds[i] = ReadLength(dir, order[i], options));

        SpriteClip idle;
        double idleShrink;
        if (sources.TryGetValue("idle", out var idleSource))
        {
            idle = LoadClip(dir, idleSource, options, 0, 1, threads, out idleShrink);
        }
        else
        {
            // No idle supplied: stand still on the first frame of whatever there is.
            var donor = order.FirstOrDefault(s => KnownClips.Contains(s.Key)) ?? order[0];
            var first = new List<SKBitmap>();
            try
            {
                DecodeClip(dir, donor, options, threads, 1, first, []);
                idle = BuildClip(new ClipSource { Key = "idle" }, first, [1.0], options, 0, 1, threads, out idleShrink);
            }
            finally
            {
                foreach (var bmp in first) bmp.Dispose();
            }
        }

        // Every other clip is drawn relative to the idle one, which is why that had to come first.
        double idleHeight = idle.ContentHeight;
        var clips = new Dictionary<string, ClipSlot> { ["idle"] = new ClipSlot(id, "idle", idle) };
        for (int i = 0; i < order.Length; i++)
        {
            var src = order[i];
            if (src.Key == "idle") continue;
            clips[src.Key] = new ClipSlot(id, src.Key, src.Name ?? PrettyName(src.Key), seconds[i],
                decodeThreads => LoadClip(dir, src, options, idleHeight, idleShrink, decodeThreads, out _));
        }

        // The decoded frames of the idle clip have been freed; give that memory back.
        Task.Run(NativeHeap.Trim);

        string name = options.Name ?? Path.GetFileName(dir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
        return new SpriteCharacter(id, name, clips, options.Height, options.Facing, options.PixelArt);
    }

    /// <summary>
    /// Runs <paramref name="body"/> for 0 to count-1 on up to <paramref name="threads"/> threads.
    /// If any of them fail, the failure with the lowest number is the one thrown, which is the
    /// one that would have been met first had they run in order.
    /// </summary>
    static void Each(int count, int threads, Action<int> body)
    {
        if (threads <= 1 || count <= 1)
        {
            for (int i = 0; i < count; i++) body(i);
            return;
        }
        var errors = new Exception?[count];
        Parallel.For(0, count, new ParallelOptions { MaxDegreeOfParallelism = threads }, i =>
        {
            try
            {
                body(i);
            }
            catch (Exception ex)
            {
                errors[i] = ex;
            }
        });
        if (errors.FirstOrDefault(e => e != null) is { } first)
            ExceptionDispatchInfo.Capture(first).Throw();
    }

    /// <summary>Decodes one clip and turns it into bitmaps, letting go of the decoded frames as it goes.</summary>
    static SpriteClip LoadClip(string dir, ClipSource src, PackOptions options, double idleHeight, double idleShrink,
        int threads, out double shrink)
    {
        var frames = new List<SKBitmap>();
        var durations = new List<double>();
        try
        {
            DecodeClip(dir, src, options, threads, int.MaxValue, frames, durations);
            return BuildClip(src, frames, durations, options, idleHeight, idleShrink, threads, out shrink);
        }
        finally
        {
            // BuildClip disposes each frame as soon as it has been copied; this is for a
            // load that failed part way.
            foreach (var bmp in frames) bmp.Dispose();
        }
    }

    // ---- Manifest and file discovery ----

    static void ReadManifest(string path, PackOptions options, Dictionary<string, ClipSource> sources, HashSet<string> claimed)
    {
        using var doc = Parse(path);
        var root = doc.RootElement;
        if (root.ValueKind != JsonValueKind.Object) throw new InvalidDataException($"{ManifestName} must contain a JSON object.");

        if (Str(root, "name") is { Length: > 0 } name) options.Name = name;
        if (Num(root, "height") is { } height) options.Height = Math.Clamp(height, 24, 1000);
        if (Str(root, "facing") is { } facing) options.Facing = facing.Equals("left", StringComparison.OrdinalIgnoreCase) ? -1 : 1;
        if (Bool(root, "pixelArt") is { } pixel) options.PixelArt = pixel;
        if (Num(root, "fps") is { } fps) options.Fps = fps;
        if (Num(root, "tolerance") is { } tol) options.Tolerance = (int)Math.Clamp(tol, 0, 200);
        if (Bool(root, "normalize") is { } norm) options.Normalize = norm;

        if (root.TryGetProperty("removeBackground", out var rb))
        {
            switch (rb.ValueKind)
            {
                case JsonValueKind.True: options.RemoveBackground = true; break;
                case JsonValueKind.False: options.RemoveBackground = false; break;
                case JsonValueKind.String:
                    string text = rb.GetString() ?? "";
                    if (text.Equals("auto", StringComparison.OrdinalIgnoreCase)) break;
                    if (!SKColor.TryParse(text, out var color))
                        throw new InvalidDataException($"removeBackground: '{text}' is not a colour like #00ff00.");
                    options.KeyColor = color;
                    options.RemoveBackground = true;
                    break;
            }
        }

        if (!root.TryGetProperty("clips", out var clips) || clips.ValueKind != JsonValueKind.Object) return;
        foreach (var prop in clips.EnumerateObject())
        {
            string key = NormaliseKey(prop.Name, out _, out _);
            var src = new ClipSource { Key = key };
            if (prop.Value.ValueKind == JsonValueKind.String)
            {
                src.File = prop.Value.GetString();
            }
            else if (prop.Value.ValueKind == JsonValueKind.Object)
            {
                var c = prop.Value;
                src.File = Str(c, "file");
                src.Folder = Str(c, "folder");
                src.Columns = (int)Math.Clamp(Num(c, "columns") ?? 1, 1, 256);
                src.Rows = (int)Math.Clamp(Num(c, "rows") ?? 1, 1, 256);
                src.Count = (int)Math.Clamp(Num(c, "count") ?? 0, 0, 65536);
                src.Fps = Num(c, "fps");
                src.Loop = Bool(c, "loop") ?? true;
                src.Name = Str(c, "name");
                src.Scale = Math.Clamp(Num(c, "scale") ?? 1, 0.05, 20);
                if (c.TryGetProperty("anchor", out var anchor) && anchor.ValueKind == JsonValueKind.Array && anchor.GetArrayLength() == 2)
                {
                    src.AnchorX = anchor[0].GetDouble();
                    src.AnchorY = anchor[1].GetDouble();
                }
            }
            if (src.File == null && src.Folder == null)
                throw new InvalidDataException($"Clip '{prop.Name}' needs a \"file\" or a \"folder\".");

            // The sheet layout can also come from the file name (walk_8x1.png).
            if (src.File != null && src.Columns == 1 && src.Rows == 1)
                NormaliseKey(Path.GetFileNameWithoutExtension(src.File), out src.Columns, out src.Rows);

            claimed.Add((src.File ?? src.Folder)!.Replace('\\', '/'));
            sources[key] = src;
        }
    }

    static string? Str(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

    static double? Num(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : null;

    static bool? Bool(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && v.ValueKind is JsonValueKind.True or JsonValueKind.False ? v.GetBoolean() : null;

    /// <summary>
    /// "Walk Cycle_8x1" → "walk_cycle" with an 8×1 sheet. Names the app does not know
    /// become extra dances, so any spare animation is still usable.
    /// </summary>
    static string NormaliseKey(string raw, out int columns, out int rows)
    {
        columns = rows = 1;
        string key = raw.Trim().ToLowerInvariant().Replace(' ', '_').Replace('-', '_');
        var m = SheetSuffix().Match(key);
        if (m.Success)
        {
            columns = Math.Clamp(int.Parse(m.Groups[1].Value), 1, 256);
            rows = Math.Clamp(int.Parse(m.Groups[2].Value), 1, 256);
            key = key[..m.Index];
        }
        key = key.Trim('_');
        if (key.Length == 0) key = "idle";
        if (Aliases.TryGetValue(key, out var alias)) key = alias;
        if (!KnownClips.Contains(key) && !key.StartsWith("dance", StringComparison.Ordinal)) key = "dance_" + key;
        return key;
    }

    static void Discover(string dir, Dictionary<string, ClipSource> sources, HashSet<string> claimed)
    {
        foreach (var file in Directory.EnumerateFiles(dir).Where(IsImage).OrderBy(f => f, NaturalOrder.Instance))
        {
            string rel = Path.GetFileName(file);
            if (claimed.Contains(rel)) continue;
            string key = NormaliseKey(Path.GetFileNameWithoutExtension(file), out int cols, out int rows);
            sources.TryAdd(key, new ClipSource { Key = key, File = rel, Columns = cols, Rows = rows });
        }
        foreach (var folder in Directory.EnumerateDirectories(dir).OrderBy(f => f, NaturalOrder.Instance))
        {
            // A folder of frames is a clip, unless its name starts with "." or "_": those are
            // the pack author's own working files (a "_source" folder, say) and stay out of it.
            string rel = Path.GetFileName(folder);
            if (claimed.Contains(rel) || rel.StartsWith('.') || rel.StartsWith('_')) continue;
            if (!Directory.EnumerateFiles(folder).Any(IsImage)) continue;
            string key = NormaliseKey(rel, out _, out _);
            sources.TryAdd(key, new ClipSource { Key = key, Folder = rel });
        }
    }

    static string PrettyName(string key)
    {
        string rest = key.StartsWith("dance_", StringComparison.Ordinal) ? key["dance_".Length..] : key;
        var words = rest.Split('_', StringSplitOptions.RemoveEmptyEntries)
            .Select(w => char.ToUpperInvariant(w[0]) + w[1..]);
        string name = string.Join(' ', words);
        return name.Length == 0 ? "Dance" : name;
    }

    // ---- Decoding ----

    static SKImageInfo InfoFor(int w, int h) => new(w, h, SKColorType.Bgra8888, SKAlphaType.Premul);

    static double FrameRate(ClipSource src, PackOptions options) => Math.Clamp(src.Fps ?? options.Fps, 0.5, 120);

    /// <summary>How long a frame of an animated file is shown, from the time stored with it.</summary>
    static double FrameSeconds(int milliseconds) => milliseconds <= 10 ? 0.1 : milliseconds / 1000.0;

    /// <summary>How many cells of a sprite sheet are used.</summary>
    static int CellCount(int columns, int rows, int count) =>
        Math.Min(count > 0 ? Math.Min(count, columns * rows) : columns * rows, MaxFramesPerClip);

    /// <summary>The time in seconds at which each frame ends.</summary>
    static double[] FrameEnds(List<double> durations)
    {
        var ends = new double[durations.Count];
        double t = 0;
        for (int i = 0; i < ends.Length; i++)
        {
            t += Math.Max(durations[i], 1.0 / 240);
            ends[i] = t;
        }
        return ends;
    }

    static string ClipFile(string dir, ClipSource src)
    {
        string file = Path.Combine(dir, src.File!);
        if (!File.Exists(file)) throw new InvalidDataException($"File not found: {src.File}");
        return file;
    }

    static string[] FolderFiles(string dir, ClipSource src)
    {
        string folder = Path.Combine(dir, src.Folder!);
        if (!Directory.Exists(folder)) throw new InvalidDataException($"Folder not found: {src.Folder}");
        return Directory.EnumerateFiles(folder).Where(IsImage).OrderBy(f => f, NaturalOrder.Instance).ToArray();
    }

    static SKCodec OpenCodec(string path, out SKImageInfo info)
    {
        var codec = SKCodec.Create(path, out var status)
                    ?? throw new InvalidDataException($"Could not read {Path.GetFileName(path)} ({status}).");
        info = InfoFor(codec.Info.Width, codec.Info.Height);
        if (info.Width <= 0 || info.Height <= 0 || (long)info.Width * info.Height > 64_000_000)
        {
            codec.Dispose();
            throw new InvalidDataException($"{Path.GetFileName(path)} is too large.");
        }
        return codec;
    }

    /// <summary>
    /// How long a clip runs, from the headers of its files alone: no frame is decoded. This
    /// counts frames exactly as <see cref="DecodeFile"/> goes on to produce them.
    /// </summary>
    static double ReadLength(string dir, ClipSource src, PackOptions options)
    {
        double fps = FrameRate(src, options);
        var durations = new List<double>();
        if (src.Folder != null)
        {
            foreach (var file in FolderFiles(dir, src)) ReadTimings(file, 1, 1, 0, fps, durations);
        }
        else
        {
            ReadTimings(ClipFile(dir, src), src.Columns, src.Rows, src.Count, fps, durations);
        }
        if (durations.Count == 0) throw new InvalidDataException($"Clip '{src.Key}' has no frames.");
        return FrameEnds(durations)[^1];
    }

    static void ReadTimings(string path, int columns, int rows, int count, double fps, List<double> durations)
    {
        using var codec = OpenCodec(path, out var info);
        int animated = codec.FrameCount;
        if (animated > 1)
        {
            var frameInfo = codec.FrameInfo;
            int n = Math.Min(animated, MaxFramesPerClip);
            for (int i = 0; i < n; i++) durations.Add(FrameSeconds(frameInfo[i].Duration));
            return;
        }

        int cells = 1;
        if (columns * rows > 1)
        {
            if (info.Width / columns < 1 || info.Height / rows < 1)
                throw new InvalidDataException($"{Path.GetFileName(path)} is smaller than its {columns}x{rows} grid.");
            cells = CellCount(columns, rows, count);
        }
        for (int i = 0; i < cells; i++) durations.Add(1 / fps);
    }

    /// <summary>
    /// Decodes the frames of one clip, or only the first <paramref name="limit"/> of them. The
    /// caller owns the bitmaps, including any that were added before a failure.
    /// </summary>
    static void DecodeClip(string dir, ClipSource src, PackOptions options, int threads, int limit,
        List<SKBitmap> frames, List<double> durations)
    {
        double fps = FrameRate(src, options);
        if (src.Folder != null)
        {
            // Each file in the folder is a picture of its own, so they are decoded side by
            // side and put back in name order.
            var files = FolderFiles(dir, src);
            int wanted = Math.Min(files.Length, limit);
            var parts = new (List<SKBitmap> Frames, List<double> Durations)[wanted];
            for (int i = 0; i < wanted; i++) parts[i] = ([], []);
            try
            {
                Each(wanted, threads, i =>
                    DecodeFile(files[i], 1, 1, 0, fps, options, wanted > 1 ? 1 : threads, limit, parts[i].Frames, parts[i].Durations));
            }
            finally
            {
                foreach (var part in parts)
                {
                    frames.AddRange(part.Frames);
                    durations.AddRange(part.Durations);
                }
            }
        }
        else
        {
            DecodeFile(ClipFile(dir, src), src.Columns, src.Rows, src.Count, fps, options, threads, limit, frames, durations);
        }
        if (frames.Count == 0) throw new InvalidDataException($"Clip '{src.Key}' has no frames.");
    }

    static void DecodeFile(string path, int columns, int rows, int count, double fps, PackOptions options,
        int threads, int limit, List<SKBitmap> frames, List<double> durations)
    {
        using var codec = OpenCodec(path, out var info);
        int animated = codec.FrameCount;
        if (animated > 1)
        {
            // Animated GIF / WebP.
            var frameInfo = codec.FrameInfo;
            int n = Math.Min(Math.Min(animated, MaxFramesPerClip), limit);
            var composed = new SKBitmap?[n];
            try
            {
                DecodeAnimation(path, codec, info, frameInfo, composed, threads);
                // Only once every frame is composed: a frame that others build on has to be
                // as it was decoded when they do.
                Each(n, threads, i => MaybeRemoveBackground(composed[i]!, options));
            }
            catch
            {
                foreach (var bmp in composed) bmp?.Dispose();
                throw;
            }
            for (int i = 0; i < n; i++)
            {
                frames.Add(composed[i]!);
                durations.Add(FrameSeconds(frameInfo[i].Duration));
            }
            return;
        }

        var sheet = SKBitmap.Decode(codec, info)
                    ?? throw new InvalidDataException($"Could not decode {Path.GetFileName(path)}.");
        MaybeRemoveBackground(sheet, options);
        if (columns * rows <= 1)
        {
            frames.Add(sheet);
            durations.Add(1 / fps);
            return;
        }

        using (sheet)
        {
            int cw = sheet.Width / columns, ch = sheet.Height / rows;
            if (cw < 1 || ch < 1) throw new InvalidDataException($"{Path.GetFileName(path)} is smaller than its {columns}x{rows} grid.");
            int total = Math.Min(CellCount(columns, rows, count), limit);
            for (int i = 0; i < total; i++)
            {
                var cell = new SKBitmap(InfoFor(cw, ch));
                cell.Erase(SKColors.Transparent);
                using (var canvas = new SKCanvas(cell))
                {
                    var from = SKRect.Create(i % columns * cw, i / columns * ch, cw, ch);
                    using var paint = new SKPaint { BlendMode = SKBlendMode.Src };
                    canvas.DrawBitmap(sheet, from, SKRect.Create(cw, ch), paint);
                }
                frames.Add(cell);
                durations.Add(1 / fps);
            }
        }
    }

    /// <summary>
    /// Composes the frames of an animated file. A frame is often stored as the changes to an
    /// earlier one, so in general they can only be decoded in order. But these files also
    /// hold a complete picture every few frames, and a run of frames that starts at one
    /// needs nothing from before it. Those runs are decoded side by side, which is most of
    /// what makes a long clip quick to load.
    /// </summary>
    static void DecodeAnimation(string path, SKCodec codec, SKImageInfo info, SKCodecFrameInfo[] frameInfo,
        SKBitmap?[] composed, int threads)
    {
        var runs = IndependentRuns(frameInfo, composed.Length);
        if (threads <= 1 || runs.Count <= 1)
        {
            DecodeRun(path, codec, info, frameInfo, composed, 0, composed.Length);
            return;
        }

        // A codec decodes one frame at a time, so each thread opens the file for itself.
        var errors = new Exception?[runs.Count];
        Parallel.For(0, runs.Count, new ParallelOptions { MaxDegreeOfParallelism = threads },
            () => (SKCodec?)null,
            (r, loop, own) =>
            {
                try
                {
                    own ??= OpenCodec(path, out _);
                    DecodeRun(path, own, info, frameInfo, composed, runs[r].Start, runs[r].End);
                }
                catch (Exception ex)
                {
                    errors[r] = ex;
                }
                return own;
            },
            own => own?.Dispose());
        if (errors.FirstOrDefault(e => e != null) is { } first)
            ExceptionDispatchInfo.Capture(first).Throw();
    }

    /// <summary>
    /// Splits the frames into runs that can each be decoded without any frame outside the run:
    /// a run starts at a frame that builds on nothing, and no later frame reaches back past it.
    /// </summary>
    static List<(int Start, int End)> IndependentRuns(SKCodecFrameInfo[] frameInfo, int count)
    {
        var runs = new List<(int Start, int End)>();
        int end = count, earliestNeeded = int.MaxValue;
        for (int i = count - 1; i >= 0; i--)
        {
            int required = frameInfo[i].RequiredFrame;
            if (required >= 0 && required < i)
            {
                earliestNeeded = Math.Min(earliestNeeded, required);
            }
            else if (earliestNeeded >= i)
            {
                runs.Add((i, end));
                end = i;
            }
        }
        runs.Reverse();
        return runs;
    }

    static unsafe void DecodeRun(string path, SKCodec codec, SKImageInfo info, SKCodecFrameInfo[] frameInfo,
        SKBitmap?[] composed, int start, int end)
    {
        for (int i = start; i < end; i++)
        {
            var bmp = new SKBitmap(info);
            int required = frameInfo[i].RequiredFrame;
            SKCodecOptions opts;
            if (required >= 0 && required < i)
            {
                Buffer.MemoryCopy((void*)composed[required]!.GetPixels(), (void*)bmp.GetPixels(), bmp.ByteCount, bmp.ByteCount);
                opts = new SKCodecOptions(i, required);
            }
            else
            {
                bmp.Erase(SKColors.Transparent);
                opts = new SKCodecOptions(i);
            }
            var result = codec.GetPixels(info, bmp.GetPixels(), opts);
            if (result is not (SKCodecResult.Success or SKCodecResult.IncompleteInput))
            {
                bmp.Dispose();
                throw new InvalidDataException($"Could not decode frame {i + 1} of {Path.GetFileName(path)} ({result}).");
            }
            composed[i] = bmp;
        }
    }

    // ---- Background removal ----

    static void MaybeRemoveBackground(SKBitmap bmp, PackOptions options)
    {
        if (options.RemoveBackground == false) return;
        if (options.KeyColor is { } key)
        {
            FloodRemove(bmp, key, options.Tolerance);
            return;
        }
        // Automatic: only touch images with no transparency at all whose corners agree on a
        // colour. Art that already has an alpha channel is never altered.
        if (HasTransparency(bmp)) return;
        if (CornerColour(bmp, options.Tolerance) is { } corner) FloodRemove(bmp, corner, options.Tolerance);
    }

    static unsafe bool HasTransparency(SKBitmap bmp)
    {
        // Each of these is a call into Skia, so they are read once, not once per pixel.
        int w = bmp.Width, h = bmp.Height, stride = bmp.RowBytes;
        byte* px = (byte*)bmp.GetPixels();
        for (int y = 0; y < h; y++)
        {
            byte* row = px + y * stride;
            for (int x = 0; x < w; x++)
                if (row[x * 4 + 3] < 250) return true;
        }
        return false;
    }

    static SKColor? CornerColour(SKBitmap bmp, int tolerance)
    {
        var a = bmp.GetPixel(0, 0);
        SKColor[] others = [bmp.GetPixel(bmp.Width - 1, 0), bmp.GetPixel(0, bmp.Height - 1), bmp.GetPixel(bmp.Width - 1, bmp.Height - 1)];
        foreach (var o in others)
            if (Math.Max(Math.Abs(o.Red - a.Red), Math.Max(Math.Abs(o.Green - a.Green), Math.Abs(o.Blue - a.Blue))) > tolerance)
                return null;
        return a;
    }

    /// <summary>
    /// Erases the background colour starting from the image border and working inwards, so
    /// patches of the same colour inside the character (white eyes on a white backdrop) survive.
    /// </summary>
    static unsafe void FloodRemove(SKBitmap bmp, SKColor key, int tolerance)
    {
        int w = bmp.Width, h = bmp.Height, stride = bmp.RowBytes;
        byte* px = (byte*)bmp.GetPixels();
        var visited = new bool[w * h];
        var stack = new Stack<int>();
        int soft = (int)(tolerance * 2.2) + 1;

        int Distance(int index)
        {
            byte* p = px + index / w * stride + index % w * 4;
            int a = p[3];
            if (a == 0) return 0;
            // Stored premultiplied; undo that before comparing colours.
            int b = p[0] * 255 / a, g = p[1] * 255 / a, r = p[2] * 255 / a;
            return Math.Max(Math.Abs(r - key.Red), Math.Max(Math.Abs(g - key.Green), Math.Abs(b - key.Blue)));
        }

        void Visit(int index)
        {
            if (visited[index]) return;
            visited[index] = true;
            int d = Distance(index);
            byte* p = px + index / w * stride + index % w * 4;
            if (d <= tolerance)
            {
                p[0] = p[1] = p[2] = p[3] = 0;
                stack.Push(index);
            }
            else if (d < soft)
            {
                // Edge pixel: partly background. Keep a matching share of it and take the
                // background colour back out so no halo is left behind.
                double keep = (double)(d - tolerance) / (soft - tolerance);
                p[0] = (byte)Math.Clamp(p[0] - key.Blue * (1 - keep), 0, 255 * keep);
                p[1] = (byte)Math.Clamp(p[1] - key.Green * (1 - keep), 0, 255 * keep);
                p[2] = (byte)Math.Clamp(p[2] - key.Red * (1 - keep), 0, 255 * keep);
                p[3] = (byte)(p[3] * keep);
            }
        }

        for (int x = 0; x < w; x++) { Visit(x); Visit((h - 1) * w + x); }
        for (int y = 0; y < h; y++) { Visit(y * w); Visit(y * w + w - 1); }
        while (stack.Count > 0)
        {
            int i = stack.Pop();
            int x = i % w, y = i / w;
            if (x > 0) Visit(i - 1);
            if (x < w - 1) Visit(i + 1);
            if (y > 0) Visit(i - w);
            if (y < h - 1) Visit(i + w);
        }
    }

    // ---- Clip assembly ----

    /// <summary>The rectangle that holds everything drawn in any of the frames.</summary>
    static SKRectI ContentBounds(List<SKBitmap> frames, int threads)
    {
        var each = new SKRectI[frames.Count];
        Each(frames.Count, threads, i => each[i] = ContentBounds(frames[i]));

        int left = int.MaxValue, top = int.MaxValue, right = 0, bottom = 0;
        foreach (var r in each)
        {
            if (r.IsEmpty) continue;
            left = Math.Min(left, r.Left);
            top = Math.Min(top, r.Top);
            right = Math.Max(right, r.Right);
            bottom = Math.Max(bottom, r.Bottom);
        }
        return right == 0 ? SKRectI.Empty : new SKRectI(left, top, right, bottom);
    }

    /// <summary>
    /// The rectangle that holds everything drawn in one frame. Only the empty margin is
    /// looked at: each side is searched inwards and the search stops where the drawing starts.
    /// </summary>
    static unsafe SKRectI ContentBounds(SKBitmap bmp)
    {
        // Each of these is a call into Skia, so they are read once, not once per pixel.
        int w = bmp.Width, h = bmp.Height, stride = bmp.RowBytes;
        byte* px = (byte*)bmp.GetPixels();

        static bool Drawn(byte* row, int from, int to)
        {
            for (int x = from; x < to; x++)
                if (row[x * 4 + 3] > 12) return true;
            return false;
        }

        int top = 0;
        while (top < h && !Drawn(px + (long)top * stride, 0, w)) top++;
        if (top == h) return SKRectI.Empty;
        int bottom = h - 1;
        while (bottom > top && !Drawn(px + (long)bottom * stride, 0, w)) bottom--;

        // A pixel can only move the left edge if it lies to the left of it, and likewise on
        // the right, so each row is searched no further in than the edges found so far.
        int left = w, right = -1;
        for (int y = top; y <= bottom; y++)
        {
            byte* row = px + (long)y * stride;
            for (int x = 0; x < left; x++)
                if (row[x * 4 + 3] > 12) { left = x; break; }
            for (int x = w - 1; x > right; x--)
                if (row[x * 4 + 3] > 12) { right = x; break; }
        }
        return new SKRectI(left, top, right + 1, bottom + 1);
    }

    static readonly SKSamplingOptions Smooth = new(SKFilterMode.Linear, SKMipmapMode.Linear);

    /// <summary>
    /// Cuts the kept part out of a decoded frame, scaled down if the pack's pictures are
    /// too large, as a bitmap that can be drawn.
    /// </summary>
    static unsafe Bitmap Trim(SKBitmap frame, SKRectI crop, int outW, int outH, double shrink)
    {
        var size = new PixelSize(outW, outH);
        var dpi = new Vector(96, 96);

        // Nothing to resize, which is the usual case. The bitmap takes its own copy of the
        // rows it is given, so it is given the kept rows where they lie in the frame: no
        // canvas, and no copy of our own in between.
        if (shrink == 1 && frame.Width >= crop.Right && frame.Height >= crop.Bottom)
        {
            byte* from = (byte*)frame.GetPixels() + (long)crop.Top * frame.RowBytes + crop.Left * 4;
            return new Bitmap(PixelFormat.Bgra8888, AlphaFormat.Premul, (nint)from, size, dpi, frame.RowBytes);
        }

        // An image made from a bitmap that might still change starts by copying it. This
        // frame is finished with, and saying so spares that copy.
        frame.SetImmutable();
        using var cell = new SKBitmap(InfoFor(outW, outH));
        cell.Erase(SKColors.Transparent);
        using (var canvas = new SKCanvas(cell))
        using (var image = SKImage.FromBitmap(frame))
        using (var paint = new SKPaint { BlendMode = SKBlendMode.Src })
        {
            var from = SKRect.Create(crop.Left, crop.Top, crop.Width, crop.Height);
            canvas.DrawImage(image, from, SKRect.Create(outW, outH), shrink < 1 ? Smooth : SKSamplingOptions.Default, paint);
        }
        return new Bitmap(PixelFormat.Bgra8888, AlphaFormat.Premul, cell.GetPixels(), size, dpi, cell.RowBytes);
    }

    static SpriteClip BuildClip(ClipSource src, List<SKBitmap> frames, List<double> durations, PackOptions options,
        double idleHeight, double idleShrink, int threads, out double shrink)
    {
        // Frames in one clip must share a size so they can share an anchor.
        int fw = frames.Max(f => f.Width), fh = frames.Max(f => f.Height);
        var bounds = ContentBounds(frames, threads);
        if (bounds.IsEmpty) bounds = new SKRectI(0, 0, fw, fh);

        // Trim the empty margin, leaving a pixel of breathing room for smooth edges.
        var crop = new SKRectI(Math.Max(0, bounds.Left - 1), Math.Max(0, bounds.Top - 1),
            Math.Min(fw, bounds.Right + 1), Math.Min(fh, bounds.Bottom + 1));

        shrink = 1;
        int longest = Math.Max(crop.Width, crop.Height);
        if (!options.PixelArt && longest > MaxFrameSide) shrink = (double)MaxFrameSide / longest;
        int outW = Math.Max(1, (int)Math.Round(crop.Width * shrink)), outH = Math.Max(1, (int)Math.Round(crop.Height * shrink));
        double scaleDown = shrink;

        var bitmaps = new Bitmap?[frames.Count];
        try
        {
            Each(frames.Count, threads, i =>
            {
                bitmaps[i] = Trim(frames[i], crop, outW, outH, scaleDown);
                // The decoded frame has done its job. Letting go of it here, not when the
                // whole pack is done, is what keeps a load from holding every frame twice.
                frames[i].Dispose();
            });
        }
        catch
        {
            foreach (var bitmap in bitmaps) bitmap?.Dispose();
            throw;
        }
        var ends = FrameEnds(durations);

        double contentH = bounds.Height * shrink, contentW = bounds.Width * shrink;
        double anchorX = src.AnchorX is { } ax ? (ax - crop.Left) * shrink : (bounds.MidX - crop.Left) * shrink;
        double anchorY = src.AnchorY is { } ay ? (ay - crop.Top) * shrink : (bounds.Bottom - crop.Top) * shrink;

        // Everything is drawn relative to the idle clip. Clips are assumed to share its pixel
        // scale, so cancel out any difference in how much each was shrunk on load; or match
        // heights outright when the pack asks for that.
        double scale = src.Scale;
        if (src.Key != "idle")
        {
            if (options.Normalize && idleHeight > 0) scale *= idleHeight / contentH;
            else scale *= idleShrink / shrink;
        }

        return new SpriteClip
        {
            Frames = bitmaps!,
            Ends = ends,
            Name = src.Name ?? PrettyName(src.Key),
            Loop = src.Loop,
            AnchorX = anchorX,
            AnchorY = anchorY,
            ContentWidth = contentW,
            ContentHeight = contentH,
            Scale = scale,
        };
    }

    /// <summary>Orders "frame2" before "frame10".</summary>
    sealed partial class NaturalOrder : IComparer<string>
    {
        public static readonly NaturalOrder Instance = new();

        [GeneratedRegex(@"\d+|\D+")]
        private static partial Regex Chunks();

        public int Compare(string? a, string? b)
        {
            var ca = Chunks().Matches(Path.GetFileName(a ?? ""));
            var cb = Chunks().Matches(Path.GetFileName(b ?? ""));
            for (int i = 0; i < Math.Min(ca.Count, cb.Count); i++)
            {
                string x = ca[i].Value, y = cb[i].Value;
                int cmp = char.IsDigit(x[0]) && char.IsDigit(y[0]) && long.TryParse(x, out long nx) && long.TryParse(y, out long ny)
                    ? nx.CompareTo(ny)
                    : string.Compare(x, y, StringComparison.OrdinalIgnoreCase);
                if (cmp != 0) return cmp;
            }
            return ca.Count.CompareTo(cb.Count);
        }
    }
}
