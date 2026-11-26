using static DeskDancer.Engine.Ease;

namespace DeskDancer.Engine;

/// <summary>Visual effects a move can fire at a given beat.</summary>
public enum Fx { Sparkle, Confetti, Stomp, Hearts }

/// <summary>
/// A dance move: a pure function from "beats since the move started" to a pose.
/// Moves are written against the beat, so they follow whatever tempo is set.
/// </summary>
public sealed class DanceMove
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required double Beats { get; init; }

    /// <summary>True when the move ends somewhere other than where it started.</summary>
    public bool Travels { get; init; }

    /// <summary>Sprite clip to show while the move plays; null uses the idle clip.</summary>
    public string? Clip { get; init; }

    public (double Beat, Fx Kind)[] Effects { get; init; } = [];

    /// <summary>(beats since start, travel direction ±1) → pose.</summary>
    public required Func<double, int, MoveFrame> Eval { get; init; }

    /// <summary>Sideways distance covered by the whole move, in character heights.</summary>
    public double NetTravel(int dir) => Eval(Beats, dir).Body.X;
}

/// <summary>The built-in choreography library.</summary>
public static class Moves
{
    static MoveFrame Happy()
    {
        var f = MoveFrame.Neutral;
        f.Limbs.Face = Face.Happy;
        return f;
    }

    static void Arms(ref MoveFrame f, double armL, double elbowL, double armR, double elbowR)
    {
        f.Limbs.ArmL = armL; f.Limbs.ElbowL = elbowL;
        f.Limbs.ArmR = armR; f.Limbs.ElbowR = elbowR;
    }

    // Bounce on every beat with a landing squash and pumping arms.
    public static readonly DanceMove Bounce = new()
    {
        Id = "bounce", Name = "Bounce", Beats = 4,
        Eval = (t, dir) =>
        {
            var f = Happy();
            double b = Frac(t), s = Sin(t);
            f.Body.Y = 0.11 * Arc(b);
            f.Body.Squash(0.13 * Decay(b, 9) - 0.05 * Arc(b));
            f.Body.Lean = 5 * Sin(t / 2);
            Arms(ref f, 60 + 35 * s, 75, 60 - 35 * s, 75);
            f.Limbs.LiftL = 0.5 * Math.Max(0, s);
            f.Limbs.LiftR = 0.5 * Math.Max(0, -s);
            f.Limbs.HeadTilt = 6 * Sin(t / 2);
            return f;
        },
    };

    // Hands in the air, swaying side to side.
    public static readonly DanceMove Sway = new()
    {
        Id = "sway", Name = "Sway", Beats = 4,
        Eval = (t, dir) =>
        {
            var f = Happy();
            double s = Sin(t / 2);
            f.Body.Lean = 11 * s;
            f.Body.Skew = -0.05 * s;
            f.Body.X = 0.06 * s;
            f.Body.Squash(0.03 * Cos(t));
            Arms(ref f, 155 + 20 * s, 12, 155 - 20 * s, 12);
            f.Limbs.HeadTilt = 9 * s;
            return f;
        },
    };

    static readonly int[] StepDirs = [1, 1, -1, -1, -1, -1, 1, 1];

    // Two steps one way, four back, two home, with a clap on each landing.
    public static readonly DanceMove SideStep = new()
    {
        Id = "sidestep", Name = "Side Step", Beats = 8,
        Eval = (t, dir) =>
        {
            var f = Happy();
            int i = Math.Clamp((int)Math.Floor(t), 0, 7);
            double b = t - i;
            double x = 0;
            for (int k = 0; k < i; k++) x += StepDirs[k];
            x += StepDirs[i] * InOut(Span(b, 0, 0.55));
            double hop = Arc(Span(b, 0, 0.55));
            int d = dir * StepDirs[i];

            f.Body.X = dir * 0.2 * x;
            f.Body.Y = 0.07 * hop;
            f.Body.Lean = d * 7 * hop;
            f.Body.Squash(b > 0.55 ? 0.09 * Decay(b - 0.55, 10) : -0.03 * hop);

            if (d > 0) { f.Limbs.LegR = 3 + 24 * hop; f.Limbs.LiftR = 0.3 * hop; }
            else { f.Limbs.LegL = 3 + 24 * hop; f.Limbs.LiftL = 0.3 * hop; }

            double clap = Arc(Span(b, 0.5, 0.95));
            Arms(ref f, Lerp(55, 30, clap), Lerp(40, -150, clap), Lerp(55, 30, clap), Lerp(40, -150, clap));
            f.Limbs.HeadTilt = d * 5 * hop;
            return f;
        },
    };

