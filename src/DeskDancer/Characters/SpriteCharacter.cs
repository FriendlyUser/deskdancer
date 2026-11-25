using System.Diagnostics;
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

/// <summary>A frame as the decoder left it, and where in it the part that is kept begins.</summary>
public readonly record struct DecodedFrame(SKBitmap Pixels, int Left, int Top);

/// <summary>
/// One animation, unpacked: a run of frames with their timings and where the feet are.
/// A frame stays as the decoder left it until the first time it is drawn, and only then is
/// copied into a bitmap the window can show. That copy is the one part of loading that
/// has to be done on the UI thread, and done like this it is one frame's worth at a time.
/// </summary>
public sealed class SpriteClip : IDisposable
{
    readonly DecodedFrame?[] _decoded;
    readonly Bitmap?[] _frames;
    readonly PixelSize _size;

    public SpriteClip(DecodedFrame[] frames, PixelSize size)
    {
        _decoded = new DecodedFrame?[frames.Length];
        for (int i = 0; i < frames.Length; i++) _decoded[i] = frames[i];
        _frames = new Bitmap?[frames.Length];
        _size = size;
    }

    /// <summary>Time in seconds at which each frame ends.</summary>
    public required double[] Ends { get; init; }
    public bool Loop { get; init; } = true;
    /// <summary>Point between the feet, in frame pixels.</summary>
    public double AnchorX { get; init; }
    public double AnchorY { get; init; }
    /// <summary>Height of the drawn character in frame pixels.</summary>
    public double ContentHeight { get; init; }
    public double ContentWidth { get; init; }
    /// <summary>Extra scale so this clip matches the idle clip's size on screen.</summary>
    public double Scale { get; init; } = 1;
    /// <summary>How long the frames took to decode, in milliseconds.</summary>
    public double DecodeTime { get; set; }

    public double Duration => Ends[^1];
    public int FrameCount => _frames.Length;
    /// <summary>Memory the frames take up, in bytes.</summary>
    public long Bytes => (long)_size.Width * _size.Height * 4 * _frames.Length;

    public Bitmap FrameAt(double time)
    {
        int i = 0;
        if (_frames.Length > 1)
        {
            double t = Loop ? time % Duration : Math.Min(time, Duration - 1e-6);
            if (t < 0) t = 0;
            i = Array.BinarySearch(Ends, t);
            i = Math.Min(i < 0 ? ~i : i + 1, _frames.Length - 1);
        }
        return _frames[i] ??= ToBitmap(i);
    }

    unsafe Bitmap ToBitmap(int i)
    {
        var (pixels, left, top) = _decoded[i]!.Value;
        // The bitmap takes its own copy, and reads no more of each row than it is wide, so
        // it can be pointed straight at the part of the frame that is kept.
        byte* from = (byte*)pixels.GetPixels() + (long)top * pixels.RowBytes + (long)left * 4;
        var bitmap = new Bitmap(PixelFormat.Bgra8888, AlphaFormat.Premul, (nint)from, _size, new Vector(96, 96), pixels.RowBytes);
        pixels.Dispose();
        _decoded[i] = null;
        return bitmap;
    }

    public void Dispose()
    {
        for (int i = 0; i < _frames.Length; i++)
        {
            if (_frames[i] != null) PictureMemory.Freed((long)_size.Width * _size.Height * 4);
            _frames[i]?.Dispose();
            _frames[i] = null;
            _decoded[i]?.Pixels.Dispose();
            _decoded[i] = null;
        }
    }
}

/// <summary>
/// One of a character's animations. What it is called and how long it runs are known as
/// soon as the pack is opened. Its frames are decoded when something asks for them, on
/// another thread unless the caller would rather wait, and can be let go of again.
/// Apart from that decoding, everything here happens on the UI thread.
/// </summary>
public sealed class LazyClip
{
    readonly Func<SpriteClip> _decode;
    readonly string _where;
    Task<SpriteClip>? _decoding;
    SpriteClip? _frames;

