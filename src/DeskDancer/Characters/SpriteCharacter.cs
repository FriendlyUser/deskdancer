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
    // Uncompressed frames are where an image pack's memory goes, so a clip does not have to
    // hold on to its own. One that is given its frames keeps them for good. One that is given
    // a way to read them from disk instead fetches them on a background thread when it is
    // first wanted on screen, and can be told to let them go again. Only the reading happens
    // on that other thread; everything else here is called from the UI thread.
    readonly Func<Bitmap[]>? _read;
    volatile Bitmap[]? _frames;
    volatile bool _reading, _unreadable;
    long _lastWanted;

    public SpriteClip(Bitmap[]? frames, Func<Bitmap[]>? read = null)
    {
        if (frames == null && read == null) throw new ArgumentNullException(nameof(frames));
        _frames = frames;
        _read = read;
    }

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

    /// <summary>True while the frames are in memory.</summary>
    public bool InMemory => _frames != null;

    /// <summary>
    /// The frame to show at a time into the clip, or null if the frames are not in memory.
    /// Asking is what brings them in: the first null starts reading them in the background.
    /// </summary>
    public Bitmap? FrameAt(double time)
    {
        _lastWanted = Environment.TickCount64;

        // The flag is looked at before the frames: with no read under way, nothing but this
        // thread can change the frames, so finding none really does mean they are not there.
        bool reading = _reading;
        var frames = _frames;
        if (frames == null)
        {
            if (!reading && !_unreadable && _read != null)
            {
                _reading = true;
                Task.Run(Read);
            }
            return null;
        }

        if (frames.Length == 1) return frames[0];
        double t = Loop ? time % Duration : Math.Min(time, Duration - 1e-6);
        if (t < 0) t = 0;
        int i = Array.BinarySearch(Ends, t);
        i = i < 0 ? ~i : i + 1;
        return frames[Math.Min(i, frames.Length - 1)];
    }

    void Read()
    {
        try
        {
            _frames = _read!();
        }
        catch (Exception ex)
        {
            // The whole clip was decoded when the pack was loaded, so its files have changed
            // or gone since. It is not tried again; reloading the characters starts afresh.
            _unreadable = true;
            Log.Error($"Could not read the '{Name}' animation", ex);
        }
        finally
        {
            _reading = false;
            FreedMemory.Return();
        }
    }

    /// <summary>
    /// Lets the frames go if the clip has not been wanted on screen for this long and can
    /// read them again. Returns true if it did.
    /// </summary>
    public bool Unload(TimeSpan unwantedFor)
    {
        if (_read == null || _reading) return false;
        if (Environment.TickCount64 - _lastWanted < unwantedFor.TotalMilliseconds) return false;
        return Discard();
    }

    /// <summary>Lets the frames go whether or not they can be read again. Returns true if there were any.</summary>
    public bool Discard()
    {
        var frames = _frames;
        if (frames == null) return false;
        _frames = null;
        foreach (var frame in frames) frame.Dispose();
        return true;
    }
}

/// <summary>A character made from the user's own image files.</summary>
public sealed class SpriteCharacter : ICharacter
{
    // Which clip stands in when the requested one was not supplied.
    static readonly Dictionary<string, string[]> Fallbacks = new()
    {
        ["fall"] = ["drag"],
        ["drag"] = ["fall"],
        ["sleep"] = ["sit"],
    };

    readonly Dictionary<string, SpriteClip> _clips;
    readonly SpriteClip _idle;