    // Wind up, spin twice in the air, land in a ta-da pose.
    public static readonly DanceMove Twirl = new()
    {
        Id = "twirl", Name = "Twirl", Beats = 4,
        Effects = [(1.0, Fx.Sparkle), (3.0, Fx.Stomp)],
        Eval = (t, dir) =>
        {
            var f = Happy();
            if (t < 1)
            {
                double a = Arc(t), c = InOut(t);
                f.Body.Squash(0.14 * a);
                f.Body.Lean = -6 * dir * a;
                Arms(ref f, Lerp(12, 80, c), 10, Lerp(12, 80, c), 10);
            }
            else if (t < 3)
            {
                double u = (t - 1) / 2;
                double up = Lerp(80, 168, InOut(Span(u, 0, 0.3)));
                f.Body.Turn = dir * 720 * InOut(u);
                f.Body.Y = 0.16 * Arc(u);
                f.Body.Squash(-0.07 * Arc(u));
                Arms(ref f, up, 10, up, 10);
            }
            else
            {
                double v = t - 3;
                double k = OutBack(Span(v, 0, 0.3));
                f.Body.Squash(0.16 * Decay(v, 6) * Math.Cos(v * 11));
                Arms(ref f, Lerp(168, 38, k), Lerp(10, -115, k), Lerp(168, 160, k), 10);
                f.Limbs.HeadTilt = 8 * k;
                f.Limbs.Face = Face.Wink;
            }
            return f;
        },
    };

    // Glide backwards while facing the other way, then spin and point.
    public static readonly DanceMove Moonwalk = new()
    {
        Id = "moonwalk", Name = "Moonwalk", Beats = 8, Travels = true,
        Effects = [(7.1, Fx.Sparkle)],
        Eval = (t, dir) =>
        {
            var f = MoveFrame.Neutral;
            f.Limbs.Face = Face.Cool;
            double g = Math.Min(t, 6);
            f.Body.X = dir * 0.24 * (g - 0.14 * Math.Sin(g * Tau));
            f.Body.Facing = -dir;
            if (t < 6)
            {
                double s = Sin(t);
                f.Body.Lean = -dir * 7;
                f.Body.Squash(0.025 * Sin(t * 2));
                f.Limbs.LegL = 4 + 12 * Math.Max(0, s); f.Limbs.LiftL = 0.35 * Math.Max(0, s);
                f.Limbs.LegR = 4 + 12 * Math.Max(0, -s); f.Limbs.LiftR = 0.35 * Math.Max(0, -s);
                Arms(ref f, 22 + 14 * s, 25, 22 - 14 * s, 25);
                f.Limbs.HeadTilt = -dir * 4;
            }
            else
            {
                double u = (t - 6) / 2;
                double k = OutBack(Span(u, 0.55, 0.75));
                f.Body.Turn = 360 * InOut(Span(u, 0, 0.55));
                f.Body.Y = 0.08 * Arc(Span(u, 0, 0.55));
                f.Body.Lean = Lerp(-dir * 7, dir * 8, k);
                f.Body.Squash(-0.05 * k);
                Arms(ref f, Lerp(22, 32, k), Lerp(25, -112, k), Lerp(22, 162, k), Lerp(25, 0, k));
                f.Limbs.HeadTilt = dir * 6 * k;
            }
            return f;
        },
    };