    /// <param name="ready">The frames, if they have already been decoded.</param>
    public LazyClip(string key, string name, double seconds, string folder, Func<SpriteClip> decode, SpriteClip? ready = null)
    {
        Key = key;
        Name = name;
        Seconds = seconds;
        _where = $"'{key}' clip of {folder}";
        _decode = decode;
        _frames = ready;
    }

    public string Key { get; }
    public string Name { get; }
    /// <summary>How long one run of the clip takes, read from its files without decoding them.</summary>
    public double Seconds { get; }
    /// <summary>Why the frames could not be decoded, if that was tried and went wrong.</summary>
    public Exception? Failure { get; private set; }
    public bool InMemory => _frames != null;
    public long Bytes => _frames?.Bytes ?? 0;
    /// <summary>When the frames were last asked for, as <see cref="Environment.TickCount64"/>.</summary>
    public long LastWanted { get; private set; }

    /// <summary>Starts decoding on another thread, unless that is done, under way or has failed before.</summary>
    public void Fetch()
    {
        LastWanted = Environment.TickCount64;
        if (_frames == null && _decoding == null && Failure == null) _decoding = Task.Run(_decode);
    }

    /// <summary>
    /// The frames, if they are in memory. If they are not, decoding starts and the answer
    /// for now is null; with <paramref name="wait"/> the call only returns once it is done.
    /// </summary>
    public SpriteClip? Frames(bool wait = false)
    {
        LastWanted = Environment.TickCount64;
        if (_frames != null || Failure != null) return _frames;
        if (_decoding == null && !wait) _decoding = Task.Run(_decode);
        if (_decoding is { IsCompleted: false } && !wait) return null;

        var decoding = _decoding;
        _decoding = null;
        try
        {
            // Waiting for another thread here is safe: decoding never needs this one.
            _frames = decoding != null ? decoding.GetAwaiter().GetResult() : _decode();
            Log.Info($"Loaded the {_where}: {_frames.FrameCount} frames, {_frames.Bytes / 1e6:0.0} MB, decoded in {_frames.DecodeTime:0} ms");
        }
        catch (Exception ex)
        {
            Failure = ex;
            Log.Error($"Could not load the {_where}", ex);
        }
        return _frames;
    }

    /// <summary>
    /// Lets go of the frames and returns how many bytes that gave up. They are decoded
    /// again the next time they are wanted.
    /// </summary>
    public long Release()
    {
        long bytes = Bytes;
        if (_frames != null) Log.Info($"Let go of the {_where} ({bytes / 1e6:0.0} MB)");
        _frames?.Dispose();
        _frames = null;
        if (_decoding is { } decoding)
        {
            // Still being decoded, or decoded and never looked at: nobody is waiting for it now.
            _decoding = null;
            decoding.ContinueWith(static done =>
            {
                if (done.IsCompletedSuccessfully) done.Result.Dispose();
                else _ = done.Exception;
            }, TaskScheduler.Default);
        }
        return bytes;
    }
}

/// <summary>
/// A character made from the user's own image files. Only the idle clip is kept in memory
/// throughout. Each of the others is decoded the first time the mate does what it is for,
/// and dropped again by <see cref="ReleaseUnused"/> once it has not been shown for a while.
/// </summary>
public sealed class SpriteCharacter : ICharacter
{
    // Which clip stands in when the requested one was not supplied.
    static readonly Dictionary<string, string[]> Fallbacks = new()
    {
        ["fall"] = ["drag"],
        ["drag"] = ["fall"],
        ["sleep"] = ["sit"],
    };

    readonly Dictionary<string, LazyClip> _clips;
    readonly LazyClip _idle;
    readonly double _idleHeight;