    public SpriteCharacter(string id, string name, Dictionary<string, SpriteClip> clips, double height, int facing, bool pixelArt)
    {
        Id = id;
        DisplayName = name;
        _clips = clips;
        _idle = clips["idle"];
        PreferredHeight = height;
        NaturalFacing = facing;
        PixelArt = pixelArt;
        AspectRatio = Math.Clamp(_idle.ContentWidth / Math.Max(1, _idle.ContentHeight), 0.3, 2.5);
        DanceClips = clips
            .Where(c => c.Key.StartsWith("dance", StringComparison.Ordinal))
            .OrderBy(c => c.Key, StringComparer.Ordinal)
            .Select(c => new DanceClip(c.Key, c.Value.Name, c.Value.Duration))
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

    public bool HasClip(string clip) => _clips.ContainsKey(clip);

    /// <summary>True if the frames that would be drawn for this clip are in memory right now.</summary>
    public bool InMemory(string clip) => Resolve(clip).InMemory;

    /// <summary>
    /// Lets go of the frames of every clip that has not been drawn for at least this long and
    /// can be read from disk again. Returns true if any were let go.
    /// </summary>
    public bool ReleaseUnused(TimeSpan unusedFor)
    {
        bool any = false;
        foreach (var clip in _clips.Values) any |= clip.Unload(unusedFor);
        return any;
    }

    SpriteClip Resolve(string clip)
    {
        if (_clips.TryGetValue(clip, out var found)) return found;
        if (Fallbacks.TryGetValue(clip, out var alternatives))
            foreach (var alt in alternatives)
                if (_clips.TryGetValue(alt, out found)) return found;
        return _idle;
    }

    public void Draw(DrawingContext ctx, double height, in CharacterFrame frame)
    {
        var clip = Resolve(frame.Clip);
        var bitmap = clip.FrameAt(frame.ClipTime);
        if (bitmap == null)
        {
            // Still being read from disk. Idle is always in memory, so stand on that until then.
            clip = _idle;
            bitmap = clip.FrameAt(frame.ClipTime)!;
        }
        double s = height / _idle.ContentHeight * clip.Scale;
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
    const int MaxClipsAtOnce = 4;

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

    /// <summary>
    /// Loads a pack. With <paramref name="onDemand"/> only the idle clip's frames are kept: every
    /// other clip is still decoded once, to check it and to measure it, but its frames are read
    /// again when it is first drawn. Without it every frame is in memory when this returns.
    /// </summary>
    public static SpriteCharacter Load(string id, string dir, bool onDemand = false)
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

        // Decoded frames are full size and uncompressed, so no clip keeps its own for longer
        // than it takes to turn them into what the character holds: each is decoded, finished
        // and its decoded frames let go before the thread that did it takes on another.
        var order = sources.Values.ToArray();
        var built = new SpriteClip?[order.Length];
        var errors = new Exception?[order.Length];
        SpriteClip? idle = null;
        double idleHeight = 0, idleShrink = 1;

        // Idle is built first because every other clip is scaled relative to it. A pack
        // without one stands still on the first frame of whatever else it has.
        int first = Array.FindIndex(order, s => s.Key == "idle");
        bool hasIdle = first >= 0;
        if (!hasIdle) first = Math.Max(0, Array.FindIndex(order, s => KnownClips.Contains(s.Key)));

        SpriteClip Build(ClipSource src, List<SKBitmap> frames, List<double> durations)
        {
            string? readFrom = onDemand && src.Key != "idle" ? dir : null;
            var clip = BuildClip(src, frames, durations, options, idleHeight, idleShrink, out double shrink, readFrom);
            if (src.Key == "idle")
            {
                idle = clip;
                idleHeight = clip.ContentHeight;
                idleShrink = shrink;
            }
            return clip;
        }

        void LoadClip(int i, bool build)
        {
            var frames = new List<SKBitmap>();
            var durations = new List<double>();
            try
            {
                DecodeClip(dir, order[i], options, frames, durations);
                if (!build) return;
                if (i == first && !hasIdle) Build(new ClipSource { Key = "idle" }, [frames[0]], [1.0]);
                built[i] = Build(order[i], frames, durations);
            }
            catch (Exception ex)
            {
                errors[i] = ex;
            }
            finally
            {
                foreach (var bmp in frames) bmp.Dispose();
            }
        }

        LoadClip(first, build: true);

        // Decoding is most of the time a pack takes to load, and each clip is its own file or
        // folder, so the rest are done side by side: a few at once, so that however many
        // cores there are, the decoded frames of a whole pack are never in memory together.
        // If idle could not be built they are only decoded, to find out what else is wrong.
        bool measured = idle != null;
        Parallel.For(0, order.Length, new ParallelOptions { MaxDegreeOfParallelism = MaxClipsAtOnce }, i =>
        {
            if (i != first) LoadClip(i, build: measured);
        });

        // Errors are reported in the order the clips were found, so a broken pack reports
        // the same problem every time.
        if (errors.FirstOrDefault(e => e != null) is { } error)
        {
            // This pack will not be used, so its finished frames should not sit in memory
            // until the garbage collector happens to notice them.
            idle?.Discard();
            foreach (var clip in built) clip?.Discard();
            ExceptionDispatchInfo.Capture(error).Throw();
        }

        // Idle heads the list; the rest follow in the order they were found.
        var clips = new Dictionary<string, SpriteClip> { ["idle"] = idle! };
        for (int i = 0; i < order.Length; i++) clips.TryAdd(order[i].Key, built[i]!);

        string name = options.Name ?? Path.GetFileName(dir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
        return new SpriteCharacter(id, name, clips, options.Height, options.Facing, options.PixelArt);
    }

    static void DecodeClip(string dir, ClipSource src, PackOptions options, List<SKBitmap> frames, List<double> durations)
    {
        double fps = Math.Clamp(src.Fps ?? options.Fps, 0.5, 120);
        if (src.Folder != null)
        {
            string folder = Path.Combine(dir, src.Folder);
            if (!Directory.Exists(folder)) throw new InvalidDataException($"Folder not found: {src.Folder}");
            foreach (var file in Directory.EnumerateFiles(folder).Where(IsImage).OrderBy(f => f, NaturalOrder.Instance))
                DecodeFile(file, 1, 1, 0, fps, options, frames, durations);
        }
        else
        {
            string file = Path.Combine(dir, src.File!);
            if (!File.Exists(file)) throw new InvalidDataException($"File not found: {src.File}");
            DecodeFile(file, src.Columns, src.Rows, src.Count, fps, options, frames, durations);
        }
        if (frames.Count == 0) throw new InvalidDataException($"Clip '{src.Key}' has no frames.");
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

    static unsafe void DecodeFile(string path, int columns, int rows, int count, double fps, PackOptions options,
        List<SKBitmap> frames, List<double> durations)
    {
        // The file is read into memory and the decoder is made from that, never straight from
        // the file. Made from a file, the decoder is handed a stream, and for WebP Skia frees
        // that stream at once while SkiaSharp still counts it as its own. If another thread
        // opens a file at that moment and is given the same address, SkiaSharp tidies the first
        // stream away by freeing the second, which the other thread is about to use. With clips
        // decoded side by side, that crashed the app about one start in thirty on macOS.
        using var data = SKData.CreateCopy(File.ReadAllBytes(path));
        using var codec = SKCodec.Create(data)
                          ?? throw new InvalidDataException($"Could not read {Path.GetFileName(path)}: it is not an image this program can decode.");
        var info = InfoFor(codec.Info.Width, codec.Info.Height);
        if (info.Width <= 0 || info.Height <= 0 || (long)info.Width * info.Height > 64_000_000)
            throw new InvalidDataException($"{Path.GetFileName(path)} is too large.");

        int animated = codec.FrameCount;
        if (animated > 1)
        {
            // Animated GIF / WebP. Later frames are often stored as changes to an earlier one,
            // so every composed frame is kept until the whole file has been read.
            var frameInfo = codec.FrameInfo;
            int n = Math.Min(animated, MaxFramesPerClip);
            var composed = new SKBitmap[n];
            for (int i = 0; i < n; i++)
            {
                var bmp = new SKBitmap(info);
                int required = frameInfo[i].RequiredFrame;
                SKCodecOptions opts;
                if (required >= 0 && required < i)
                {
                    Buffer.MemoryCopy((void*)composed[required].GetPixels(), (void*)bmp.GetPixels(), bmp.ByteCount, bmp.ByteCount);
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
                    foreach (var c in composed) c?.Dispose();
                    throw new InvalidDataException($"Could not decode frame {i + 1} of {Path.GetFileName(path)} ({result}).");
                }
                composed[i] = bmp;
            }
            for (int i = 0; i < n; i++)
            {
                int ms = frameInfo[i].Duration;
                MaybeRemoveBackground(composed[i], options);
                frames.Add(composed[i]);
                durations.Add(ms <= 10 ? 0.1 : ms / 1000.0);
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
            int total = Math.Min(count > 0 ? Math.Min(count, columns * rows) : columns * rows, MaxFramesPerClip);
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
                byte* row = px + y * stride;
                for (int x = 0; x < w; x++)
                {
                    if (row[x * 4 + 3] <= 12) continue;
                    if (x < minX) minX = x;
                    if (x > maxX) maxX = x;
                    if (y < minY) minY = y;
                    if (y > maxY) maxY = y;
                }
            }
        }
        return maxX < 0 ? SKRectI.Empty : new SKRectI(minX, minY, maxX + 1, maxY + 1);
    }

    /// <summary>
    /// Works out how a clip's decoded frames are trimmed, scaled and anchored. The clip keeps the
    /// finished frames, unless <paramref name="readFrom"/> names the pack folder: then it keeps
    /// none and decodes its files again whenever it needs them.
    /// </summary>
    static SpriteClip BuildClip(ClipSource src, List<SKBitmap> frames, List<double> durations, PackOptions options,
        double idleHeight, double idleShrink, out double shrink, string? readFrom = null)
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

        int count = frames.Count;
        var ends = new double[count];
        double t = 0;
        for (int i = 0; i < count; i++)
        {
            t += Math.Max(durations[i], 1.0 / 240);
            ends[i] = t;
        }

        // Cutting the frames out is the same job whether it is done now or when the clip is
        // read again later, and both must give the same pictures.
        double scaled = shrink;
        Bitmap[] Cut(List<SKBitmap> decoded) => CutFrames(decoded, crop, scaled, outW, outH);
        Bitmap[] ReadAgain()
        {
            var decoded = new List<SKBitmap>();
            try
            {
                DecodeClip(readFrom!, src, options, decoded, []);
                if (decoded.Count != count)
                    throw new InvalidDataException($"Clip '{src.Key}' had {count} frames when it was loaded and has {decoded.Count} now.");
                return Cut(decoded);
            }
            finally
            {
                foreach (var bmp in decoded) bmp.Dispose();
            }
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

        bool keep = readFrom == null;
        return new SpriteClip(keep ? Cut(frames) : null, keep ? null : ReadAgain)
        {
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

    static unsafe Bitmap[] CutFrames(List<SKBitmap> frames, SKRectI crop, double shrink, int outW, int outH)
    {
        var bitmaps = new Bitmap[frames.Count];
        var sampling = new SKSamplingOptions(SKFilterMode.Linear, SKMipmapMode.Linear);
        byte[]? rows = null;
        try
        {
            for (int i = 0; i < frames.Count; i++)
            {
                // Nothing to resize, which is the usual case: copy the trimmed rows straight
                // across. Drawing them through a canvas gives the same pixels far more slowly.
                var frame = frames[i];
                if (shrink == 1 && frame.Width >= crop.Right && frame.Height >= crop.Bottom)
                {
                    int rowBytes = outW * 4;
                    rows ??= new byte[rowBytes * outH];
                    fixed (byte* to = rows)
                    {
                        byte* from = (byte*)frame.GetPixels() + crop.Top * frame.RowBytes + crop.Left * 4;
                        for (int y = 0; y < outH; y++)
                            Buffer.MemoryCopy(from + (long)y * frame.RowBytes, to + (long)y * rowBytes, rowBytes, rowBytes);
                        bitmaps[i] = new Bitmap(PixelFormat.Bgra8888, AlphaFormat.Premul, (nint)to,
                            new PixelSize(outW, outH), new Vector(96, 96), rowBytes);
                    }
                    continue;
                }

                using var cell = new SKBitmap(InfoFor(outW, outH));
                cell.Erase(SKColors.Transparent);
                using (var canvas = new SKCanvas(cell))
                using (var image = SKImage.FromBitmap(frames[i]))
                using (var paint = new SKPaint { BlendMode = SKBlendMode.Src })
                {
                    var from = SKRect.Create(crop.Left, crop.Top, crop.Width, crop.Height);
                    canvas.DrawImage(image, from, SKRect.Create(outW, outH), shrink < 1 ? sampling : SKSamplingOptions.Default, paint);
                }
                bitmaps[i] = new Bitmap(PixelFormat.Bgra8888, AlphaFormat.Premul, cell.GetPixels(),
                    new PixelSize(outW, outH), new Vector(96, 96), cell.RowBytes);
            }
        }
        catch
        {
            foreach (var bitmap in bitmaps) bitmap?.Dispose();
            throw;
        }
        return bitmaps;
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
