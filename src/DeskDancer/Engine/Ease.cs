namespace DeskDancer.Engine;

/// <summary>Small maths helpers shared by the choreography and the renderer.</summary>
public static class Ease
{
    public const double Tau = Math.PI * 2;
    public const double Deg = Math.PI / 180;

    public static double Clamp01(double t) => t < 0 ? 0 : t > 1 ? 1 : t;
    public static double Lerp(double a, double b, double t) => a + (b - a) * t;
    public static double Frac(double t) => t - Math.Floor(t);

    /// <summary>Maps <paramref name="t"/> from [a, b] onto [0, 1], clamped.</summary>
    public static double Span(double t, double a, double b) => Clamp01((t - a) / (b - a));

    public static double InOut(double t) { t = Clamp01(t); return t * t * (3 - 2 * t); }
    public static double InOutCubic(double t)
    {
        t = Clamp01(t);
        return t < 0.5 ? 4 * t * t * t : 1 - Math.Pow(-2 * t + 2, 3) / 2;
    }
    public static double OutCubic(double t) { t = Clamp01(t); var u = 1 - t; return 1 - u * u * u; }
    public static double InCubic(double t) { t = Clamp01(t); return t * t * t; }
    public static double OutBack(double t)
    {
        t = Clamp01(t);
        const double c1 = 1.70158, c3 = c1 + 1;
        var u = t - 1;
        return 1 + c3 * u * u * u + c1 * u * u;
    }

    /// <summary>Sine of a value measured in whole turns (1 = one full cycle).</summary>
    public static double Sin(double turns) => Math.Sin(turns * Tau);
    public static double Cos(double turns) => Math.Cos(turns * Tau);

    /// <summary>Half sine: 0 → 1 → 0 as t goes 0 → 1.</summary>
    public static double Arc(double t) => Math.Sin(Clamp01(t) * Math.PI);

    /// <summary>Exponential decay starting at 1 when t = 0; zero before that.</summary>
    public static double Decay(double t, double rate) => t < 0 ? 0 : Math.Exp(-t * rate);

    /// <summary>Wraps an angle in degrees to (-180, 180].</summary>
    public static double WrapDegrees(double d)
    {
        d %= 360;
        if (d > 180) d -= 360;
        if (d <= -180) d += 360;
        return d;
    }
}
