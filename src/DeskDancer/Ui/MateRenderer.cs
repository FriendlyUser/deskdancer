using Avalonia;
using Avalonia.Media;
using Avalonia.Media.Immutable;
using DeskDancer.Characters;
using DeskDancer.Engine;

namespace DeskDancer.Ui;

/// <summary>Stateless drawing shared by the live window and the offline render tools.</summary>
public static class MateRenderer
{
    static readonly StreamGeometry StarShape = BuildStar();
    static readonly StreamGeometry HeartShape = BuildHeart();

    static IBrush Brush(uint argb, double alpha)
    {
        var c = Color.FromUInt32(argb);
        return new ImmutableSolidColorBrush(Color.FromArgb((byte)(Ease.Clamp01(alpha) * c.A), c.R, c.G, c.B));
    }

    /// <summary>
    /// Builds the whole-body transform. Local space has the feet at the origin; the result
    /// still needs translating to where the feet are on screen.
    /// </summary>
    public static Matrix BodyMatrix(in BodyPose b, double h, double flip)
    {
        double turn = Math.Cos(b.Turn * Ease.Deg);
        var m = Matrix.CreateScale(b.ScaleX * turn * flip, b.ScaleY);
        // y is negative above the feet, so a negative shear term pushes the head right.
        if (b.Skew != 0) m *= new Matrix(1, 0, -b.Skew, 1, 0, 0);
        if (b.Lean != 0) m *= Matrix.CreateRotation(b.Lean * Ease.Deg);
        if (b.Spin != 0)
        {
            double centre = -0.5 * h * b.ScaleY;
            m *= Matrix.CreateTranslation(0, -centre) * Matrix.CreateRotation(b.Spin * Ease.Deg) * Matrix.CreateTranslation(0, centre);
        }
        return m;
    }

    public static void DrawCharacter(DrawingContext ctx, ICharacter character, double h, Point feet,
        in BodyPose body, int facing, in CharacterFrame frame)
    {
        double flip = facing * character.NaturalFacing < 0 ? -1 : 1;
        var m = BodyMatrix(body, h, flip) * Matrix.CreateTranslation(feet.X, feet.Y - body.Y * h);
        using (ctx.PushTransform(m))
            character.Draw(ctx, h, frame);
    }

    /// <summary>Soft contact shadow, plus a pulsing neon pool of light while dancing.</summary>
    public static void DrawFloor(DrawingContext ctx, Point floor, double h, double aspect, double lift, double energy, double beat)
    {
        double near = 1 - Ease.Clamp01(lift / 1.6);
        if (near <= 0.01) return;
        double rx = (0.2 + 0.2 * aspect) * h * (0.6 + 0.4 * near), ry = rx * 0.2;

        if (energy > 0.02)
        {
            uint colour = ParticleSystem.Neon[(int)(Math.Abs(Math.Floor(beat)) % ParticleSystem.Neon.Length)];
            double hit = Math.Exp(-Ease.Frac(beat) * 3.5);
            ctx.DrawEllipse(Brush(colour, energy * (0.10 + 0.14 * hit)), null, floor, rx * (1.5 + 0.25 * hit), ry * (1.5 + 0.25 * hit));
            ctx.DrawEllipse(Brush(colour, energy * (0.16 + 0.22 * hit)), null, floor, rx * 1.1, ry * 1.1);
        }
        ctx.DrawEllipse(Brush(0xFF000000, 0.24 * near), null, floor, rx, ry);
    }