    // Crouch, full backwards somersault, stick the landing.
    public static readonly DanceMove Backflip = new()
    {
        Id = "backflip", Name = "Backflip", Beats = 4,
        Effects = [(2.5, Fx.Confetti), (2.5, Fx.Stomp)],
        Eval = (t, dir) =>
        {
            var f = MoveFrame.Neutral;
            if (t < 1)
            {
                double a = InOut(t);
                f.Body.Squash(0.24 * a);
                Arms(ref f, Lerp(12, 35, a), Lerp(10, -30, a), Lerp(12, 35, a), Lerp(10, -30, a));
                f.Limbs.Crouch = 0.35 * a;
                f.Limbs.Face = Face.Wide;
            }
            else if (t < 2.5)
            {
                double u = (t - 1) / 1.5;
                double launch = Lerp(0.24, -0.12, InOut(Span(u, 0, 0.15)));
                double tuck = 0.08 * Arc(u);
                double up = Lerp(35, 170, InOut(Span(u, 0, 0.2)));
                f.Body.Y = 0.6 * 4 * u * (1 - u);
                f.Body.Spin = -dir * 360 * InOut(u);
                f.Body.Squash(Lerp(launch, tuck, InOut(Span(u, 0.15, 0.5))));
                Arms(ref f, up, 10, up, 10);
                f.Limbs.Crouch = 0.35 * (1 - Span(u, 0, 0.15));
                f.Limbs.LiftL = f.Limbs.LiftR = 0.6 * Arc(u);
                f.Limbs.Face = Face.Wide;
            }
            else if (t < 3.2)
            {
                double v = (t - 2.5) / 0.7;
                f.Body.Squash(0.26 * Decay(v, 3.5) * Math.Cos(v * 8) * InOut(Span(v, 0, 0.1)));
                Arms(ref f, Lerp(170, 150, v), 10, Lerp(170, 150, v), 10);
                f.Limbs.Crouch = 0.3 * Decay(v, 4) * InOut(Span(v, 0, 0.1));
                f.Limbs.Face = Face.Happy;
            }
            else
            {
                double w = (t - 3.2) / 0.8;
                f.Body.Y = 0.06 * Arc(w);
                Arms(ref f, 150, 10, 150, 10);
                f.Limbs.Face = Face.Happy;
            }
            return f;
        },
    };

    // Fast shimmy with noodle arms.
    public static readonly DanceMove Wiggle = new()
    {
        Id = "wiggle", Name = "Wiggle", Beats = 4,
        Eval = (t, dir) =>
        {
            var f = Happy();
            double w = Sin(t * 2);
            f.Body.Skew = 0.16 * w;
            f.Body.ScaleX *= 1 + 0.035 * Cos(t * 2);
            f.Body.Lean = 4 * Sin(t);
            f.Body.Y = 0.02 * Math.Abs(w);
            Arms(ref f,
                95 + 35 * Sin(t * 2), 45 * Math.Sin(t * 2 * Tau - 1.2),
                95 + 35 * Sin(t * 2 + 0.5), 45 * Math.Sin(t * 2 * Tau + Math.PI - 1.2));
            f.Limbs.HeadTilt = 7 * Math.Sin(t * 2 * Tau + 0.6);
            return f;
        },
    };

    static MoveFrame Key(double lean, double squash, double armL, double elbowL, double armR, double elbowR,
        double head, Face face = Face.Cool, double skew = 0, double crouch = 0)
    {
        var f = MoveFrame.Neutral;
        f.Body.Lean = lean;
        f.Body.Skew = skew;
        f.Body.Squash(squash);
        Arms(ref f, armL, elbowL, armR, elbowR);
        f.Limbs.HeadTilt = head;
        f.Limbs.Crouch = crouch;
        f.Limbs.Face = face;
        return f;
    }

    static readonly MoveFrame[] PopKeys =
    [
        Key(-12, 0.00, 165, 0, 25, 0, -8),
        Key(12, 0.00, 25, 0, 165, 0, 8),
        Key(0, 0.16, 90, 90, 90, 90, 0, crouch: 0.2),
        Key(0, -0.08, 90, -90, 90, 90, -10),
        Key(-8, 0.00, 90, 90, 90, -90, 10),
        Key(9, 0.10, 40, -112, 150, 0, 12, skew: -0.08),
        Key(0, 0.20, 30, -125, 30, -125, 0, crouch: 0.3),
        Key(0, -0.12, 160, 0, 160, 0, 0, Face.Happy),
    ];

