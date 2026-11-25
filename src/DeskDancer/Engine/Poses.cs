namespace DeskDancer.Engine;

/// <summary>
/// Whole-body transform applied to any character, sprite or rig. Distances are in
/// character heights so the same move works at every size.
/// </summary>
public struct BodyPose
{
    /// <summary>Sideways offset from where the move started.</summary>
    public double X;
    /// <summary>Height above the floor.</summary>
    public double Y;
    /// <summary>Rotation about the feet in degrees; positive tips the head to the right.</summary>
    public double Lean;
    /// <summary>Rotation about the body centre in degrees (flips, cartwheels).</summary>
    public double Spin;
    /// <summary>Fake 3D rotation about the vertical axis in degrees (twirls).</summary>
    public double Turn;
    public double ScaleX, ScaleY;
    /// <summary>Horizontal shear; positive pushes the head to the right.</summary>
    public double Skew;
    /// <summary>+1 right, -1 left, 0 leaves the current facing alone.</summary>
    public int Facing;

    public static BodyPose Identity => new() { ScaleX = 1, ScaleY = 1 };

    /// <summary>Positive values squash (shorter and wider), negative values stretch.</summary>
    public void Squash(double amount)
    {
        ScaleY *= 1 - amount;
        ScaleX *= 1 + amount * 0.7;
    }

    /// <summary>The pose with travel removed and full rotations unwound, used as a blend source.</summary>
    public readonly BodyPose Settled()
    {
        var p = this;
        p.X = 0;
        p.Spin = Ease.WrapDegrees(Spin);
        p.Turn = Ease.WrapDegrees(Turn);
        return p;
    }

    public static BodyPose Lerp(in BodyPose a, in BodyPose b, double t) => new()
    {
        X = Ease.Lerp(a.X, b.X, t),
        Y = Ease.Lerp(a.Y, b.Y, t),
        Lean = Ease.Lerp(a.Lean, b.Lean, t),
        Spin = Ease.Lerp(a.Spin, b.Spin, t),
        Turn = Ease.Lerp(a.Turn, b.Turn, t),
        ScaleX = Ease.Lerp(a.ScaleX, b.ScaleX, t),
        ScaleY = Ease.Lerp(a.ScaleY, b.ScaleY, t),
        Skew = Ease.Lerp(a.Skew, b.Skew, t),
        Facing = b.Facing != 0 ? b.Facing : a.Facing,
    };
}

public enum Face { Normal, Happy, Wide, Sleepy, Dizzy, Wink, Cool, Love }

/// <summary>
/// Limb angles for rigged characters. Sprite characters ignore this and only use
/// <see cref="BodyPose"/>. Angles are in degrees.
/// </summary>
public struct LimbPose
{
    /// <summary>Shoulder angle: 0 hangs straight down, 90 points out sideways, 180 points up.</summary>
    public double ArmL, ArmR;
    /// <summary>Elbow bend added to the shoulder angle; negative folds the forearm in towards the chest.</summary>
    public double ElbowL, ElbowR;
    /// <summary>Hip angle, positive swings the leg outwards.</summary>
    public double LegL, LegR;
    /// <summary>0..1, how far the foot is pulled up.</summary>
    public double LiftL, LiftR;
    /// <summary>0..1, lowers the hips (1 = sitting on the floor).</summary>
    public double Crouch;
    public double HeadTilt;
    /// <summary>Vertical head offset in character heights.</summary>
    public double HeadBob;
    /// <summary>-1..1 gaze direction.</summary>
    public double LookX, LookY;
    /// <summary>0 = eyes shut, 1 = open.</summary>
    public double EyeOpen;
    public Face Face;

    public static LimbPose Rest => new()
    {
        ArmL = 12, ArmR = 12, ElbowL = 10, ElbowR = 10, LegL = 3, LegR = 3, EyeOpen = 1,
    };

    public static LimbPose Lerp(in LimbPose a, in LimbPose b, double t) => new()
    {
        ArmL = Ease.Lerp(a.ArmL, b.ArmL, t),
        ArmR = Ease.Lerp(a.ArmR, b.ArmR, t),
        ElbowL = Ease.Lerp(a.ElbowL, b.ElbowL, t),
        ElbowR = Ease.Lerp(a.ElbowR, b.ElbowR, t),
        LegL = Ease.Lerp(a.LegL, b.LegL, t),
        LegR = Ease.Lerp(a.LegR, b.LegR, t),
        LiftL = Ease.Lerp(a.LiftL, b.LiftL, t),
        LiftR = Ease.Lerp(a.LiftR, b.LiftR, t),
        Crouch = Ease.Lerp(a.Crouch, b.Crouch, t),
        HeadTilt = Ease.Lerp(a.HeadTilt, b.HeadTilt, t),
        HeadBob = Ease.Lerp(a.HeadBob, b.HeadBob, t),
        LookX = Ease.Lerp(a.LookX, b.LookX, t),
        LookY = Ease.Lerp(a.LookY, b.LookY, t),
        EyeOpen = Ease.Lerp(a.EyeOpen, b.EyeOpen, t),
        Face = t < 0.5 ? a.Face : b.Face,
    };
}

/// <summary>One evaluated instant of a move: the body transform plus the limb angles.</summary>
public struct MoveFrame
{
    public BodyPose Body;
    public LimbPose Limbs;

    public static MoveFrame Neutral => new() { Body = BodyPose.Identity, Limbs = LimbPose.Rest };

    public static MoveFrame Lerp(in MoveFrame a, in MoveFrame b, double t) => new()
    {
        Body = BodyPose.Lerp(a.Body, b.Body, t),
        Limbs = LimbPose.Lerp(a.Limbs, b.Limbs, t),
    };
}
