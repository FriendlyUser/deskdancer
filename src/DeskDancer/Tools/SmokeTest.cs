using System.Diagnostics;
using Avalonia;
using Avalonia.Threading;
using DeskDancer.Engine;
using DeskDancer.Platform;
using DeskDancer.Ui;

namespace DeskDancer.Tools;

/// <summary>
/// Drives the real app through its features for a few seconds and exits with 0 only if
/// every step ran, the windows kept drawing frames and nothing threw. This is what CI
/// runs on Windows and Linux.
/// </summary>
public static class SmokeTest
{
    public static void Start(App app, CliOptions options)
    {
        string outDir = options.Out ?? Path.Combine(Path.GetTempPath(), "deskdancer-smoke");
        Directory.CreateDirectory(outDir);
        var report = new List<string>();
        var watch = Stopwatch.StartNew();
        double total = Math.Max(6, options.Seconds);
        bool finished = false;

        void Note(string line)
        {
            report.Add($"[{watch.Elapsed.TotalSeconds,5:0.00}s] {line}");
            Console.WriteLine(report[^1]);
        }

        void Finish(bool pass, string reason)
        {
            if (finished) return;
            finished = true;
            Note((pass ? "PASS: " : "FAIL: ") + reason);
            File.WriteAllLines(Path.Combine(outDir, "smoke-result.txt"), report);
            app.Quit(pass ? 0 : 1);
        }

        void Snap(MateWindow mate, string name)
        {
            mate.Snapshot(Path.Combine(outDir, name + ".png"));
            var b = mate.Brain;
            Note($"snapshot {name}: state={b.State} move={b.CurrentMoveName ?? "-"} foot=({b.FootX:0},{b.FootY:0}) window={mate.Position} frames={mate.FrameCount}");
        }

        // Keep the mate where it lands so the checks below are repeatable.
        app.Settings.Wander = false;
        app.Settings.AutoDance = false;

        MateWindow First() => app.Mates[0];
        string? spritePack = app.Library.Available.FirstOrDefault(c => c.Folder != null)?.Id;

        // Each step fires once, at a fraction of the total run time.
        var steps = new List<(double At, string Name, Action Run)>
        {
            (0.06, "started", () =>
            {
                if (app.Mates.Count != 1) throw new InvalidOperationException($"expected 1 mate, found {app.Mates.Count}");
                Note($"characters: {string.Join(", ", app.Library.Available.Select(c => c.Id))}");
                var screen = First().Screens.Primary ?? First().Screens.All.FirstOrDefault();
                Note($"screens: {First().Screens.All.Count}, work area: {screen?.WorkingArea}, scaling {First().RenderScaling}");
            }),
            (0.16, "landed", () =>
            {
                var b = First().Brain;
                if (Math.Abs(b.FootY - b.Floor) > 2) throw new InvalidOperationException($"mate did not land: footY={b.FootY} floor={b.Floor} state={b.State}");
                Snap(First(), "1-landed");
            }),
            (0.17, "click-through", () =>
            {
                var mate = First();
                if (!ClickThrough.Supported)
                {
                    Note("click-through is not supported here; skipped");
                    return;
                }
                if (mate.SolidArea is not { } solid) throw new InvalidOperationException("the click-through area was not applied");
                Note($"clickable area {solid} inside a {mate.Bounds.Width:0}x{mate.Bounds.Height:0} window");

                // Where the system can tell us, prove it: the character is hit, the empty corner is not.
                var origin = mate.Position;
                var onCharacter = new PixelPoint(origin.X + solid.X + solid.Width / 2, origin.Y + solid.Y + solid.Height / 2);
                var onEmptyCorner = new PixelPoint(origin.X + 3, origin.Y + 3);
                if (ClickThrough.IsWindowAt(mate, onCharacter) is { } hit && ClickThrough.IsWindowAt(mate, onEmptyCorner) is { } miss)
                {
                    Note($"hit test: on character={hit}, on empty corner={miss}");
                    if (!hit) throw new InvalidOperationException("the character itself is not clickable");
                    if (miss) throw new InvalidOperationException("clicks on the empty corner are not passing through");
                }
            }),
            (0.18, "backflip", () => First().Brain.StartDance([Moves.Backflip, Moves.Twirl])),
            (0.27, "mid-dance", () =>
            {
                if (!First().Brain.IsDancing) throw new InvalidOperationException("mate is not dancing");
                Snap(First(), "2-dancing");
            }),
            (0.33, "second mate + party", () =>
            {
                var second = app.AddMate(spritePack ?? CharacterIds.BuiltIn);
                Note($"second mate uses '{second.Character.Id}' ({second.Character.DisplayName})");
                if (spritePack != null && app.Library.ErrorFor(spritePack) is { } error)
                    throw new InvalidOperationException($"image pack '{spritePack}' failed to load: {error}");
                app.SetParty(true);
            }),
            (0.50, "party", () =>
            {
                if (app.Mates.Any(m => !m.Brain.IsDancing)) throw new InvalidOperationException("not every mate joined the party");
                Snap(app.Mates[0], "3-party-a");
                Snap(app.Mates[1], "3-party-b");
            }),
            (0.55, "party off, resize, menu", () =>
            {
                app.SetParty(false);
                app.SetTempo(140);
                app.Mates[1].SetScale(1.5);
                First().OpenMenu();
            }),
            (0.63, "menu open", () =>
            {
                if (First().ContextMenu?.IsOpen != true) throw new InvalidOperationException("context menu did not open");
                int entries = First().ContextMenu!.Items.Count;
                Note($"menu has {entries} entries");
                if (entries < 10) throw new InvalidOperationException("context menu was not populated");
                First().ContextMenu!.Close();
            }),
            (0.66, "drag and throw", () =>
            {
                var b = First().Brain;
                b.BeginDrag();
                b.DragTo(b.FootX + 60, b.FootY - 220);
            }),
            (0.70, "release", () =>
            {
                var b = First().Brain;
                if (b.State != MateState.Drag) throw new InvalidOperationException($"expected Drag, was {b.State}");
                Snap(First(), "4-carried");
                b.EndDrag();
            }),
            (0.86, "sit, swap character", () =>
            {
                var b = First().Brain;
                if (Math.Abs(b.FootY - b.Floor) > 2) throw new InvalidOperationException("mate did not fall back to the floor");
                b.Sit();
                app.Mates[1].SetCharacter(CharacterIds.BuiltIn);
                app.ReloadCharacters();
            }),
            (0.94, "remove mate", () =>
            {
                Snap(First(), "5-sitting");
                app.RemoveMate(app.Mates[1]);
                if (app.Mates.Count != 1) throw new InvalidOperationException("second mate was not removed");
            }),
        };

        int next = 0;
        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(50) };
        timer.Tick += (_, _) =>
        {
            if (finished) return;
            double at = watch.Elapsed.TotalSeconds / total;
            try
            {
                while (next < steps.Count && at >= steps[next].At)
                {
                    Note($"step: {steps[next].Name}");
                    steps[next++].Run();
                }
                if (at >= 1)
                {
                    timer.Stop();
                    int frames = First().FrameCount;
                    if (frames < total * 5) Finish(false, $"only {frames} frames were drawn in {total:0}s");
                    else Finish(true, $"{steps.Count} steps, {frames} frames ({frames / watch.Elapsed.TotalSeconds:0} fps)");
                }
            }
            catch (Exception ex)
            {
                timer.Stop();
                Finish(false, ex.ToString());
            }
        };
        Dispatcher.UIThread.UnhandledException += (_, e) =>
        {
            e.Handled = true;
            Finish(false, "unhandled UI exception: " + e.Exception);
        };
        timer.Start();
    }
}