    /// <param name="clips">Every clip of the pack. The idle one must already be decoded.</param>
    public SpriteCharacter(string id, string name, Dictionary<string, LazyClip> clips, double height, int facing, bool pixelArt)
    {
        Id = id;
        DisplayName = name;
        _clips = clips;
        _idle = clips["idle"];
        PreferredHeight = height;
        NaturalFacing = facing;
        PixelArt = pixelArt;
        // Everything is drawn relative to the idle clip, so its measurements are kept for
        // good, whatever happens to its frames later.
        var idle = _idle.Frames(wait: true) ?? throw new InvalidDataException("The idle clip could not be read.");
        _idleHeight = idle.ContentHeight;
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

    /// <summary>The clips whose frames are in memory right now.</summary>
    public IEnumerable<string> ClipsInMemory => _clips.Values.Where(c => c.InMemory).Select(c => c.Key);
    /// <summary>Memory those frames take up, in bytes.</summary>
    public long BytesInMemory => _clips.Values.Sum(c => c.Bytes);
    /// <summary>What went wrong, if one of the clips could not be decoded when it was wanted.</summary>
    public string? Problem =>
        _clips.Values.FirstOrDefault(c => c.Failure != null) is { } broken ? $"Clip '{broken.Key}': {broken.Failure!.Message}" : null;

    public bool HasClip(string clip) => _clips.ContainsKey(clip);

    LazyClip Resolve(string clip)
    {
        if (_clips.TryGetValue(clip, out var found)) return found;
        if (Fallbacks.TryGetValue(clip, out var alternatives))
            foreach (var alt in alternatives)
                if (_clips.TryGetValue(alt, out found)) return found;
        return _idle;
    }

    public void Prepare(string clip) => Resolve(clip).Fetch();

    /// <summary>
    /// Has frames in memory before returning: those of the idle clip, which nothing can be
    /// drawn without, or of every clip. Returns false if the idle clip cannot be read.
    /// </summary>
    public bool LoadNow(bool everyClip = false)
    {
        if (_idle.Frames(wait: true) == null) return false;
        if (!everyClip) return true;

        // Set them all going, then wait for each in turn.
        foreach (var clip in _clips.Values) clip.Fetch();
        foreach (var clip in _clips.Values) clip.Frames(wait: true);
        return true;
    }

    /// <summary>
    /// Lets go of the frames of every clip that has not been asked for since
    /// <paramref name="since"/>, a value of <see cref="Environment.TickCount64"/>, and
    /// returns how many bytes that gave up. Drawing asks for the idle clip every time, so
    /// a character that is on screen never loses that one.
    /// </summary>
    public long ReleaseUnused(long since)
    {
        long bytes = 0;
        foreach (var clip in _clips.Values)
            if (clip.LastWanted <= since) bytes += clip.Release();
        return bytes;
    }

    public void Draw(DrawingContext ctx, double height, in CharacterFrame frame)
    {
        // The idle clip stands in while another is being decoded, so it is wanted every time.
        var idle = _idle.Frames(wait: true);
        var wanted = Resolve(frame.Clip);
        var clip = ReferenceEquals(wanted, _idle) ? idle : wanted.Frames() ?? idle;
        // Without an idle clip there is nothing to show. That only happens if its files have
        // gone since the pack was opened, and it is in the log.
        if (clip == null) return;

        var bitmap = clip.FrameAt(frame.ClipTime);
        double s = height / _idleHeight * clip.Scale;
        var size = bitmap.Size;
        var dest = new Rect(-clip.AnchorX * s, -clip.AnchorY * s, size.Width * s, size.Height * s);
        ctx.DrawImage(bitmap, new Rect(size), dest);
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
        /// <summary>Only the first frame is used, and held: an idle clip borrowed from another clip.</summary>
        public bool Still;
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

    /// <summary>
    /// Opens a pack: reads its settings, checks the files of every clip and decodes the
    /// idle one. Nothing here touches the UI, so it can be done on any thread.
    /// </summary>
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

        // Every clip's files are opened now. That finds a missing or unreadable one while
        // the pack is being loaded, and says how long each clip runs, without decoding a
        // single frame. The clips are gone through in the order they were found, so a pack
        // reports the same problem every time.
        var seconds = new Dictionary<string, double>();
        foreach (var src in sources.Values)
        {
            var durations = new List<double>();
            ReadClip(dir, src, options, durations, null);
            seconds[src.Key] = EndTimes(durations)[^1];
        }

        if (!sources.ContainsKey("idle"))
        {
            // No idle supplied: stand still on the first frame of whatever there is.
            var donor = sources.Values.FirstOrDefault(s => KnownClips.Contains(s.Key)) ?? sources.Values.First();
            sources["idle"] = new ClipSource
            {
                Key = "idle", File = donor.File, Folder = donor.Folder, Columns = donor.Columns, Rows = donor.Rows,
                Count = donor.Count, Fps = donor.Fps, Still = true,
            };
            seconds["idle"] = 1;
        }

        // The idle clip is decoded here and now: the mate is measured by it, and every
        // other clip is sized against it. The rest wait until they are wanted.
        var idle = DecodeClip(dir, sources["idle"], options, 0, 1, out double idleShrink);
        double idleHeight = idle.ContentHeight;

        var clips = new Dictionary<string, LazyClip>();
        foreach (var src in sources.Values.OrderBy(s => s.Key == "idle" ? 0 : 1))
        {
            clips[src.Key] = new LazyClip(src.Key, src.Name ?? PrettyName(src.Key), seconds[src.Key], dir,
                () => DecodeClip(dir, src, options, idleHeight, idleShrink, out _), src.Key == "idle" ? idle : null);
        }

        string name = options.Name ?? Path.GetFileName(dir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
        Log.Info($"Opened {dir}: {clips.Count} clips; the idle one has {idle.FrameCount} frames, {idle.Bytes / 1e6:0.0} MB, decoded in {idle.DecodeTime:0} ms");
        return new SpriteCharacter(id, name, clips, options.Height, options.Facing, options.PixelArt);
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

    /// <summary>
    /// A bitmap to decode a frame into, fully transparent to begin with. Its memory is
    /// taken from <see cref="PictureMemory"/> and not from Skia, so that all of it goes
    /// back to the system the moment the frame is finished with.
    /// </summary>
    static SKBitmap NewFrame(SKImageInfo info)
    {
        var memory = PictureMemory.Take(info.BytesSize64);
        var bitmap = new SKBitmap();
        // Skia gives the memory back itself, when the bitmap goes or if it will not have it.
        if (bitmap.InstallPixels(info, memory.Address, info.RowBytes, (_, _) => memory.GiveBack())) return bitmap;
        bitmap.Dispose();
        throw new InvalidDataException($"Could not make a {info.Width}x{info.Height} bitmap.");
    }

    /// <summary>How many threads decode one animation at a time: all but one, which is left for the mate to keep moving.</summary>
    static readonly ParallelOptions SideBySide = new() { MaxDegreeOfParallelism = Math.Max(1, Environment.ProcessorCount - 1) };

    /// <summary>
    /// Decodes one clip and measures it. This is where the time goes when a pack is
    /// loaded, and none of it touches the UI, so it can be done on any thread.
    /// </summary>
    static SpriteClip DecodeClip(string dir, ClipSource src, PackOptions options, double idleHeight, double idleShrink, out double shrink)
    {
        var watch = Stopwatch.StartNew();
        var frames = new List<SKBitmap>();
        var durations = new List<double>();
        try
        {
            ReadClip(dir, src, options, durations, frames);
            var clip = BuildClip(src, frames, durations, options, idleHeight, idleShrink, out shrink);
            clip.DecodeTime = watch.Elapsed.TotalMilliseconds;
            return clip;
        }
        catch
        {
            foreach (var frame in frames) frame.Dispose();
            throw;
        }
    }

    /// <summary>
    /// Goes through the file or folder a clip is made from. How long each frame is shown
    /// is always read, which takes no decoding. The frames themselves are only decoded
    /// when there is a list to put them in.
    /// </summary>
    static void ReadClip(string dir, ClipSource src, PackOptions options, List<double> durations, List<SKBitmap>? frames)
    {
        double fps = Math.Clamp(src.Fps ?? options.Fps, 0.5, 120);
        int limit = src.Still ? 1 : int.MaxValue;
        if (src.Folder != null)
        {
            string folder = Path.Combine(dir, src.Folder);
            if (!Directory.Exists(folder)) throw new InvalidDataException($"Folder not found: {src.Folder}");
            foreach (var file in Directory.EnumerateFiles(folder).Where(IsImage).OrderBy(f => f, NaturalOrder.Instance))
            {
                if (durations.Count >= limit) break;
                ReadFile(file, 1, 1, 0, fps, options, durations, frames, limit);
            }
        }
        else
        {
            string file = Path.Combine(dir, src.File!);
            if (!File.Exists(file)) throw new InvalidDataException($"File not found: {src.File}");
            ReadFile(file, src.Columns, src.Rows, src.Count, fps, options, durations, frames, limit);
        }
        if (durations.Count == 0) throw new InvalidDataException($"Clip '{src.Key}' has no frames.");
        if (src.Still) durations[0] = 1;
    }

    /// <summary>The time at which each frame ends, given how long each one is shown.</summary>
    static double[] EndTimes(List<double> durations)
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

    static unsafe void ReadFile(string path, int columns, int rows, int count, double fps, PackOptions options,
        List<double> durations, List<SKBitmap>? frames, int limit)
    {
        using var codec = SKCodec.Create(path, out var status)
                          ?? throw new InvalidDataException($"Could not read {Path.GetFileName(path)} ({status}).");
        var info = InfoFor(codec.Info.Width, codec.Info.Height);
        if (info.Width <= 0 || info.Height <= 0 || (long)info.Width * info.Height > 64_000_000)
            throw new InvalidDataException($"{Path.GetFileName(path)} is too large.");

        int animated = codec.FrameCount;
        if (animated > 1)
        {
            var frameInfo = codec.FrameInfo;
            int n = Math.Min(Math.Min(animated, MaxFramesPerClip), limit);
            for (int i = 0; i < n; i++)
            {
                int ms = frameInfo[i].Duration;
                durations.Add(ms <= 10 ? 0.1 : ms / 1000.0);
            }
            if (frames == null) return;

            // Animated GIF / WebP. Later frames are often stored as changes to an earlier one,
            // so every composed frame is kept until the whole file has been read. Frames
            // that build on one another have to be decoded in order, but most files start
            // again from a whole picture every few frames. Each such run of frames can be
            // decoded without the others, so the runs are decoded side by side.
            var composed = new SKBitmap?[n];
            var results = new SKCodecResult[n];
            var start = new int[n];
            for (int i = 0; i < n; i++)
            {
                int required = frameInfo[i].RequiredFrame;
                start[i] = required >= 0 && required < i ? start[required] : i;
            }
            var runs = Enumerable.Range(0, n).GroupBy(i => start[i]).Select(run => run.ToArray()).ToArray();

            SKCodecResult Compose(SKCodec decoder, int i)
            {
                var bmp = NewFrame(info);
                int required = frameInfo[i].RequiredFrame;
                var opts = new SKCodecOptions(i);
                if (required >= 0 && required < i)
                {
                    Buffer.MemoryCopy((void*)composed[required]!.GetPixels(), (void*)bmp.GetPixels(), bmp.ByteCount, bmp.ByteCount);
                    opts = new SKCodecOptions(i, required);
                }
                var result = decoder.GetPixels(info, bmp.GetPixels(), opts);
                if (result is SKCodecResult.Success or SKCodecResult.IncompleteInput) composed[i] = bmp;
                else bmp.Dispose();
                return result;
            }

            try
            {
                // A decoder cannot be shared between threads, so each one opens its own.
                Parallel.ForEach(runs, SideBySide, () => (SKCodec?)null, (run, _, decoder) =>
                {
                    decoder ??= SKCodec.Create(path, out var opened)
                                ?? throw new InvalidDataException($"Could not read {Path.GetFileName(path)} ({opened}).");
                    foreach (int i in run)
                    {
                        results[i] = Compose(decoder, i);
                        if (composed[i] == null) break;
                    }
                    return decoder;
                }, decoder => decoder?.Dispose());
            }
            catch (AggregateException ex)
            {
                foreach (var c in composed) c?.Dispose();
                ExceptionDispatchInfo.Capture(ex.InnerExceptions[0]).Throw();
            }

            // A run stops at the frame that goes wrong, so the earliest frame missing is the
            // one that would have been reported had they been decoded one after another.
            int bad = Array.FindIndex(composed, c => c == null);
            if (bad >= 0)
            {
                foreach (var c in composed) c?.Dispose();
                throw new InvalidDataException($"Could not decode frame {bad + 1} of {Path.GetFileName(path)} ({results[bad]}).");
            }
            for (int i = 0; i < n; i++)
            {
                MaybeRemoveBackground(composed[i]!, options);
                frames.Add(composed[i]!);
            }
            return;
        }

        // A single picture, or a sheet of them laid out in a grid.
        bool single = columns * rows <= 1;
        int cw = info.Width / columns, ch = info.Height / rows;
        if (!single && (cw < 1 || ch < 1))
            throw new InvalidDataException($"{Path.GetFileName(path)} is smaller than its {columns}x{rows} grid.");
        int total = single ? 1 : Math.Min(Math.Min(count > 0 ? Math.Min(count, columns * rows) : columns * rows, MaxFramesPerClip), limit);
        for (int i = 0; i < total; i++) durations.Add(1 / fps);
        if (frames == null) return;

        var sheet = NewFrame(info);
        if (codec.GetPixels(info, sheet.GetPixels()) is not (SKCodecResult.Success or SKCodecResult.IncompleteInput))
        {
            sheet.Dispose();
            throw new InvalidDataException($"Could not decode {Path.GetFileName(path)}.");
        }
        MaybeRemoveBackground(sheet, options);
        if (single)
        {
            frames.Add(sheet);
            return;
        }

        using (sheet)
        {
            for (int i = 0; i < total; i++)
            {
                // The cell's rows are copied straight out of the sheet. Drawing the cell
                // out through a canvas gives the same pixels, but to do it Skia first
                // takes a copy of the whole sheet, and does so again for every cell.
                var cell = NewFrame(InfoFor(cw, ch));
                byte* from = (byte*)sheet.GetPixels() + (long)(i / columns * ch) * sheet.RowBytes + (long)(i % columns * cw) * 4;
                byte* to = (byte*)cell.GetPixels();
                for (int y = 0; y < ch; y++)
                    Buffer.MemoryCopy(from + (long)y * sheet.RowBytes, to + (long)y * cell.RowBytes, cw * 4, cw * 4);
                frames.Add(cell);
            }
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

    /// <summary>The smallest box that holds everything drawn in any of the frames.</summary>
    static unsafe SKRectI ContentBounds(List<SKBitmap> frames)
    {
        int minX = int.MaxValue, minY = int.MaxValue, maxX = -1, maxY = -1;
        foreach (var bmp in frames)
        {
            // Each of these is a call into Skia, so they are read once, not once per pixel.
            int w = bmp.Width, h = bmp.Height, stride = bmp.RowBytes;
            byte* px = (byte*)bmp.GetPixels();
            for (int y = 0; y < h; y++)
            {
                // Only a pixel outside the box found so far can make it bigger, so a row is
                // searched inwards from each end and no further than the box. Once the
                // first frames have set the box, that leaves almost nothing to look at.
                byte* alpha = px + (long)y * stride + 3;
                int x = 0, stop = Math.Min(minX, w);
                while (x < stop && alpha[x * 4] <= 12) x++;
                bool found = x < stop;
                if (found) minX = x;
                x = w - 1;
                while (x > maxX && alpha[x * 4] <= 12) x--;
                if (x > maxX)
                {
                    maxX = x;
                    found = true;
                }

                // A row above or below the box makes it taller if anything at all is drawn
                // in it, and that may be somewhere the search above did not look.
                if (y >= minY && y <= maxY) continue;
                for (x = minX; !found && x <= maxX && x < w; x++) found = alpha[x * 4] > 12;
                if (!found) continue;
                if (y < minY) minY = y;
                if (y > maxY) maxY = y;
            }
        }
        return maxX < 0 ? SKRectI.Empty : new SKRectI(minX, minY, maxX + 1, maxY + 1);
    }

    static SpriteClip BuildClip(ClipSource src, List<SKBitmap> frames, List<double> durations, PackOptions options,
        double idleHeight, double idleShrink, out double shrink)
    {
        // Frames in one clip must share a size so they can share an anchor.
        int fw = frames.Max(f => f.Width), fh = frames.Max(f => f.Height);
        var bounds = ContentBounds(frames);
        if (bounds.IsEmpty) bounds = new SKRectI(0, 0, fw, fh);

        // Trim the empty margin, leaving a pixel of breathing room for smooth edges.
        var crop = new SKRectI(Math.Max(0, bounds.Left - 1), Math.Max(0, bounds.Top - 1),
            Math.Min(fw, bounds.Right + 1), Math.Min(fh, bounds.Bottom + 1));

        shrink = 1;
        int longest = Math.Max(crop.Width, crop.Height);
        if (!options.PixelArt && longest > MaxFrameSide) shrink = (double)MaxFrameSide / longest;
        int outW = Math.Max(1, (int)Math.Round(crop.Width * shrink)), outH = Math.Max(1, (int)Math.Round(crop.Height * shrink));

        var kept = new DecodedFrame[frames.Count];
        var sampling = new SKSamplingOptions(SKFilterMode.Linear, SKMipmapMode.Linear);
        for (int i = 0; i < frames.Count; i++)
        {
            // Nothing to resize, which is the usual case: the frame is kept just as it is,
            // and only the trimmed part of it is copied when it becomes a bitmap.
            var frame = frames[i];
            if (shrink == 1 && frame.Width >= crop.Right && frame.Height >= crop.Bottom)
            {
                kept[i] = new DecodedFrame(frame, crop.Left, crop.Top);
                continue;
            }

            var cell = NewFrame(InfoFor(outW, outH));
            // The frame is finished with after this, and saying so lets the image below
            // draw from it directly, where it would otherwise take a copy first.
            frame.SetImmutable();
            using (var canvas = new SKCanvas(cell))
            using (var image = SKImage.FromBitmap(frame))
            using (var paint = new SKPaint { BlendMode = SKBlendMode.Src })
            {
                var from = SKRect.Create(crop.Left, crop.Top, crop.Width, crop.Height);
                canvas.DrawImage(image, from, SKRect.Create(outW, outH), shrink < 1 ? sampling : SKSamplingOptions.Default, paint);
            }
            // The resized frame takes the place of the one it was made from, in the list
            // too, so that whoever tidies up after a failure finds it there.
            frame.Dispose();
            frames[i] = cell;
            kept[i] = new DecodedFrame(cell, 0, 0);
        }

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

        return new SpriteClip(kept, new PixelSize(outW, outH))
        {
            Ends = EndTimes(durations),
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
