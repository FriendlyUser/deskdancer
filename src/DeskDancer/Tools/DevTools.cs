using System.Globalization;
using System.Text.Json;
using Avalonia;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using DeskDancer.Characters;
using DeskDancer.Engine;
using DeskDancer.Ui;

namespace DeskDancer.Tools;

/// <summary>Offline tools: contact sheets for checking the choreography, and the example image pack.</summary>
public static class DevTools
{
    public static int Run(CliOptions options)
    {
        if (options.RenderTest != null) RenderTest(options.RenderTest, options.Character);
        if (options.ExportSample != null) ExportSample(options.ExportSample);
        return 0;
    }

    static CharacterFrame FrameFor(in LimbPose limbs, string clip, double time, double beat, double energy) => new()
    {
        Clip = clip, ClipTime = time, Limbs = limbs, Time = time, Beat = beat, Energy = energy,
    };

    static void Label(DrawingContext ctx, string text, double x, double y, double size = 13)
    {
        var formatted = new FormattedText(text, CultureInfo.InvariantCulture, FlowDirection.LeftToRight,
            Typeface.Default, size, Brushes.White);
        ctx.DrawText(formatted, new Point(x, y));
    }

    // ---- Contact sheets ----

    static void RenderTest(string dir, string? characterId)
    {
        Directory.CreateDirectory(dir);
        var character = App.Instance.Library.Load(characterId ?? CharacterIds.BuiltIn);
        // An image pack decodes a clip when it is first shown and stands still meanwhile.
        // The sheets draw each clip once, so they need every one of them decoded beforehand.
        (character as SpriteCharacter)?.LoadAll();
        const int columns = 10, cellW = 170, cellH = 230, labelW = 110;
        const double h = 100;
        var backdrop = new SolidColorBrush(Color.FromRgb(0x3B, 0x42, 0x5C));
        var stripe = new SolidColorBrush(Color.FromRgb(0x46, 0x4E, 0x6B));
        var floorPen = new Pen(new SolidColorBrush(Color.FromArgb(0x50, 0xFF, 0xFF, 0xFF)), 1);

        var moves = Moves.All;
        for (int sheet = 0; sheet * 5 < moves.Count; sheet++)
        {
            var rows = moves.Skip(sheet * 5).Take(5).ToList();
            using var target = new RenderTargetBitmap(new PixelSize(labelW + columns * cellW, rows.Count * cellH));
            using (var ctx = target.CreateDrawingContext())
            {
                ctx.DrawRectangle(backdrop, null, new Rect(0, 0, target.PixelSize.Width, target.PixelSize.Height));
                for (int r = 0; r < rows.Count; r++)
                {
                    var move = rows[r];
                    if (r % 2 == 1) ctx.DrawRectangle(stripe, null, new Rect(0, r * cellH, target.PixelSize.Width, cellH));
                    Label(ctx, move.Name, 8, r * cellH + 8);
                    Label(ctx, $"{move.Beats:0} beats", 8, r * cellH + 26, 11);
                    for (int c = 0; c < columns; c++)
                    {
                        double t = move.Beats * c / columns + move.Beats / columns / 2;
                        var f = move.Eval(t, 1);
                        var body = f.Body;
                        body.X = 0;
                        var feet = new Point(labelW + c * cellW + cellW / 2.0, r * cellH + cellH - 22);
                        ctx.DrawLine(floorPen, new Point(feet.X - cellW / 2.0 + 6, feet.Y), new Point(feet.X + cellW / 2.0 - 6, feet.Y));
                        using (ctx.PushClip(new Rect(labelW + c * cellW, r * cellH, cellW, cellH)))
                        {
                            MateRenderer.DrawFloor(ctx, feet, h, character.AspectRatio, body.Y, 1, t);
                            int facing = body.Facing != 0 ? body.Facing : 1;
                            MateRenderer.DrawCharacter(ctx, character, h, feet, body, facing,
                                FrameFor(f.Limbs, move.Clip ?? "dance", t * 0.5, t, 1));
                        }
                    }
                }
            }
            target.Save(Path.Combine(dir, $"moves-{sheet + 1}.png"), new PngBitmapEncoderOptions());
        }

        RenderStates(dir, character, backdrop, floorPen);
        RenderHero(dir, character);
        Console.WriteLine($"Contact sheets written to {Path.GetFullPath(dir)}");
    }

