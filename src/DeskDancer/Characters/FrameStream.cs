using Avalonia;
using Avalonia.Media.Imaging;
using Avalonia.Platform;
using SkiaSharp;

namespace DeskDancer.Characters;

/// <summary>
/// One animated file, read a frame at a time as it is shown and not all at once. A clip
/// that is played once through, such as an action, is shown from its first frame to its
/// last and then put away, so there is no call to have all of it unpacked: seventeen
/// seconds of a big picture drawn 25 times a second would be half a gigabyte, and read like
/// this they are a few frames' worth, with nothing to wait for before the first.
///
/// A frame of an animated file is often stored as the changes to an earlier one. So for
/// each place in the animation that is being shown, the frames a later one is still to be
/// built on are kept, and no others. Showing frames in order costs one frame's decoding
/// each time. Jumping somewhere else starts from the nearest frame that stands by itself.
/// Two mates showing the clip at different moments each get a place of their own.
///
/// Everything here but <see cref="CheckAll"/> happens on the UI thread, and a stream that
/// is being checked is not being shown.
/// </summary>
public sealed unsafe class FrameStream : IDisposable
{
    sealed class Place
    {
        /// <summary>The frame this place is at, or -1 before there is one.</summary>
        public int Index = -1;
        /// <summary>That frame, and the earlier ones a later frame is built on.</summary>
        public readonly Dictionary<int, SKBitmap> Composed = [];
        /// <summary>The frame as a picture the window can show, and the one before it, which may still be on its way to the screen.</summary>
        public Bitmap? Shown, Before;
        public long Used;
    }

    /// <summary>More places than this at once, and the one longest out of use is taken over.</summary>
    const int MostPlaces = 4;
    /// <summary>A place whose frame is no more than this far behind the one wanted is moved on to it.</summary>
    const int Near = 12;
    /// <summary>A place nobody has drawn from for this long, in milliseconds, is given up.</summary>
    const long PlaceLifetime = 3000;
    /// <summary>A file where showing frames in order would mean keeping more than this many at once is not read this way.</summary>
    public const int MostKept = 12;

    readonly SKData _data;
    readonly SKCodec _codec;
    readonly SKImageInfo _info;
    readonly int[] _builtOn, _lastBuiltOn;
    readonly Action<SKBitmap>? _finish;
    readonly Func<SKImageInfo, SKBitmap> _newFrame;
    readonly string _name;
    readonly List<Place> _places = [];
    readonly Stack<SKBitmap> _spare = new();
    readonly List<int> _chain = [];
    bool _failed;

    /// <param name="builtOn">For each frame, the earlier frame it is stored as changes to, or -1 if it stands by itself.</param>
    /// <param name="finish">Something to do to each frame before it is shown, such as taking its background out.</param>
    /// <param name="newFrame">Makes an empty bitmap to decode into.</param>
    public FrameStream(SKData data, SKCodec codec, SKImageInfo info, int[] builtOn, Action<SKBitmap>? finish,
        Func<SKImageInfo, SKBitmap> newFrame, string name)
    {
        _data = data;
        _codec = codec;
        _info = info;
        _builtOn = builtOn;
        _lastBuiltOn = LastBuiltOn(builtOn);
        _finish = finish;
        _newFrame = newFrame;
        _name = name;
    }

    public int Count => _builtOn.Length;
    public PixelSize Size => new(_info.Width, _info.Height);

    /// <summary>Memory in use right now, in bytes: the file, and the few frames that are unpacked.</summary>
    public long Bytes
    {
        get
        {
            int frames = _spare.Count;
            foreach (var place in _places)
                frames += place.Composed.Count + (place.Shown != null ? 1 : 0) + (place.Before != null ? 1 : 0);
            return _data.Size + frames * _info.BytesSize64;
        }
    }

    static int[] LastBuiltOn(int[] builtOn)
    {
        var last = new int[builtOn.Length];
        Array.Fill(last, -1);
        for (int i = 0; i < builtOn.Length; i++)
            if (builtOn[i] >= 0) last[builtOn[i]] = i;
        return last;
    }

    /// <summary>How many frames have to be kept at once to show every frame in order.</summary>
    public static int MostAtOnce(int[] builtOn)
    {
        var last = LastBuiltOn(builtOn);
        var kept = new HashSet<int>();
        int most = 0;
        for (int i = 0; i < builtOn.Length; i++)
        {
            kept.Add(i);
            kept.RemoveWhere(j => j != i && last[j] <= i);
            most = Math.Max(most, kept.Count);
        }
        return most;
    }