    public static void DrawParticle(DrawingContext ctx, in Particle p, Point at, double h)
    {
        double age = p.Age, size = p.Size * h;
        double fade = Ease.Clamp01(Math.Min(age * 8, (1 - age) * 2.5));
        switch (p.Kind)
        {
            case ParticleKind.Note:
            {
                double drift = Math.Sin(age * 7 + p.Wobble) * size * 0.5;
                var m = Matrix.CreateRotation(p.Rot + Math.Sin(age * 5 + p.Wobble) * 0.25)
                        * Matrix.CreateTranslation(at.X + drift, at.Y);
                using (ctx.PushTransform(m))
                {
                    var brush = Brush(p.Color, fade);
                    var pen = new Pen(brush, size * 0.2, null, PenLineCap.Round, PenLineJoin.Round);
                    ctx.DrawEllipse(brush, null, new Point(0, 0), size * 0.5, size * 0.38);
                    ctx.DrawLine(pen, new Point(size * 0.42, 0), new Point(size * 0.42, -size * 1.5));
                    ctx.DrawLine(pen, new Point(size * 0.42, -size * 1.5), new Point(size * 0.98, -size * 1.1));
                }
                break;
            }
            case ParticleKind.Star:
            {
                double s = size * (0.4 + 0.6 * Math.Sin(Ease.Clamp01(age) * Math.PI));
                var m = Matrix.CreateScale(s, s) * Matrix.CreateRotation(p.Rot) * Matrix.CreateTranslation(at.X, at.Y);
                using (ctx.PushTransform(m)) ctx.DrawGeometry(Brush(p.Color, fade), null, StarShape);
                break;
            }
            case ParticleKind.Heart:
            {
                double drift = Math.Sin(age * 6 + p.Wobble) * size * 0.4;
                double s = size * (0.5 + 0.5 * Ease.OutBack(age * 4));
                var m = Matrix.CreateScale(s, s) * Matrix.CreateTranslation(at.X + drift, at.Y);
                using (ctx.PushTransform(m)) ctx.DrawGeometry(Brush(p.Color, fade), null, HeartShape);
                break;
            }
            case ParticleKind.Zzz:
            {
                double s = size * (0.6 + 0.9 * age);
                double x = at.X + Math.Sin(age * 5 + p.Wobble) * size * 0.4, y = at.Y;
                var pen = new Pen(Brush(p.Color, fade * 0.9), Math.Max(1, s * 0.22), null, PenLineCap.Round, PenLineJoin.Round);
                ctx.DrawLine(pen, new Point(x - s / 2, y - s / 2), new Point(x + s / 2, y - s / 2));
                ctx.DrawLine(pen, new Point(x + s / 2, y - s / 2), new Point(x - s / 2, y + s / 2));
                ctx.DrawLine(pen, new Point(x - s / 2, y + s / 2), new Point(x + s / 2, y + s / 2));
                break;
            }
            case ParticleKind.Confetti:
            {
                // Scaling one axis by a sine makes the flat paper appear to tumble.
                var m = Matrix.CreateScale(1, Math.Sin(p.Rot * 1.7 + p.Wobble))
                        * Matrix.CreateRotation(p.Rot) * Matrix.CreateTranslation(at.X, at.Y);
                using (ctx.PushTransform(m))
                    ctx.DrawRectangle(Brush(p.Color, Ease.Clamp01((1 - age) * 3)), null, new Rect(-size / 2, -size * 0.32, size, size * 0.64));
                break;
            }
            case ParticleKind.Ring:
            {
                double grow = Ease.OutCubic(age);
                double rx = size * (1 + 2.2 * grow), ry = rx * 0.22;
                var pen = new Pen(Brush(p.Color, 0.55 * (1 - age)), Math.Max(1, h * 0.022 * (1 - age)));
                ctx.DrawEllipse(null, pen, at, rx, ry);
                break;
            }
        }
    }

    static StreamGeometry BuildStar()
    {
        var geo = new StreamGeometry();
        using var g = geo.Open();
        const double k = 0.26;
        Point[] pts =
        [
            new(0, -1), new(k, -k), new(1, 0), new(k, k), new(0, 1), new(-k, k), new(-1, 0), new(-k, -k),
        ];
        g.BeginFigure(pts[0], true);
        for (int i = 1; i < pts.Length; i++) g.LineTo(pts[i]);
        g.EndFigure(true);
        return geo;
    }

    static StreamGeometry BuildHeart()
    {
        var geo = new StreamGeometry();
        using var g = geo.Open();
        g.BeginFigure(new Point(0, 0.9), true);
        g.CubicBezierTo(new Point(-1.5, -0.1), new Point(-0.75, -1.25), new Point(0, -0.45));
        g.CubicBezierTo(new Point(0.75, -1.25), new Point(1.5, -0.1), new Point(0, 0.9));
        g.EndFigure(true);
        return geo;
    }
}