    /// <summary>A large render of a few signature poses, used as the picture in the README.</summary>
    static void RenderHero(string dir, ICharacter character)
    {
        const int cellW = 350, height = 620;
        const double h = 290;
        (DanceMove? Move, double T, string Caption)[] poses =
        [
            (null, 0, "Idle"),
            (Moves.DiscoPoint, 0.6, "Disco Point"),
            (Moves.Backflip, 1.62, "Backflip"),
            (Moves.Moonwalk, 7.6, "Moonwalk"),
            (Moves.Sway, 0.5, "Sway"),
        ];

        using var target = new RenderTargetBitmap(new PixelSize(poses.Length * cellW, height));
        using (var ctx = target.CreateDrawingContext())
        {
            var gradient = new LinearGradientBrush
            {
                StartPoint = new RelativePoint(0, 0, RelativeUnit.Relative),
                EndPoint = new RelativePoint(0, 1, RelativeUnit.Relative),
                GradientStops = { new GradientStop(Color.FromRgb(0x1B, 0x1D, 0x3A), 0), new GradientStop(Color.FromRgb(0x2E, 0x2A, 0x5C), 1) },
            };
            ctx.DrawRectangle(gradient, null, new Rect(0, 0, target.PixelSize.Width, height));
            for (int i = 0; i < poses.Length; i++)
            {
                var (move, t, caption) = poses[i];
                var f = move?.Eval(t, 1) ?? MoveFrame.Neutral;
                var body = f.Body;
                body.X = 0;
                var feet = new Point(i * cellW + cellW / 2.0, height - 90);
                MateRenderer.DrawFloor(ctx, feet, h, character.AspectRatio, body.Y, move == null ? 0 : 1, t + i);
                MateRenderer.DrawCharacter(ctx, character, h, feet, body, body.Facing != 0 ? body.Facing : 1,
                    FrameFor(f.Limbs, move?.Clip ?? "idle", 0.4 + i, t, move == null ? 0 : 1));
                Label(ctx, caption, i * cellW + 20, height - 40, 17);
            }
        }
        target.Save(Path.Combine(dir, "hero.png"), new PngBitmapEncoderOptions());
    }

    /// <summary>Runs a real brain through each everyday state and draws what comes out.</summary>
    static void RenderStates(string dir, ICharacter character, IBrush backdrop, IPen floorPen)
    {
        const int cellW = 200, cellH = 250;
        const double h = 130;
        double now = 0;
        var clock = new BeatClock { TimeSource = () => now };
        var settings = new Settings { Persist = false, Wander = false, AutoDance = false };
        var faces = Enum.GetValues<Face>();
        var states = new (string Name, Action<MateBrain> Setup, double Seconds)[]
        {
            ("idle", _ => { }, 1.0),
            ("walk", _ => settings.Wander = true, 0),
            ("sit", b => b.Sit(), 1.0),
            ("sleep", b => b.Sleep(), 2.6),
            ("drag", b => { b.BeginDrag(); b.DragTo(b.FootX + 260, b.FootY - 200); }, 0.25),
            ("fall", b => { b.Place(600, 300); b.Drop(240, 0); }, 0.22),
            ("poke", b => b.Poke(), 0.2),
            ("party", _ => { }, 1.3),
        };

        using var target = new RenderTargetBitmap(new PixelSize(Math.Max(faces.Length, states.Length) * cellW, cellH * 2));
        using (var ctx = target.CreateDrawingContext())
        {
            ctx.DrawRectangle(backdrop, null, new Rect(0, 0, target.PixelSize.Width, target.PixelSize.Height));

            for (int i = 0; i < faces.Length; i++)
            {
                var limbs = LimbPose.Rest;
                limbs.Face = faces[i];
                var feet = new Point(i * cellW + cellW / 2.0, cellH - 30);
                Label(ctx, faces[i].ToString(), i * cellW + 8, 8);
                ctx.DrawLine(floorPen, new Point(feet.X - 80, feet.Y), new Point(feet.X + 80, feet.Y));
                MateRenderer.DrawFloor(ctx, feet, h, character.AspectRatio, 0, 0, 0);
                MateRenderer.DrawCharacter(ctx, character, h, feet, BodyPose.Identity, 1, FrameFor(limbs, "idle", 0.5, 0, 0));
            }

            for (int i = 0; i < states.Length; i++)
            {
                var (name, setup, seconds) = states[i];
                settings.Wander = false;
                var conductor = new Conductor(clock);
                var brain = new MateBrain(clock, conductor, settings, character, new Random(7))
                {
                    H = h, Left = 0, Right = 1200, Top = 0, Floor = 800,
                };
                brain.Place(600, 800);
                void Advance(double span)
                {
                    for (double t = 0; t < span; t += 1.0 / 60)
                    {
                        now += 1.0 / 60;
                        brain.Update(1.0 / 60);
                    }
                }
                Advance(0.1);
                setup(brain);
                if (name == "party") conductor.SetParty(true);
                if (name == "walk")
                {
                    // Idle until the brain decides to wander, then catch it mid-stride.
                    for (int guard = 0; guard < 3000 && brain.State != MateState.Walk; guard++) Advance(1.0 / 60);
                    Advance(0.7);
                }
                else
                {
                    Advance(seconds);
                }

                // Draw relative to where the feet ended up, as the live window does.
                var feet = new Point(i * cellW + cellW / 2.0, cellH + cellH - 30);
                double floorY = feet.Y + (brain.Floor - brain.FootY) * 0.5;
                Label(ctx, $"{name} -> {brain.State}", i * cellW + 8, cellH + 8);
                ctx.DrawLine(floorPen, new Point(feet.X - 80, floorY), new Point(feet.X + 80, floorY));
                using (ctx.PushClip(new Rect(i * cellW, cellH, cellW, cellH)))
                {
                    MateRenderer.DrawFloor(ctx, new Point(feet.X, floorY), h, character.AspectRatio,
                        Math.Max(brain.Body.Y, (brain.Floor - brain.FootY) / brain.H), brain.Energy, brain.Beat);
                    MateRenderer.DrawCharacter(ctx, character, h, feet, brain.Body, brain.Facing,
                        FrameFor(brain.Limbs, brain.Clip, brain.ClipTime, brain.Beat, brain.Energy) with { Trail = brain.Trail });
                    foreach (var p in brain.Particles.Items)
                        MateRenderer.DrawParticle(ctx, p, new Point(feet.X + (p.X - brain.FootX), feet.Y + (p.Y - brain.FootY)), h);
                }
            }
        }
        target.Save(Path.Combine(dir, "states.png"), new PngBitmapEncoderOptions());
    }

