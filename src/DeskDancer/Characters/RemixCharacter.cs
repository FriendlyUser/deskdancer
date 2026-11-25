using Avalonia;
using Avalonia.Media;
using Avalonia.Media.Immutable;
using DeskDancer.Engine;

namespace DeskDancer.Characters;

/// <summary>
/// Remix, the built-in mate: a small DJ robot in a hoodie, drawn entirely in code
/// so it stays sharp at any size and every limb can be posed by the choreography.
/// All measurements are fractions of the character height.
/// </summary>
public sealed class RemixCharacter : ICharacter
{
    public string Id => CharacterIds.BuiltIn;
    public string DisplayName => "Remix (built-in)";
    public double AspectRatio => 0.66;
    public double PreferredHeight => 150;
    public bool IsRigged => true;
    public bool PixelArt => false;
    public int NaturalFacing => 1;
    public IReadOnlyList<DanceClip> DanceClips => [];
    public bool HasClip(string clip) => false;

    static ImmutableSolidColorBrush B(uint argb) => new(Color.FromUInt32(argb));

    static readonly ImmutableSolidColorBrush Outline = B(0xFF15162E);
    static readonly ImmutableSolidColorBrush Shell = B(0xFF5A5FCF);
    static readonly ImmutableSolidColorBrush ShellLight = B(0xFF8388F2);
    static readonly ImmutableSolidColorBrush Visor = B(0xFF0E1024);
    static readonly ImmutableSolidColorBrush Gloss = B(0x26FFFFFF);
    static readonly ImmutableSolidColorBrush Led = B(0xFFFF7ADB);
    static readonly ImmutableSolidColorBrush LedGlow = B(0x4CFF5FD2);
    static readonly ImmutableSolidColorBrush Hoodie = B(0xFF20C9B5);
    static readonly ImmutableSolidColorBrush HoodieDark = B(0xFF14998B);
    static readonly ImmutableSolidColorBrush Limb = B(0xFF2B2E55);
    static readonly ImmutableSolidColorBrush White = B(0xFFF4F5FB);
    static readonly ImmutableSolidColorBrush Grey = B(0xFFC3C7DE);
    static readonly ImmutableSolidColorBrush Pink = B(0xFFFF5FD2);
    static readonly ImmutableSolidColorBrush[] EqBars =
    [
        B(0xFFFF5FD2), B(0xFFFFE45C), B(0xFF3CF2FF), B(0xFF8CFF7A), B(0xFFFF8A5C),
    ];

    const double OutlineWidth = 0.013;

    /// <summary>Drawing helper that converts character units (y up) into canvas coordinates.</summary>
    readonly struct Painter(DrawingContext ctx, double u)
    {
        public DrawingContext Ctx => ctx;
        public double U => u;

        public Point P(double x, double y) => new(x * u, -y * u);
        public Pen Pen(IBrush brush, double width) => new(brush, width * u, null, PenLineCap.Round, PenLineJoin.Round);

        public void Line(IBrush brush, double width, double x1, double y1, double x2, double y2) =>
            ctx.DrawLine(Pen(brush, width), P(x1, y1), P(x2, y2));

        /// <summary>A thick rounded stroke with a dark outline around it.</summary>
        public void Tube(IBrush brush, double width, double x1, double y1, double x2, double y2)
        {
            Line(Outline, width + OutlineWidth * 2, x1, y1, x2, y2);
            Line(brush, width, x1, y1, x2, y2);
        }

        public void Box(IBrush? fill, IPen? pen, double cx, double cy, double w, double h, double r) =>
            ctx.DrawRectangle(fill, pen, new Rect((cx - w / 2) * u, (-cy - h / 2) * u, w * u, h * u), r * u, r * u);

        public void Oval(IBrush? fill, IPen? pen, double cx, double cy, double rx, double ry) =>
            ctx.DrawEllipse(fill, pen, P(cx, cy), rx * u, ry * u);

        /// <summary>Elliptical arc; angles in degrees, 0 = right, 90 = up.</summary>
        public void Arc(IBrush brush, double width, double cx, double cy, double rx, double ry, double from, double to, int segments = 12)
        {
            var pen = Pen(brush, width);
            Point prev = default;
            for (int i = 0; i <= segments; i++)
            {
                double a = (from + (to - from) * i / segments) * Ease.Deg;
                var pt = P(cx + Math.Cos(a) * rx, cy + Math.Sin(a) * ry);
                if (i > 0) ctx.DrawLine(pen, prev, pt);
                prev = pt;
            }
        }
    }

