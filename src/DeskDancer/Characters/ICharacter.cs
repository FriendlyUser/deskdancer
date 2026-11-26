using Avalonia.Media;
using DeskDancer.Engine;

namespace DeskDancer.Characters;

/// <summary>Everything a character needs to know to draw one frame.</summary>
public readonly struct CharacterFrame
{
    /// <summary>Animation clip requested by the behaviour engine ("idle", "walk", "dance_xyz"...).</summary>
    public string Clip { get; init; }
    /// <summary>Seconds since that clip started.</summary>
    public double ClipTime { get; init; }
    public LimbPose Limbs { get; init; }
    /// <summary>Seconds since the mate was created; drives ambient animation.</summary>
    public double Time { get; init; }
    public double Beat { get; init; }
    /// <summary>0 at rest, 1 while dancing.</summary>
    public double Energy { get; init; }
    /// <summary>Degrees that loose parts (cables, drawstrings) trail behind the body.</summary>
    public double Trail { get; init; }
}

/// <summary>
/// One of a character's own animations, made by the artist, that is offered as a dance or as
/// an action. <paramref name="Seconds"/> is how long it runs once through, and
/// <paramref name="Travel"/>, for an action that takes the mate somewhere, is where.
/// </summary>
public readonly record struct OwnClip(string Id, string Name, double Seconds, ClipTravel? Travel = null);

/// <summary>Whether a clip's pictures are there to be shown.</summary>
public enum ClipReadiness
{
    /// <summary>They are being read, and something else stands in for them meanwhile.</summary>
    Coming,
    /// <summary>They are in memory.</summary>
    Ready,
    /// <summary>They could not be read, and never will be.</summary>
    Lost,
}

/// <summary>
/// Where an action takes the mate while it plays: how far it has got at given times, in
/// character heights, with straight lines between. Distances are as the art is drawn,
/// positive to the right of the picture; shown the other way round, the mate goes the
/// other way. The pictures themselves stay centred on the mate, so a clip of someone running
/// off shows them running on the spot, and this is what moves them.
/// </summary>
public sealed class ClipTravel
{
    readonly double[] _seconds, _heights;

    /// <param name="keys">Times in seconds and how far the mate has got by each. It starts at 0 at time 0.</param>
    public ClipTravel(IEnumerable<(double Seconds, double Heights)> keys)
    {
        var sorted = keys.Where(k => double.IsFinite(k.Seconds) && double.IsFinite(k.Heights) && k.Seconds >= 0)
            .OrderBy(k => k.Seconds).ToList();
        if (sorted.Count == 0 || sorted[0].Seconds > 0) sorted.Insert(0, (0, 0));
        _seconds = sorted.Select(k => k.Seconds).ToArray();
        _heights = sorted.Select(k => Math.Clamp(k.Heights, -MaxHeights, MaxHeights)).ToArray();
        Min = Math.Min(0, _heights.Min());
        Max = Math.Max(0, _heights.Max());
    }

    /// <summary>No action takes the mate further than this from where it started, in heights.</summary>
    public const double MaxHeights = 20;

    /// <summary>The furthest it gets to the left and to the right of where it started, as drawn.</summary>
    public double Min { get; }
    public double Max { get; }
    /// <summary>Where it ends up.</summary>
    public double End => _heights[^1];

    /// <summary>How far the mate has got, in heights, this long into the action.</summary>
    public double At(double seconds)
    {
        int next = Array.BinarySearch(_seconds, seconds);
        if (next >= 0) return _heights[next];
        next = ~next;
        if (next == 0) return _heights[0];
        if (next == _seconds.Length) return _heights[^1];
        double span = _seconds[next] - _seconds[next - 1];
        return _heights[next - 1] + (_heights[next] - _heights[next - 1]) * (seconds - _seconds[next - 1]) / span;
    }
}

/// <summary>
/// A drawable character. <see cref="Draw"/> works in a local space whose origin is the
/// point between the feet, with y pointing down the screen and <c>height</c> the body height.
/// </summary>
public interface ICharacter
{
    string Id { get; }
    string DisplayName { get; }
    /// <summary>Resting width divided by height.</summary>
    double AspectRatio { get; }
    /// <summary>Height in device-independent pixels at 100% size.</summary>
    double PreferredHeight { get; }
    /// <summary>True when the character has limbs driven by <see cref="LimbPose"/>.</summary>
    bool IsRigged { get; }
    /// <summary>True for art that should be scaled without smoothing.</summary>
    bool PixelArt { get; }
    /// <summary>+1 when the art faces right, -1 when it faces left; decides when to mirror it.</summary>
    int NaturalFacing { get; }
    /// <summary>Clips whose names start with "dance": danced to the beat, with notes, for as long as a move lasts.</summary>
    IReadOnlyList<OwnClip> DanceClips { get; }
    /// <summary>
    /// Clips whose names start with "action": things the mate does, such as having a drink.
    /// Each is played once through at its own speed, with no beat, notes or dance floor.
    /// </summary>
    IReadOnlyList<OwnClip> ActionClips { get; }
    bool HasClip(string clip);
    /// <summary>
    /// Whether a clip's pictures can be shown this instant. Asking sets a character that
    /// fetches its pictures when they are wanted going on them, as <see cref="Prepare"/> does.
    /// </summary>
    ClipReadiness Readiness(string clip);
    /// <summary>
    /// Says a clip is about to be shown. A character that only fetches its pictures when
    /// they are wanted can start on them now, ahead of the first frame that needs them.
    /// </summary>
    void Prepare(string clip);
    void Draw(DrawingContext ctx, double height, in CharacterFrame frame);
}