    // ---- Example image pack ----

    const int CellW = 300, CellH = 330;
    const double SpriteH = 250;

    delegate MoveFrame Pose(double phase);

    static void DrawCell(DrawingContext ctx, ICharacter character, int column, int row, MoveFrame f, double phase)
    {
        var body = f.Body;
        body.X = 0;
        var feet = new Point(column * CellW + CellW / 2.0, row * CellH + CellH - 16);
        using (ctx.PushClip(new Rect(column * CellW, row * CellH, CellW, CellH)))
            MateRenderer.DrawCharacter(ctx, character, SpriteH, feet, body, 1, FrameFor(f.Limbs, "idle", phase * 2, phase * 4, 0.6));
    }

    static void SaveSheet(ICharacter character, string path, int columns, int rows, Pose pose)
    {
        int count = columns * rows;
        using var target = new RenderTargetBitmap(new PixelSize(columns * CellW, rows * CellH));
        using (var ctx = target.CreateDrawingContext())
            for (int i = 0; i < count; i++)
                DrawCell(ctx, character, i % columns, i / columns, pose((double)i / count), (double)i / count);
        target.Save(path, new PngBitmapEncoderOptions());
    }

    static void SaveFrames(ICharacter character, string folder, int count, Pose pose)
    {
        Directory.CreateDirectory(folder);
        for (int i = 0; i < count; i++)
            SaveSheet(character, Path.Combine(folder, $"{i + 1:000}.png"), 1, 1, _ => pose((double)i / count));
    }