    public void Draw(DrawingContext ctx, double height, in CharacterFrame frame)
    {
        var p = new Painter(ctx, height);
        var limbs = frame.Limbs;
        var outline = p.Pen(Outline, OutlineWidth);

        double hipY = 0.265 - 0.15 * limbs.Crouch;
        double torsoBottom = hipY - 0.03, torsoTop = hipY + 0.25;
        double pulse = frame.Energy * Math.Exp(-Ease.Frac(frame.Beat) * 4);

        DrawLeg(p, outline, -1, hipY, limbs.LegL, limbs.LiftL);
        DrawLeg(p, outline, +1, hipY, limbs.LegR, limbs.LiftR);
        DrawTorso(p, outline, torsoBottom, torsoTop, frame);
        DrawArm(p, outline, -1, torsoTop, limbs.ArmL, limbs.ElbowL);
        DrawArm(p, outline, +1, torsoTop, limbs.ArmR, limbs.ElbowR);

        // The head pivots on the neck.
        var neck = p.P(0, torsoTop - 0.01);
        var tilt = Matrix.CreateTranslation(-neck.X, -neck.Y)
                   * Matrix.CreateRotation(limbs.HeadTilt * Ease.Deg)
                   * Matrix.CreateTranslation(neck.X, neck.Y);
        using (ctx.PushTransform(tilt))
            DrawHead(p, outline, torsoTop + 0.175 + limbs.HeadBob, limbs, pulse, frame.Time);
    }

    static void DrawLeg(Painter p, IPen outline, int side, double hipY, double angle, double lift)
    {
        const double fullLength = 0.205, ankleMin = 0.058;
        double a = angle * Ease.Deg;
        double length = fullLength * (1 - 0.55 * Ease.Clamp01(lift));
        double cos = Math.Max(Math.Cos(a), 0.25);
        // Telescopic legs: they shorten rather than poke through the floor when the hips drop.
        if (hipY - cos * length < ankleMin) length = Math.Max(0.02, (hipY - ankleMin) / cos);

        double hipX = side * 0.078;
        double ax = hipX + side * Math.Sin(a) * length, ay = hipY - Math.Cos(a) * length;
        p.Tube(Limb, 0.066, hipX, hipY, ax, ay);

        // Sneaker, toe turned out a little and following the leg when it swings wide.
        var ankle = p.P(ax, ay);
        var turn = Matrix.CreateTranslation(-ankle.X, -ankle.Y)
                   * Matrix.CreateRotation(-side * angle * 0.55 * Ease.Deg)
                   * Matrix.CreateTranslation(ankle.X, ankle.Y);
        using (p.Ctx.PushTransform(turn))
        {
            double cx = ax + side * 0.022, cy = ay - 0.014;
            p.Box(White, outline, cx, cy, 0.168, 0.086, 0.04);
            p.Line(Pink, 0.02, cx - 0.058, cy - 0.03, cx + 0.058, cy - 0.03);
            p.Line(Grey, 0.011, cx - side * 0.012, cy + 0.02, cx + side * 0.03, cy + 0.02);
            p.Line(Grey, 0.011, cx - side * 0.005, cy, cx + side * 0.04, cy);
        }
    }

    static void DrawTorso(Painter p, IPen outline, double bottom, double top, in CharacterFrame frame)
    {
        double mid = (bottom + top) / 2, h = top - bottom;
        p.Box(Hoodie, outline, 0, mid, 0.31, h, 0.085);
        // Hem and kangaroo pocket.
        p.Box(HoodieDark, null, 0, bottom + 0.028, 0.27, 0.034, 0.017);
        p.Box(HoodieDark, null, 0, bottom + 0.098, 0.17, 0.066, 0.03);

        // Chest equaliser: idles with a flicker, jumps with the beat while dancing.
        double eqY = bottom + 0.19;
        p.Box(Visor, null, 0, eqY, 0.168, 0.074, 0.02);
        for (int i = 0; i < 5; i++)
        {
            double idle = 0.2 + 0.12 * Math.Sin(frame.Time * 2.3 + i * 1.7);
            double live = 0.25 + 0.75 * Math.Abs(Math.Sin(frame.Beat * Math.PI + i * 0.9)) * (0.6 + 0.4 * Math.Sin(frame.Time * 9 + i * 2.1));
            double level = Ease.Clamp01(Ease.Lerp(idle, live, frame.Energy));
            double bh = 0.012 + 0.042 * level;
            p.Box(EqBars[i], null, (i - 2) * 0.028, eqY - 0.027 + bh / 2, 0.018, bh, 0.005);
        }

        // Hood bunched around the neck, with drawstrings that swing behind the motion.
        p.Oval(HoodieDark, outline, 0, top + 0.002, 0.175, 0.052);
        double swing = frame.Trail * Ease.Deg;
        foreach (int side in (ReadOnlySpan<int>)[-1, 1])
        {
            double x = side * 0.05, y = top - 0.035;
            double ex = x + Math.Sin(swing) * 0.085, ey = y - Math.Cos(swing) * 0.085;
            p.Line(White, 0.014, x, y, ex, ey);
            p.Oval(Pink, null, ex, ey, 0.013, 0.013);
        }
    }

