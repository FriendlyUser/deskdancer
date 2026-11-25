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

/// <summary>An animation clip made by the artist that can be offered as a dance.</summary>
public readonly record struct DanceClip(string Id, string Name, double Seconds);

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
    IReadOnlyList<DanceClip> DanceClips { get; }
    bool HasClip(string clip);
    void Draw(DrawingContext ctx, double height, in CharacterFrame frame);
}