    // Snap into a new stiff pose on every beat.
    public static readonly DanceMove PopLock = new()
    {
        Id = "poplock", Name = "Pop & Lock", Beats = 8,
        Effects = [(7.0, Fx.Sparkle)],
        Eval = (t, dir) =>
        {
            int i = Math.Clamp((int)Math.Floor(t), 0, 7);
            double b = t - i;
            var from = i == 0 ? MoveFrame.Neutral : PopKeys[i - 1];
            var f = MoveFrame.Lerp(from, PopKeys[i], OutBack(Span(b, 0, 0.22)));
            f.Limbs.Face = PopKeys[i].Limbs.Face;
            f.Limbs.EyeOpen = 1;
            if (i == 7) f.Body.Y = 0.12 * Arc(Span(b, 0, 0.8));
            if (dir < 0) { f.Body.Lean = -f.Body.Lean; f.Body.Skew = -f.Body.Skew; }
            return f;
        },
    };

    // Double-time nods with one fist in the air.
    public static readonly DanceMove Headbang = new()
    {
        Id = "headbang", Name = "Headbang", Beats = 4,
        Eval = (t, dir) =>
        {
            var f = Happy();
            double h = Math.Pow(0.5 - 0.5 * Cos(t * 2), 2);
            f.Body.Squash(0.10 * h);
            f.Body.Lean = 6 * Sin(t / 2);
            Arms(ref f, 35, -115, 168 - 22 * h, 8);
            f.Limbs.HeadBob = -0.045 * h;
            f.Limbs.HeadTilt = 5 * Sin(t / 2);
            f.Limbs.LiftL = 0.25 * h;
            return f;
        },
    };

    // Jumping jacks.
    public static readonly DanceMove StarJump = new()
    {
        Id = "starjump", Name = "Star Jumps", Beats = 4,
        Effects = [(1.0, Fx.Stomp), (2.0, Fx.Stomp), (3.0, Fx.Stomp)],
        Eval = (t, dir) =>
        {
            var f = Happy();
            double b = Frac(t), j = Arc(b);
            f.Body.Y = 0.28 * j;
            f.Body.Squash(0.14 * Decay(b, 9) - 0.07 * j);
            f.Body.ScaleX *= 1 + 0.06 * j;
            Arms(ref f, 18 + 145 * j, 6, 18 + 145 * j, 6);
            f.Limbs.LegL = f.Limbs.LegR = 3 + 30 * j;
            return f;
        },
    };

    // Running man: quick alternating knees, turning round halfway.
    public static readonly DanceMove Shuffle = new()
    {
        Id = "shuffle", Name = "Shuffle", Beats = 4,
        Eval = (t, dir) =>
        {
            var f = Happy();
            double s = Sin(t);
            f.Body.X = 0.05 * Sin(t / 2);
            f.Body.Y = 0.035 * Math.Abs(s);
            f.Body.Lean = 4 * s;
            f.Body.Squash(0.035 * Cos(t * 2));
            f.Body.Facing = (int)Math.Floor(t / 2) % 2 == 0 ? dir : -dir;
            f.Limbs.LegL = 3 + 20 * Math.Max(0, s); f.Limbs.LiftL = 0.6 * Math.Max(0, s);
            f.Limbs.LegR = 3 + 20 * Math.Max(0, -s); f.Limbs.LiftR = 0.6 * Math.Max(0, -s);
            Arms(ref f, 45 - 30 * s, 70, 45 + 30 * s, 70);
            return f;
        },
    };

    // Four rapid spins rising off the floor, then a dizzy wobble.
    public static readonly DanceMove Tornado = new()
    {
        Id = "tornado", Name = "Tornado", Beats = 4,
        Effects = [(0.8, Fx.Sparkle), (1.6, Fx.Sparkle), (2.4, Fx.Sparkle), (3.2, Fx.Stomp)],
        Eval = (t, dir) =>
        {
            var f = Happy();
            double lift = Arc(Span(t, 0.2, 3.2));
            double up = Lerp(12, 172, InOut(Span(t, 0, 0.6)));
            f.Body.Turn = dir * 1440 * InOutCubic(Span(t, 0, 3.2));
            f.Body.Y = 0.38 * lift * lift;
            f.Body.ScaleX *= 1 - 0.08 * lift;
            f.Body.ScaleY *= 1 + 0.08 * lift;
            Arms(ref f, up, 6, up, 6);
            if (t > 3.2)
            {
                double w = (t - 3.2) / 0.8;
                double arms = Lerp(172, 70, InOut(w * 2));
                f.Body.Lean = 10 * Math.Sin(w * Tau * 2) * (1 - w);
                f.Body.Squash(0.10 * Decay(w, 5) * InOut(Span(w, 0, 0.1)));
                Arms(ref f, arms, 6, arms, 6);
                f.Limbs.HeadTilt = -f.Body.Lean * 0.6;
                f.Limbs.Face = Face.Dizzy;
            }
            return f;
        },
    };