    /// <summary>The frame with this number, as a picture to draw. It stays good until the frame after next is asked for.</summary>
    public Bitmap FrameAt(int index)
    {
        index = Math.Clamp(index, 0, Count - 1);
        long now = Environment.TickCount64;
        Place? place = null;
        foreach (var p in _places)
        {
            if (p.Index == index && p.Shown != null)
            {
                p.Used = now;
                return p.Shown;
            }
            // Otherwise, the place with the least far to go to get there.
            if (p.Index < index && index - p.Index <= Near && (place == null || p.Index > place.Index)) place = p;
        }

        if (place == null)
        {
            for (int i = _places.Count - 1; i >= 0; i--)
                if (now - _places[i].Used > PlaceLifetime) GiveUp(_places[i]);
            if (_places.Count < MostPlaces)
            {
                _places.Add(place = new Place());
            }
            else
            {
                place = _places[0];
                foreach (var p in _places)
                    if (p.Used < place.Used) place = p;
            }
        }

        place.Used = now;
        try
        {
            if (!_failed)
            {
                Compose(place, index);
                var shown = ToBitmap(place.Composed[index]);
                place.Before?.Dispose();
                place.Before = place.Shown;
                place.Shown = shown;
            }
        }
        catch (Exception ex)
        {
            // The check that every clip gets when its pack is loaded finds a damaged file
            // before a mate comes to show it, as a rule. If one gets this far all the same,
            // the last good frame stays up.
            _failed = true;
            place.Index = -1;
            Log.Error($"Could not read frame {index + 1} of {_name}", ex);
        }
        return place.Shown ?? Blank(place);
    }

    Bitmap Blank(Place place)
    {
        foreach (var p in _places)
            if (p.Shown != null) return p.Shown;
        var empty = Take();
        new Span<byte>((void*)empty.GetPixels(), empty.ByteCount).Clear();
        place.Shown = ToBitmap(empty);
        _spare.Push(empty);
        return place.Shown;
    }

    /// <summary>Brings a place to a frame: decodes it, and first whatever it is built on that is not to hand.</summary>
    void Compose(Place place, int index)
    {
        // Back from the frame that is wanted to one that is to hand, or one that stands by itself.
        _chain.Clear();
        for (int i = index; i >= 0 && !place.Composed.ContainsKey(i); i = _builtOn[i]) _chain.Add(i);
        for (int k = _chain.Count - 1; k >= 0; k--)
        {
            int i = _chain[k], from = _builtOn[i];
            var frame = Take();
            SKCodecOptions options;
            if (from >= 0)
            {
                Buffer.MemoryCopy((void*)place.Composed[from].GetPixels(), (void*)frame.GetPixels(), frame.ByteCount, frame.ByteCount);
                options = new SKCodecOptions(i, from);
            }
            else
            {
                new Span<byte>((void*)frame.GetPixels(), frame.ByteCount).Clear();
                options = new SKCodecOptions(i);
            }
            var result = _codec.GetPixels(_info, frame.GetPixels(), options);
            if (result is not (SKCodecResult.Success or SKCodecResult.IncompleteInput))
            {
                _spare.Push(frame);
                throw new InvalidDataException($"Could not decode frame {i + 1} of {_name} ({result}).");
            }
            place.Composed[i] = frame;
        }
        place.Index = index;

        // What is kept: the frame itself, and the earlier ones a later frame is built on.
        _chain.Clear();
        foreach (int i in place.Composed.Keys)
            if (i > index || (i != index && _lastBuiltOn[i] <= index)) _chain.Add(i);
        foreach (int i in _chain)
        {
            _spare.Push(place.Composed[i]);
            place.Composed.Remove(i);
        }
        while (_spare.Count > 2) _spare.Pop().Dispose();
    }

    SKBitmap Take() => _spare.Count > 0 ? _spare.Pop() : _newFrame(_info);

    Bitmap ToBitmap(SKBitmap frame)
    {
        if (_finish == null) return Copy(frame);
        // What is done to a frame for showing must not be done to the one later frames are built on.
        var work = Take();
        Buffer.MemoryCopy((void*)frame.GetPixels(), (void*)work.GetPixels(), work.ByteCount, work.ByteCount);
        _finish(work);
        var bitmap = Copy(work);
        _spare.Push(work);
        return bitmap;
    }

    // The bitmap takes its own copy of the pixels.
    Bitmap Copy(SKBitmap frame) =>
        new(PixelFormat.Bgra8888, AlphaFormat.Premul, frame.GetPixels(), Size, new Vector(96, 96), frame.RowBytes);

    void GiveUp(Place place)
    {
        foreach (var frame in place.Composed.Values) frame.Dispose();
        place.Composed.Clear();
        place.Shown?.Dispose();
        place.Before?.Dispose();
        _places.Remove(place);
    }

    /// <summary>
    /// Decodes every frame once, in order, and keeps none: finds out whether the whole file
    /// can be read. Throws if it cannot.
    /// </summary>
    public void CheckAll()
    {
        var place = new Place();
        try
        {
            for (int i = 0; i < Count; i++) Compose(place, i);
        }
        finally
        {
            foreach (var frame in place.Composed.Values) frame.Dispose();
        }
    }

    public void Dispose()
    {
        while (_places.Count > 0) GiveUp(_places[^1]);
        while (_spare.Count > 0) _spare.Pop().Dispose();
        _codec.Dispose();
        _data.Dispose();
    }
}
