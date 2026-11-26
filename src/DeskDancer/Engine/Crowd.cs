namespace DeskDancer.Engine;

/// <summary>
/// The mates that share a desktop. Each mate's brain looks here for the others: to bump
/// into them, and to meet them. A mate with no crowd, or alone in one, behaves as it
/// always has.
/// </summary>
public sealed class Crowd(BeatClock clock, Conductor conductor)
{
    readonly List<MateBrain> _mates = [];
    readonly Random _rng = new();

    public IReadOnlyList<MateBrain> Mates => _mates;

    public void Add(MateBrain mate)
    {
        if (_mates.Contains(mate)) return;
        _mates.Add(mate);
        mate.Crowd = this;
    }

    public void Remove(MateBrain mate)
    {
        if (!_mates.Remove(mate)) return;
        mate.LeaveGathering(rest: false);
        mate.Crowd = null;
    }

    /// <summary>Where a mate comes in the crowd. Settles which of two mates on the very same spot steps which way.</summary>
    public int IndexOf(MateBrain mate) => _mates.IndexOf(mate);

    /// <summary>
    /// Two mates have met. If the second is already at a get-together that is still going,
    /// the first joins it. Otherwise they start one: a short routine of moves done on the
    /// spot, which begins on a beat a moment from now, once they have said hello.
    /// </summary>
    public Gathering Gather(MateBrain one, MateBrain other)
    {
        if (other.Gathering is { } going && !going.Over(clock.Beat))
        {
            going.Add(one);
            return going;
        }

        // On the spot, so that nobody dances off through anybody else. Should every such
        // move be switched off, whatever is left has to do.
        var pool = conductor.Pool();
        var still = pool.Where(m => !m.Travels).ToList();
        if (still.Count == 0) still = [.. pool];
        var routine = new List<DanceMove>();
        for (int i = 0; i < Gathering.Moves; i++)
        {
            DanceMove pick;
            do pick = still[_rng.Next(still.Count)];
            while (still.Count > 1 && routine.Count > 0 && pick == routine[^1]);
            routine.Add(pick);
        }

        double start = Math.Ceiling(clock.Beat + Gathering.HelloSeconds * clock.Bpm / 60);
        var gathering = new Gathering(DanceSession.FromList(start, routine)!, start, start + routine.Sum(m => m.Beats));
        gathering.Add(one);
        gathering.Add(other);
        return gathering;
    }
}

/// <summary>
/// Mates who have met and are dancing together: the one routine they all dance, in step,
/// and who is there. It is over when the routine is.
/// </summary>
public sealed class Gathering(DanceSession session, double startBeat, double endBeat)
{
    /// <summary>How many moves a get-together dances.</summary>
    public const int Moves = 5;
    /// <summary>How long they have to say hello before the dancing starts, at the least.</summary>
    public const double HelloSeconds = 1.1;

    readonly List<MateBrain> _members = [];

    public DanceSession Session => session;
    /// <summary>The beat the dancing starts on.</summary>
    public double StartBeat => startBeat;
    public IReadOnlyList<MateBrain> Members => _members;

    public bool Over(double beat) => session.Finished || beat >= endBeat;

    internal void Add(MateBrain mate)
    {
        if (_members.Contains(mate)) return;
        _members.Add(mate);
        mate.JoinGathering(this, _members.Count - 1);
    }

    internal void Remove(MateBrain mate) => _members.Remove(mate);
}