    static readonly MoveFrame PointRight = Key(0, 0, 32, -115, 152, 0, 6);
    static readonly MoveFrame PointLeft = Key(0, 0, 152, 0, 32, -115, -6);

    // Parade across the screen pointing at the sky on alternate sides.
    public static readonly DanceMove Strut = new()
    {
        Id = "strut", Name = "Strut", Beats = 8, Travels = true,
        Eval = (t, dir) =>
        {
            int i = Math.Clamp((int)Math.Floor(t), 0, 7);
            double b = t - i;
            int bar = Math.Clamp((int)Math.Floor(t / 2), 0, 3);
            double k = OutBack(Span(t - bar * 2, 0, 0.3));
            var cur = bar % 2 == 0 ? PointRight : PointLeft;
            var prev = bar == 0 ? MoveFrame.Neutral : bar % 2 == 0 ? PointLeft : PointRight;
            var f = MoveFrame.Lerp(prev, cur, k);
            f.Limbs.Face = Face.Cool;
            f.Limbs.EyeOpen = 1;

            f.Body = BodyPose.Identity;
            f.Body.X = dir * 0.19 * t;
            f.Body.Facing = dir;
            f.Body.Y = 0.07 * Arc(b);
            f.Body.Lean = 6 * Sin(t / 2);
            f.Body.Skew = 0.05 * Sin(t);
            f.Body.Squash(0.06 * Decay(b, 10));
            if (i % 2 == 0) { f.Limbs.LiftL = 0.45 * Arc(b); f.Limbs.LegL = 3 + 8 * Arc(b); }
            else { f.Limbs.LiftR = 0.45 * Arc(b); f.Limbs.LegR = 3 + 8 * Arc(b); }
            return f;
        },
    };

    // Sideways wheel across the floor.
    public static readonly DanceMove Cartwheel = new()
    {
        Id = "cartwheel", Name = "Cartwheel", Beats = 4, Travels = true,
        Effects = [(2.6, Fx.Stomp), (2.6, Fx.Sparkle)],
        Eval = (t, dir) =>
        {
            var f = Happy();
            if (t < 0.6)
            {
                double a = t / 0.6;
                double up = Lerp(12, 170, InOut(a));
                f.Body.Lean = -dir * 6 * Arc(a);
                f.Body.Squash(0.08 * Arc(a));
                Arms(ref f, up, 6, up, 6);
            }
            else if (t < 2.6)
            {
                double u = (t - 0.6) / 2, e = InOut(u);
                f.Body.X = dir * 1.15 * e;
                f.Body.Spin = dir * 360 * e;
                f.Body.Y = 0.10 * Arc(u);
                Arms(ref f, 170, 6, 170, 6);
                f.Limbs.LegL = f.Limbs.LegR = 3 + 28 * Arc(u);
            }
            else
            {
                double v = t - 2.6;
                double arms = Lerp(170, 150, OutBack(Span(v, 0.05, 0.35)));
                f.Body.X = dir * 1.15;
                f.Body.Squash(0.15 * Decay(v, 5) * Math.Cos(v * 9) * InOut(Span(v, 0, 0.08)));
                f.Body.Y = 0.05 * Arc(Span(v, 0.5, 1.2));
                Arms(ref f, arms, 6, arms, 6);
            }
            return f;
        },
    };

    static readonly MoveFrame DiscoRight = Key(8, 0, 35, -115, 150, 0, 8, Face.Happy, skew: -0.06);
    static readonly MoveFrame DiscoLeft = Key(-8, 0, 150, 0, 35, -115, -8, Face.Happy, skew: 0.06);

