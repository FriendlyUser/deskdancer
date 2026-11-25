using System.Diagnostics;

namespace DeskDancer.Engine;

/// <summary>Wall-clock beat counter shared by every mate so they stay in time with each other.</summary>
public sealed class BeatClock
{
    readonly Stopwatch _watch = Stopwatch.StartNew();
    double _baseBeat, _baseTime, _bpm = 120;

    /// <summary>Overrides the time source; used by the offline render tools.</summary>
    public Func<double>? TimeSource { get; set; }

    public double Seconds => TimeSource?.Invoke() ?? _watch.Elapsed.TotalSeconds;

    public double Bpm
    {
        get => _bpm;
        set
        {
            double now = Seconds;
            _baseBeat = BeatAt(now);
            _baseTime = now;
            _bpm = Math.Clamp(value, 40, 240);
        }
    }

    public double Beat => BeatAt(Seconds);

    double BeatAt(double now) => _baseBeat + (now - _baseTime) * _bpm / 60.0;
}

/// <summary>
/// A queue of moves being performed. One session can be shared by several mates,
/// which is how the dance party keeps everyone on the same step.
/// </summary>
public sealed class DanceSession
{
    readonly Func<DanceMove?> _next;

    DanceSession(double beat, DanceMove first, Func<DanceMove?> next)
    {
        Current = first;
        StartBeat = beat;
        _next = next;
    }

    public DanceMove Current { get; private set; }
    public double StartBeat { get; private set; }
    /// <summary>Suggested travel direction for the current move; flips after each travelling move.</summary>
    public int Dir { get; private set; } = 1;
    /// <summary>Increments every time the session moves on to a new move.</summary>
    public int Serial { get; private set; }
    public bool Finished { get; private set; }

    public static DanceSession? FromList(double beat, IEnumerable<DanceMove> moves)
    {
        var queue = new Queue<DanceMove>(moves);
        if (queue.Count == 0) return null;
        return new DanceSession(beat, queue.Dequeue(), () => queue.Count > 0 ? queue.Dequeue() : null);
    }

    public static DanceSession Endless(double beat, IReadOnlyList<DanceMove> pool, Random rng)
    {
        DanceMove last = pool[rng.Next(pool.Count)];
        return new DanceSession(beat, last, () =>
        {
            DanceMove pick;
            do pick = pool[rng.Next(pool.Count)];
            while (pool.Count > 1 && pick == last);
            return last = pick;
        });
    }

    /// <summary>Advances to whichever move should be playing at <paramref name="beat"/>. Safe to call repeatedly.</summary>
    public void Update(double beat)
    {
        while (!Finished && beat >= StartBeat + Current.Beats)
        {
            var next = _next();
            if (next == null) { Finished = true; break; }
            if (Current.Travels) Dir = -Dir;
            StartBeat += Current.Beats;
            Current = next;
            Serial++;
        }
    }

    public void Stop() => Finished = true;
}

/// <summary>Runs the non-stop dance party that every mate joins.</summary>
public sealed class Conductor(BeatClock clock)
{
    readonly Random _rng = new();

    public bool PartyOn { get; private set; }
    public DanceSession? Session { get; private set; }

    public void SetParty(bool on)
    {
        if (on == PartyOn) return;
        PartyOn = on;
        Session?.Stop();
        Session = on ? DanceSession.Endless(clock.Beat, Moves.All, _rng) : null;
    }
}
