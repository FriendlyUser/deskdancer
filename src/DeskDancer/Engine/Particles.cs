namespace DeskDancer.Engine;

public enum ParticleKind { Note, Star, Heart, Zzz, Confetti, Ring }

/// <summary>A particle in screen pixels, so it stays put while the mate moves on.</summary>
public struct Particle
{
    public ParticleKind Kind;
    public double X, Y, Vx, Vy;
    /// <summary>Downward acceleration in pixels per second squared.</summary>
    public double Gravity;
    public double Life, MaxLife;
    public double Rot, VRot;
    /// <summary>Size in character heights.</summary>
    public double Size;
    public uint Color;
    /// <summary>Phase offset for the sideways drift of floating particles.</summary>
    public double Wobble;

    public readonly double Age => 1 - Life / MaxLife;
}

public sealed class ParticleSystem
{
    const int Max = 180;

    public static readonly uint[] Neon =
    [
        0xFFFF5FD2, 0xFF3CF2FF, 0xFFFFE45C, 0xFF8CFF7A, 0xFFFF8A5C, 0xFFB69CFF,
    ];

    public List<Particle> Items { get; } = new(64);

    public void Add(in Particle p)
    {
        if (Items.Count < Max) Items.Add(p);
    }

    public void Update(double dt)
    {
        for (int i = Items.Count - 1; i >= 0; i--)
        {
            var p = Items[i];
            p.Life -= dt;
            if (p.Life <= 0)
            {
                Items.RemoveAt(i);
                continue;
            }
            p.Vy += p.Gravity * dt;
            p.X += p.Vx * dt;
            p.Y += p.Vy * dt;
            p.Rot += p.VRot * dt;
            if (p.Kind is ParticleKind.Confetti)
            {
                // Air resistance makes confetti flutter down instead of dropping like a stone.
                p.Vx *= Math.Exp(-1.6 * dt);
                p.Vy *= Math.Exp(-1.2 * dt);
            }
            Items[i] = p;
        }
    }

    public void Clear() => Items.Clear();
}