    static void DrawArm(Painter p, IPen outline, int side, double torsoTop, double angle, double elbow)
    {
        // Raised arms fan out into a V and stretch a little so the hands clear the big head.
        double shoulder = angle <= 110 ? angle : 110 + (angle - 110) * 0.6;
        double stretch = 1 + 0.45 * Ease.Span(shoulder, 95, 150);
        double upper = 0.15 * stretch, fore = 0.14 * stretch;
        double a1 = shoulder * Ease.Deg, a2 = (shoulder + elbow) * Ease.Deg;

        double sx = side * 0.16, sy = torsoTop - 0.055;
        double ex = sx + side * Math.Sin(a1) * upper, ey = sy - Math.Cos(a1) * upper;
        double wx = ex + side * Math.Sin(a2) * fore, wy = ey - Math.Cos(a2) * fore;
        double hx = wx + side * Math.Sin(a2) * 0.03, hy = wy - Math.Cos(a2) * 0.03;

        // Outline pass first so the two sleeve segments read as one shape.
        p.Line(Outline, 0.074 + OutlineWidth * 2, sx, sy, ex, ey);
        p.Line(Outline, 0.074 + OutlineWidth * 2, ex, ey, wx, wy);
        p.Line(Hoodie, 0.074, sx, sy, ex, ey);
        p.Line(Hoodie, 0.074, ex, ey, wx, wy);
        p.Line(HoodieDark, 0.078, Ease.Lerp(ex, wx, 0.8), Ease.Lerp(ey, wy, 0.8), wx, wy);
        p.Oval(White, outline, hx, hy, 0.047, 0.047);
    }

    static void DrawHead(Painter p, IPen outline, double cy, in LimbPose limbs, double pulse, double time)
    {
        // Headphone band behind the shell.
        p.Arc(Outline, 0.042 + OutlineWidth * 2, 0, cy + 0.01, 0.275, 0.215, 12, 168);
        p.Arc(White, 0.042, 0, cy + 0.01, 0.275, 0.215, 12, 168);

        p.Box(Shell, outline, 0, cy, 0.50, 0.36, 0.125);
        p.Box(ShellLight, null, 0, cy + 0.148, 0.34, 0.028, 0.014);

        double vy = cy - 0.008;
        p.Box(Visor, null, 0, vy, 0.405, 0.24, 0.085);
        p.Line(Gloss, 0.022, -0.155, vy + 0.07, -0.10, vy + 0.094);
        p.Line(Gloss, 0.014, -0.075, vy + 0.098, -0.06, vy + 0.101);

        DrawFace(p, vy, limbs, time);

        // Ear cups in front, with a ring that throbs on the beat.
        foreach (int side in (ReadOnlySpan<int>)[-1, 1])
        {
            double x = side * 0.262;
            p.Box(White, outline, x, cy - 0.005, 0.095, 0.18, 0.045);
            double glow = 0.022 + 0.014 * pulse;
            p.Oval(LedGlow, null, x, cy - 0.005, glow + 0.016, 0.05 + glow * 0.9);
            p.Oval(Pink, null, x, cy - 0.005, 0.02 + 0.006 * pulse, 0.048 + 0.008 * pulse);
        }
    }

    // ---- LED face ----

    static void LedLine(Painter p, double width, double x1, double y1, double x2, double y2)
    {
        p.Line(LedGlow, width * 2.6, x1, y1, x2, y2);
        p.Line(Led, width, x1, y1, x2, y2);
    }

    static void LedArc(Painter p, double width, double cx, double cy, double rx, double ry, double from, double to)
    {
        p.Arc(LedGlow, width * 2.6, cx, cy, rx, ry, from, to);
        p.Arc(Led, width, cx, cy, rx, ry, from, to);
    }

    static void LedBox(Painter p, double cx, double cy, double w, double h)
    {
        double r = Math.Min(w, h) / 2;
        p.Box(LedGlow, null, cx, cy, w + 0.034, h + 0.034, r + 0.017);
        p.Box(Led, null, cx, cy, w, h, r);
    }

    static void LedHeart(Painter p, double cx, double cy, double s)
    {
        foreach (var (brush, k) in ((IBrush, double)[])[(LedGlow, 1.45), (Led, 1.0)])
        {
            double r = s * 0.3 * k;
            p.Oval(brush, null, cx - r * 0.85, cy + r * 0.45, r, r);
            p.Oval(brush, null, cx + r * 0.85, cy + r * 0.45, r, r);
            var geo = new StreamGeometry();
            using (var g = geo.Open())
            {
                g.BeginFigure(p.P(cx - r * 1.78, cy + r * 0.12), true);
                g.LineTo(p.P(cx + r * 1.78, cy + r * 0.12));
                g.LineTo(p.P(cx, cy - r * 1.85));
                g.EndFigure(true);
            }
            p.Ctx.DrawGeometry(brush, null, geo);
        }
    }

