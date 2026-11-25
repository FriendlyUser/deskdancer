using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Platform;
using Avalonia.Threading;
using DeskDancer.Engine;
using DeskDancer.Platform;
using DeskDancer.Ui;

namespace DeskDancer.Tools;

/// <summary>
/// Drives the real app through its features for a few seconds and exits with 0 only if
/// every step ran, the windows kept drawing frames and nothing threw. This is what CI
/// runs on Windows, Linux and macOS.
/// </summary>
public static class SmokeTest
{
    /// <summary>
    /// One thing the test does, once the run is <paramref name="At"/> of the way through. A
    /// step that needs the app to have got somewhere first says what it is still waiting for,
    /// or null when that is nothing. It is held until then, and fails the run with those
    /// words if it is kept waiting too long.
    /// </summary>
    sealed record Step(double At, string Name, Action Run, Func<string?>? WaitingFor = null);

    /// <summary>Seconds a step may be kept waiting, and seconds the first frame may take to appear.</summary>
    const double Patience = 5, StartUpLimit = 30;

    public static void Start(App app, CliOptions options)
    {
        string outDir = options.Out ?? Path.Combine(Path.GetTempPath(), "deskdancer-smoke");
        Directory.CreateDirectory(outDir);
        var report = new List<string>();
        var watch = Stopwatch.StartNew();
        double total = Math.Max(6, options.Seconds);
        bool finished = false;
        Window? backdrop = null;

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
            backdrop?.Close();
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

        // Where the screen can be read back (Windows, and macOS once screenshots have been
        // allowed), put a plain backdrop in a colour the characters never use behind
        // everything. If that colour shows through the empty part of a mate's window, the
        // window really is transparent on this machine.
        ScreenProbe.UseScreenshots = options.Screenshots;
        var backdropColour = Color.FromRgb(128, 96, 16);
        // What that colour comes out as on screen. A Mac's screenshot is in the display's own
        // colours, which are near the ones asked for but not the same.
        var backdropSeen = backdropColour;
        if (ScreenProbe.Supported)
        {
            backdrop = new Window
            {
                Title = "DeskDancer smoke test backdrop",
                Background = new SolidColorBrush(backdropColour),
                WindowDecorations = WindowDecorations.None,
                WindowState = OperatingSystem.IsMacOS() ? WindowState.Normal : WindowState.Maximized,
                ShowInTaskbar = false,
                ShowActivated = false,
            };
            // On a Mac it is laid over the work area by hand.
            if (OperatingSystem.IsMacOS() && MainScreen() is { } screen)
            {
                backdrop.WindowStartupLocation = WindowStartupLocation.Manual;
                backdrop.Position = screen.WorkingArea.Position;
                backdrop.Width = screen.WorkingArea.Width / screen.Scaling;
                backdrop.Height = screen.WorkingArea.Height / screen.Scaling;
            }
            backdrop.Show();
        }

        // Has a fresh look at the screen before pixels are read off it. On a Mac that is a
        // screenshot, which is kept with the results as a picture of the desktop, and what the
        // backdrop looks like in it is read from a spot that shows nothing else.
        void LookAtScreen(string picture)
        {
            var screen = MainScreen() ?? throw new InvalidOperationException("there is no screen");
            if (ScreenProbe.Look(screen, Path.Combine(outDir, picture + ".png")) is { } problem)
                throw new InvalidOperationException("could not look at the screen: " + problem);
            if (!OperatingSystem.IsMacOS()) return;
            var plainSpot = new PixelPoint(screen.WorkingArea.X + 24, screen.WorkingArea.Y + 24);
            if (ScreenProbe.PixelAt(plainSpot) is not { } plain) throw new InvalidOperationException("could not read the screenshot");
            if (!ScreenProbe.Near(plain, backdropColour, 72))
                throw new InvalidOperationException($"the screenshot shows {plain} where the backdrop ({backdropColour}) should be, so it is not showing this program's windows. Is screen recording allowed for whatever started it?");
            backdropSeen = plain;
        }

        MateWindow First() => app.Mates[0];
        Screen? MainScreen() => First().Screens.Primary ?? First().Screens.All.FirstOrDefault();

        // The image packs that are installed, and a check that a mate really became the
        // character it was asked to be, not the built-in one standing in for a broken pack.
        var packs = app.Library.Available.Where(c => c.Folder != null).Select(c => c.Id).ToList();

        // Load them all now. A big pack takes a second or more, and the steps below are on a
        // clock: loaded on the spot, a new mate would still be dropping in when it is checked.
        foreach (string id in packs)
        {
            var loading = Stopwatch.StartNew();
            var character = app.Library.Load(id);
            Note($"loaded '{id}' in {loading.ElapsedMilliseconds} ms; its own dances: " +
                 (character.DanceClips.Count == 0 ? "none" : string.Join(", ", character.DanceClips.Select(d => d.Name))));
        }
        bool Same(string a, string b) => a.Equals(b, StringComparison.OrdinalIgnoreCase);
        void MustBe(MateWindow mate, string id)
        {
            if (app.Library.ErrorFor(id) is { } error)
                throw new InvalidOperationException($"character '{id}' failed to load: {error}");
            if (!Same(mate.Character.Id, id))
                throw new InvalidOperationException($"asked for character '{id}' but got '{mate.Character.Id}'");
        }

        // Landing can end in a bounce, which touches the floor on its way back up.
        string? NotOnTheFloor(MateWindow mate)
        {
            var b = mate.Brain;
            return b.State != MateState.Fall && Math.Abs(b.FootY - b.Floor) <= 2 ? null : $"footY={b.FootY:0.#} floor={b.Floor:0.#} state={b.State}";
        }

        string? AreaNotApplied() => ClickThrough.Supported && First().SolidArea == null ? "the click-through area was not applied" : null;

        // Two spots on the screen inside the first mate's window: the middle of the rectangle
        // that holds the character, and a corner of the window that holds nothing.
        PixelPoint OnCharacter()
        {
            var solid = First().SolidArea!.Value;
            return new PixelPoint(First().Position.X + solid.X + solid.Width / 2, First().Position.Y + solid.Y + solid.Height / 2);
        }
        PixelPoint OnEmptyCorner() => new(First().Position.X + 3, First().Position.Y + 3);

        // How long the program has been running. Not every system will say.
        double? SinceLaunch()
        {
            try
            {
                return (DateTime.Now - Process.GetCurrentProcess().StartTime).TotalSeconds;
            }
            catch (Exception ex) when (ex is InvalidOperationException or NotSupportedException or System.ComponentModel.Win32Exception)
            {
                return null;
            }
        }

        // The run is timed from the first frame drawn, and each step fires once, at a fraction
        // of its length. Nothing here relies on how long the app takes to do something: a
        // step that follows on from something the app does waits for it.
        var steps = new List<Step>
        {
            new(0.06, "started", () =>
            {
                if (app.Mates.Count != 1) throw new InvalidOperationException($"expected 1 mate, found {app.Mates.Count}");
                Note($"settings folder: {Settings.ConfigDir}");
                Note($"characters: {string.Join(", ", app.Library.Available.Select(c => c.Id))} (shipped ones from {Characters.CharacterLibrary.AppFolder})");
                foreach (string id in packs)
                    if (app.Library.ErrorFor(id) is { } error)
                        throw new InvalidOperationException($"character '{id}' failed to load: {error}");
                string wanted = First().Settings.Character;
                Note($"first mate is '{First().Character.Id}' ({First().Character.DisplayName})");
                if (Same(wanted, CharacterIds.BuiltIn) || packs.Any(p => Same(p, wanted))) MustBe(First(), wanted);
                else Note($"character '{wanted}' is not installed; the built-in one is standing in");
                Note($"screens: {First().Screens.All.Count}, work area: {MainScreen()?.WorkingArea}, scaling {First().RenderScaling}");
            }),
            new(0.16, "landed", () => Snap(First(), "1-landed"),
                WaitingFor: () => NotOnTheFloor(First()) is { } where ? "mate did not land: " + where : null),
            new(0.17, "click-through", () =>
            {
                var mate = First();
                if (!ClickThrough.Supported)
                {
                    Note("click-through is not supported here; skipped");
                    return;
                }
                var solid = mate.SolidArea!.Value;
                Note($"clickable area {solid} inside a {mate.Bounds.Width:0}x{mate.Bounds.Height:0} window");

                // Where the system can tell us, prove it: the character is hit, the empty corner
                // is not. (On macOS that depends on where the pointer is; see further down.)
                if (!OperatingSystem.IsMacOS() && ClickThrough.IsWindowAt(mate, OnCharacter()) is { } hit && ClickThrough.IsWindowAt(mate, OnEmptyCorner()) is { } miss)
                {
                    Note($"hit test: on character={hit}, on empty corner={miss}");
                    if (!hit) throw new InvalidOperationException("the character itself is not clickable");
                    if (miss) throw new InvalidOperationException("clicks on the empty corner are not passing through");
                }

                if (backdrop == null) return;
                // Read the real screen. Just inside the clickable rectangle's top corner there is
                // window but no character, so the backdrop must show through it.
                LookAtScreen("desktop-1-standing");
                var emptySpot = new PixelPoint(mate.Position.X + solid.X + 6, mate.Position.Y + solid.Y + 6);
                var b = mate.Brain;
                int painted = 0, samples = 0;
                for (double up = 0.1; up < 0.95; up += 0.1, samples++)
                {
                    var onBody = new PixelPoint((int)b.FootX, (int)(b.FootY - up * b.H));
                    if (ScreenProbe.PixelAt(onBody) is { } c && !ScreenProbe.Near(c, backdropSeen)) painted++;
                }
                var seen = ScreenProbe.PixelAt(emptySpot);
                Note($"on screen: empty part of the window shows {seen} (backdrop is {backdropSeen}); character painted at {painted} of {samples} sample points");
                if (seen is not { } colour) throw new InvalidOperationException("could not read the screen");
                if (!ScreenProbe.Near(colour, backdropSeen)) throw new InvalidOperationException("the window is not transparent: something is painted where it should be see-through");
                if (painted < 3) throw new InvalidOperationException("the character is not visible on screen");
            }, WaitingFor: AreaNotApplied),
            new(0.18, "backflip", () => First().Brain.StartDance([Moves.Backflip, Moves.Twirl])),
            new(0.27, "mid-dance", () =>
            {
                if (!First().Brain.IsDancing) throw new InvalidOperationException("mate is not dancing");
                Snap(First(), "2-dancing");

                if (backdrop == null) return;
                // While dancing the whole window is in play, so its far corners must be see-through too.
                LookAtScreen("desktop-2-dancing");
                var mate = First();
                var size = PixelSize.FromSize(mate.Bounds.Size, mate.RenderScaling);
                var left = ScreenProbe.PixelAt(new PixelPoint(mate.Position.X + 4, mate.Position.Y + 4));
                var right = ScreenProbe.PixelAt(new PixelPoint(mate.Position.X + size.Width - 5, mate.Position.Y + 4));
                Note($"on screen while dancing: window corners show {left} and {right}");
                bool clear = left is { } l && ScreenProbe.Near(l, backdropSeen) || right is { } r && ScreenProbe.Near(r, backdropSeen);
                if (!clear) throw new InvalidOperationException("the window is not transparent while dancing");
            }),
            new(0.33, "second mate + party", () =>
            {
                // Between them the two mates cover both kinds of character: the one drawn in
                // code and an image pack.
                string id = First().Character.IsRigged ? packs.FirstOrDefault() ?? CharacterIds.BuiltIn : CharacterIds.BuiltIn;
                var second = app.AddMate(id);
                Note($"second mate uses '{second.Character.Id}' ({second.Character.DisplayName})");
                MustBe(second, id);
                app.SetParty(true);
            }),
            new(0.50, "party", () =>
            {
                Snap(app.Mates[0], "3-party-a");
                Snap(app.Mates[1], "3-party-b");
                // On a Mac this leaves a picture of the party among the results.
                if (backdrop != null) LookAtScreen("desktop-3-party");
            }, WaitingFor: () => app.Mates.All(m => m.Brain.IsDancing) ? null
                : "not every mate joined the party: they are " + string.Join(", ", app.Mates.Select(m => m.Brain.State))),
            new(0.55, "party off, resize, menu", () =>
            {
                app.SetParty(false);
                app.SetTempo(140);
                app.Mates[1].SetScale(1.5);
                First().OpenMenu();
            }),
            new(0.63, "menu open", () =>
            {
                int entries = First().ContextMenu!.Items.Count;
                Note($"menu has {entries} entries");
                if (entries < 10) throw new InvalidOperationException("context menu was not populated");
                First().ContextMenu!.Close();
            }, WaitingFor: () => First().ContextMenu?.IsOpen == true ? null : "context menu did not open"),
            new(0.66, "drag and throw", () =>
            {
                var b = First().Brain;
                b.BeginDrag();
                b.DragTo(b.FootX + 60, b.FootY - 220);
            }),
            new(0.70, "release", () =>
            {
                var b = First().Brain;
                if (b.State != MateState.Drag) throw new InvalidOperationException($"expected Drag, was {b.State}");
                Snap(First(), "4-carried");
                b.EndDrag();
            }),
            new(0.86, "sit, swap character", () =>
            {
                First().Brain.Sit();

                // Turn the second mate into a character neither mate has been yet, where there
                // is one, so that every kind that is installed gets loaded and drawn.
                var second = app.Mates[1];
                string id = packs.FirstOrDefault(p => !Same(p, First().Character.Id) && !Same(p, second.Character.Id))
                            ?? (second.Character.IsRigged ? packs.FirstOrDefault() : null)
                            ?? CharacterIds.BuiltIn;
                second.SetCharacter(id);
                app.ReloadCharacters();
                Note($"second mate is now '{second.Character.Id}' ({second.Character.DisplayName})");
                MustBe(second, id);
            }, WaitingFor: () => NotOnTheFloor(First()) is { } where ? "mate did not fall back to the floor: " + where : null),
            new(0.94, "remove mate", () =>
            {
                Snap(First(), "5-sitting");
                Snap(app.Mates[1], "5-swapped");
                app.RemoveMate(app.Mates[1]);
                if (app.Mates.Count != 1) throw new InvalidOperationException("second mate was not removed");
            }),
        };

        // On macOS the window takes the mouse only while the pointer is on the character, so
        // the pointer is really moved: onto the mate, off onto the empty corner, and back.
        // After each move the system is asked what a click there would land on. The trip back
        // matters most: a window that is ignoring the mouse is told nothing about it, and
        // must notice for itself that the pointer has returned.
        if (OperatingSystem.IsMacOS() && ClickThrough.Supported)
        {
            IEnumerable<Step> Pointer(double at, string where, Func<PixelPoint> spot, bool lands, string problem) =>
            [
                new(at, $"pointer onto {where}", () =>
                {
                    if (!ClickThrough.MovePointerTo(First(), spot())) throw new InvalidOperationException("could not move the pointer");
                }, WaitingFor: AreaNotApplied),
                new(at + 0.001, $"click on {where}",
                    () => Note($"a click there {(lands ? "lands on the mate" : "passes through")}: {ClickThrough.DescribePointer(First())}"),
                    WaitingFor: () => ClickThrough.IsWindowAt(First(), spot()) == lands ? null : $"{problem}: {ClickThrough.DescribePointer(First())}"),
            ];
            steps.AddRange(Pointer(0.171, "the mate", OnCharacter, true, "the character is not clickable with the pointer on it"));
            steps.AddRange(Pointer(0.174, "the empty corner", OnEmptyCorner, false, "clicks on the empty corner are not passing through"));
            steps.AddRange(Pointer(0.177, "the mate again", OnCharacter, true, "the mate did not take clicks again when the pointer came back"));
            steps = [.. steps.OrderBy(step => step.At)];
        }

        int next = 0;
        // Seconds on the watch: when the first frame was drawn, and since when the next step
        // has been kept waiting. Negative until then.
        double began = -1, held = -1;
        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(50) };
        timer.Tick += (_, _) =>
        {
            if (finished) return;
            double now = watch.Elapsed.TotalSeconds;
            try
            {
                if (began < 0)
                {
                    if (First().FrameCount == 0)
                    {
                        if (now > StartUpLimit) throw new InvalidOperationException($"no frame was drawn in the first {StartUpLimit:0} seconds");
                        return;
                    }
                    began = now;
                    Note("first frame drawn" + (SinceLaunch() is { } seconds ? $", {seconds:0.0}s after the program was started" : ""));
                }
                double at = (now - began) / total;
                while (next < steps.Count && at >= steps[next].At)
                {
                    var step = steps[next];
                    if (held < 0)
                    {
                        Note($"step: {step.Name}");
                        held = now;
                    }
                    if (step.WaitingFor?.Invoke() is { } problem)
                    {
                        if (now - held > Patience) throw new InvalidOperationException($"{problem} (waited {Patience:0}s)");
                        return;     // look again on the next tick
                    }
                    if (now > held) Note($"waited {now - held:0.00}s for that");
                    held = -1;
                    step.Run();
                    next++;
                }
                if (at >= 1)
                {
                    timer.Stop();
                    int frames = First().FrameCount;
                    if (frames < total * 5) Finish(false, $"only {frames} frames were drawn in {total:0}s");
                    else Finish(true, $"{steps.Count} steps, {frames} frames ({frames / (now - began):0} fps)");
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
