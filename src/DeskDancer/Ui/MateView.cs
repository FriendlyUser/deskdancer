using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using DeskDancer.Characters;
using DeskDancer.Engine;

namespace DeskDancer.Ui;

/// <summary>The drawing surface inside a mate's window.</summary>
public sealed class MateView : Control
{
    public MateBrain? Brain { get; set; }
    public ICharacter? Character { get; set; }
    /// <summary>Character height in device-independent pixels.</summary>
    public double CharacterHeight { get; set; } = 150;
    /// <summary>Screen pixels per device-independent pixel.</summary>
    public double Scaling { get; set; } = 1;
    /// <summary>Top-left corner of the window in screen pixels.</summary>
    public double OriginX { get; set; }
    public double OriginY { get; set; }

    public MateView()
    {
        // Mouse input is handled by the window, which is hit-testable everywhere.
        IsHitTestVisible = false;
    }

    public override void Render(DrawingContext ctx)
    {
        var brain = Brain;
        var character = Character;
        if (brain == null || character == null) return;

        double s = Scaling <= 0 ? 1 : Scaling, h = CharacterHeight;
        var feet = new Point((brain.FootX - OriginX) / s, (brain.FootY - OriginY) / s);

        bool airborne = brain.State is MateState.Drag or MateState.Fall;
        double floorY = airborne ? (brain.Floor - OriginY) / s : feet.Y;
        double lift = airborne ? Math.Max(0, (brain.Floor - brain.FootY) / brain.H) : brain.Body.Y;
        MateRenderer.DrawFloor(ctx, new Point(feet.X, floorY), h, character.AspectRatio, lift, brain.Energy, brain.Beat);

        var frame = new CharacterFrame
        {
            Clip = brain.Clip,
            ClipTime = brain.ClipTime,
            Limbs = brain.Limbs,
            Time = brain.Time,
            Beat = brain.Beat,
            Energy = brain.Energy,
            Trail = brain.Trail,
        };
        MateRenderer.DrawCharacter(ctx, character, h, feet, brain.Body, brain.Facing, frame);

        var particles = brain.Particles.Items;
        for (int i = 0; i < particles.Count; i++)
        {
            var p = particles[i];
            MateRenderer.DrawParticle(ctx, p, new Point((p.X - OriginX) / s, (p.Y - OriginY) / s), h);
        }
    }
}