    static void DrawFace(Painter p, double vy, in LimbPose limbs, double time)
    {
        const double stroke = 0.02;
        double lookX = limbs.LookX * 0.022, lookY = limbs.LookY * 0.014;
        double ey = vy + 0.022 + lookY, my = vy - 0.058 + lookY * 0.5;
        double open = Math.Max(limbs.EyeOpen, 0.12);
        double exL = -0.095 + lookX, exR = 0.095 + lookX, mx = lookX * 0.6;

        switch (limbs.Face)
        {
            case Face.Happy:
                LedArc(p, stroke, exL, ey - 0.018, 0.036, 0.04, 20, 160);
                LedArc(p, stroke, exR, ey - 0.018, 0.036, 0.04, 20, 160);
                // Open-mouthed grin: a filled "D" lying on its back.
                p.Oval(LedGlow, null, mx, my + 0.004, 0.06, 0.045);
                var grin = new StreamGeometry();
                using (var g = grin.Open())
                {
                    g.BeginFigure(p.P(mx - 0.044, my + 0.016), true);
                    g.LineTo(p.P(mx + 0.044, my + 0.016));
                    g.ArcTo(p.P(mx - 0.044, my + 0.016), new Size(0.044 * p.U, 0.042 * p.U), 0, false, SweepDirection.Clockwise);
                    g.EndFigure(true);
                }
                p.Ctx.DrawGeometry(Led, null, grin);
                break;

            case Face.Wide:
                LedArc(p, stroke, exL, ey, 0.036, 0.042, 0, 360);
                LedArc(p, stroke, exR, ey, 0.036, 0.042, 0, 360);
                LedArc(p, stroke * 0.9, mx, my, 0.018, 0.02, 0, 360);
                break;

            case Face.Sleepy:
                LedLine(p, stroke, exL - 0.034, ey - 0.008, exL + 0.034, ey - 0.016);
                LedLine(p, stroke, exR - 0.034, ey - 0.016, exR + 0.034, ey - 0.008);
                LedArc(p, stroke * 0.8, mx, my + 0.004, 0.014, 0.012, 0, 360);
                break;

            case Face.Dizzy:
                foreach (double x in (ReadOnlySpan<double>)[exL, exR])
                {
                    double wob = Math.Sin(time * 14 + x * 20) * 0.006;
                    LedLine(p, stroke, x - 0.03, ey + 0.03 + wob, x + 0.03, ey - 0.03 - wob);
                    LedLine(p, stroke, x - 0.03, ey - 0.03 - wob, x + 0.03, ey + 0.03 + wob);
                }
                for (int i = 0; i < 4; i++)
                {
                    double x0 = mx - 0.048 + i * 0.024, up = i % 2 == 0 ? 0.012 : -0.012;
                    LedLine(p, stroke * 0.8, x0, my - up, x0 + 0.024, my + up);
                }
                break;

            case Face.Wink:
                LedBox(p, exL, ey, 0.056, 0.094 * open);
                LedArc(p, stroke, exR, ey - 0.018, 0.036, 0.04, 20, 160);
                LedArc(p, stroke, mx, my + 0.022, 0.042, 0.034, 205, 335);
                break;

            case Face.Cool:
                // Visor shades: one solid bar with a notch for the nose, and a smirk.
                LedBox(p, lookX, ey, 0.30, 0.062);
                p.Box(Visor, null, lookX, ey - 0.024, 0.036, 0.03, 0.012);
                p.Line(Visor, 0.012, exL - 0.03, ey + 0.012, exL + 0.012, ey + 0.012);
                p.Line(Visor, 0.012, exR - 0.012, ey + 0.012, exR + 0.03, ey + 0.012);
                LedLine(p, stroke * 0.9, mx - 0.03, my - 0.006, mx + 0.034, my + 0.012);
                break;

            case Face.Love:
                LedHeart(p, exL, ey, 0.085 * (0.5 + 0.5 * open));
                LedHeart(p, exR, ey, 0.085 * (0.5 + 0.5 * open));
                LedArc(p, stroke, mx, my + 0.022, 0.042, 0.034, 205, 335);
                break;

            default:
                LedBox(p, exL, ey, 0.056, 0.094 * open);
                LedBox(p, exR, ey, 0.056, 0.094 * open);
                LedArc(p, stroke * 0.9, mx, my + 0.018, 0.034, 0.024, 210, 330);
                break;
        }
    }
}