    /// <summary>
    /// Renders the built-in character to image files laid out exactly like a pack the user
    /// would make: a folder of frames, sprite sheets, single stills and a character.json.
    /// </summary>
    static void ExportSample(string dir)
    {
        Directory.CreateDirectory(dir);
        var remix = new RemixCharacter();

        // idle/ - a folder of numbered frames: breathing, with one blink.
        SaveFrames(remix, Path.Combine(dir, "idle"), 12, phase =>
        {
            var f = MoveFrame.Neutral;
            double breath = Math.Sin(phase * Ease.Tau);
            f.Body.Squash(0.014 * breath);
            f.Limbs.ArmL = f.Limbs.ArmR = 12 + 3 * breath;
            f.Limbs.EyeOpen = phase is > 0.7 and < 0.8 ? 0.1 : 1;
            return f;
        });

        // walk_8x1.png - a sprite sheet, 8 columns by 1 row.
        SaveSheet(remix, Path.Combine(dir, "walk_8x1.png"), 8, 1, phase =>
        {
            var f = MoveFrame.Neutral;
            double s = Math.Sin(phase * Ease.Tau);
            f.Body.Y = 0.025 * Math.Abs(s);
            f.Body.Lean = 3;
            f.Limbs.LegL = 3 + 10 * Math.Max(0, s); f.Limbs.LiftL = 0.5 * Math.Max(0, s);
            f.Limbs.LegR = 3 + 10 * Math.Max(0, -s); f.Limbs.LiftR = 0.5 * Math.Max(0, -s);
            f.Limbs.ArmL = 16 + 14 * s; f.Limbs.ArmR = 16 - 14 * s;
            f.Limbs.ElbowL = f.Limbs.ElbowR = 28;
            f.Limbs.LookX = 0.7;
            return f;
        });

        // Single stills.
        MoveFrame Seated(Face face, double eyes, double tilt)
        {
            var f = MoveFrame.Neutral;
            f.Limbs.Crouch = 1;
            f.Limbs.LegL = f.Limbs.LegR = 68;
            f.Limbs.ArmL = f.Limbs.ArmR = 28;
            f.Limbs.ElbowL = f.Limbs.ElbowR = -40;
            f.Limbs.Face = face;
            f.Limbs.EyeOpen = eyes;
            f.Limbs.HeadTilt = tilt;
            return f;
        }
        SaveSheet(remix, Path.Combine(dir, "sit.png"), 1, 1, _ => Seated(Face.Normal, 1, 0));
        SaveSheet(remix, Path.Combine(dir, "sleep.png"), 1, 1, _ => Seated(Face.Sleepy, 0, 13));
        SaveSheet(remix, Path.Combine(dir, "drag.png"), 1, 1, _ =>
        {
            var f = MoveFrame.Neutral;
            f.Body.Squash(-0.04);
            f.Limbs.ArmL = f.Limbs.ArmR = 30;
            f.Limbs.LegL = f.Limbs.LegR = 8;
            f.Limbs.LiftL = f.Limbs.LiftR = 0.15;
            f.Limbs.Face = Face.Wide;
            return f;
        });
        SaveSheet(remix, Path.Combine(dir, "fall_4x1.png"), 4, 1, phase =>
        {
            var f = MoveFrame.Neutral;
            double a = phase * Ease.Tau;
            f.Limbs.ArmL = 150 + 20 * Math.Sin(a); f.Limbs.ArmR = 150 + 20 * Math.Sin(a + 2);
            f.Limbs.LegL = 10 + 10 * Math.Sin(a); f.Limbs.LegR = 10 + 10 * Math.Sin(a + 3);
            f.Limbs.Face = Face.Wide;
            return f;
        });

        // Anything whose name starts with "dance" is offered as a dance move.
        SaveSheet(remix, Path.Combine(dir, "dance_groove_8x2.png"), 8, 2, phase => Moves.DiscoPoint.Eval(phase * 4, 1));
        SaveSheet(remix, Path.Combine(dir, "dance_star_jump_6x1.png"), 6, 1, phase => Moves.StarJump.Eval(phase, 1));

        var manifest = new Dictionary<string, object>
        {
            ["name"] = "Remix (example image pack)",
            ["height"] = 150,
            ["facing"] = "right",
            ["fps"] = 8,
            ["clips"] = new Dictionary<string, object>
            {
                ["idle"] = new Dictionary<string, object> { ["folder"] = "idle", ["fps"] = 6 },
                ["walk"] = new Dictionary<string, object> { ["file"] = "walk_8x1.png", ["fps"] = 12 },
                ["fall"] = new Dictionary<string, object> { ["file"] = "fall_4x1.png", ["fps"] = 12 },
                ["dance_groove"] = new Dictionary<string, object> { ["file"] = "dance_groove_8x2.png", ["name"] = "Groove", ["fps"] = 8 },
                ["dance_star_jump"] = new Dictionary<string, object> { ["file"] = "dance_star_jump_6x1.png", ["name"] = "Star Jump (frames)", ["fps"] = 12 },
            },
        };
        File.WriteAllText(Path.Combine(dir, SpritePackLoader.ManifestName),
            JsonSerializer.Serialize(manifest, new JsonSerializerOptions { WriteIndented = true }) + Environment.NewLine);

        Console.WriteLine($"Example image pack written to {Path.GetFullPath(dir)}");
    }
}