    // The classic: one hand on the hip, the other pointing at the ceiling, swapping every beat.
    public static readonly DanceMove DiscoPoint = new()
    {
        Id = "disco", Name = "Disco Point", Beats = 4,
        Eval = (t, dir) =>
        {
            int i = Math.Clamp((int)Math.Floor(t), 0, 3);
            double b = t - i;
            bool right = (i % 2 == 0) == (dir > 0);
            var cur = right ? DiscoRight : DiscoLeft;
            var prev = i == 0 ? MoveFrame.Neutral : right ? DiscoLeft : DiscoRight;
            var f = MoveFrame.Lerp(prev, cur, OutBack(Span(b, 0, 0.25)));
            f.Limbs.Face = Face.Happy;
            f.Limbs.EyeOpen = 1;
            // Shift the hips towards the pointing hand, and come back to centre as the move ends.
            double side = right ? 0.05 : -0.05;
            f.Body.X = Lerp(i == 0 ? 0 : -side, side, InOut(Span(b, 0, 0.25))) * (1 - InOut(Span(t, 3.5, 4)));
            f.Body.Squash(0.07 * Decay(b, 10));
            f.Body.Y = 0.03 * Arc(Span(b, 0.5, 1));
            return f;
        },
    };

    /// <summary>Every procedural move, in menu order.</summary>
    public static readonly IReadOnlyList<DanceMove> All =
    [
        Bounce, Sway, DiscoPoint, SideStep, Shuffle, Wiggle, Headbang, PopLock,
        StarJump, Twirl, Tornado, Backflip, Cartwheel, Moonwalk, Strut,
    ];

    public static DanceMove? Find(string id) => All.FirstOrDefault(m => m.Id == id);

    /// <summary>
    /// Every dance a character knows, switched on or not: its own clips first, each played
    /// for at least four beats at the given tempo, then the built-in moves.
    /// </summary>
    public static IReadOnlyList<DanceMove> ForCharacter(Characters.ICharacter character, double bpm)
    {
        var list = new List<DanceMove>();
        foreach (var clip in character.DanceClips)
        {
            double beats = Math.Max(0.25, clip.Seconds * bpm / 60);
            double total = beats;
            while (total < 4) total += beats;
            list.Add(FromClip(clip.Id, clip.Name, total));
        }
        list.AddRange(All);
        return list;
    }

    /// <summary>
    /// How a move is named in the settings: a built-in move by its id, a character's own
    /// dance by the character and its clip, as its clips are no one else's.
    /// </summary>
    public static string KeyOf(DanceMove move, string characterId) => move.Clip == null ? move.Id : $"{characterId}/{move.Id}";

    /// <summary>How one of a character's actions is named in the settings: "domo/action_fart".</summary>
    public static string KeyOf(Characters.OwnClip action, string characterId) => $"{characterId}/{action.Id}";

    /// <summary>Wraps an artist-made animation clip so it can be queued like any other move.</summary>
    public static DanceMove FromClip(string clip, string name, double beats) => new()
    {
        Id = clip, Name = name, Beats = beats, Clip = clip,
        Eval = (_, _) => Happy(),
    };
}

/// <summary>Named sequences of moves.</summary>
public sealed record Routine(string Name, string[] MoveIds)
{
    public static readonly IReadOnlyList<Routine> All =
    [
        new("Disco Fever", ["strut", "disco", "sway", "twirl", "sidestep", "disco", "twirl"]),
        new("Street", ["poplock", "shuffle", "headbang", "moonwalk", "backflip"]),
        new("Acrobat", ["starjump", "cartwheel", "tornado", "backflip", "twirl"]),
        new("Chill", ["sway", "bounce", "wiggle", "sidestep", "sway"]),
    ];

    public IEnumerable<DanceMove> Resolve() => MoveIds.Select(Moves.Find).OfType<DanceMove>();

    /// <summary>The routine without the moves that are switched off. Empty if that leaves nothing.</summary>
    public IReadOnlyList<DanceMove> Resolve(IReadOnlyList<DanceMove> switchedOn) => Resolve().Where(switchedOn.Contains).ToList();
}
