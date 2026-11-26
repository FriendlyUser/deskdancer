#!/usr/bin/env python3
"""Decides whether the Android smoke test passed, from its screenshots and logs.

    python3 check.py out-dir

Checks, in order:
  * the app is still running and nothing crashed;
  * the mate is on the screen: over the character's body (its hit box) the screenshot is
    clearly different from the bare home screen;
  * the stage is see-through: in the rest of the stage window, the home screen shows
    through unchanged, so there is no box or tint around the mate;
  * it moves while dancing: the dancing screenshots differ from one another;
  * it can be dragged: the log shows a drag that started from the scripted swipe;
  * asked to, Domo does his Fart action, once, and then stands about again;
  * his Apple Tree action, which is read a frame at a time as it is shown and takes him
    across the screen, plays through, moves him, and leaves him standing;
  * a character put in a folder on the phone, once that folder is chosen in the folder
    picker, is copied in, can be put on the screen and is visible there;
  * the folder opens in the Files app;
  * a move unticked in the settings is switched off.
Where the two windows were comes from Android itself (dumpsys window), taken right after
the screenshot. The bare home screen is the one taken after the mate was put away, when
the launcher has long settled. Outlines of what changed are printed as text, so the result
can be read in the job log.
"""
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PKG = "io.github.friendlyuser.deskdancer"
out = Path(sys.argv[1])


def read(name):
    p = out / name
    return p.read_text(errors="replace") if p.exists() else ""


log = read("logcat.txt")
failures = []


def load(name):
    p = out / f"{name}.png"
    if not p.exists() or p.stat().st_size == 0:
        return None
    return np.asarray(Image.open(p).convert("RGB")).astype(np.int16)


def difference(a, b):
    return np.abs(a - b).max(axis=2)


def outline(mask, cols=60):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return "(nothing)"
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    cell = max(1, (x1 - x0) // cols)
    rows = []
    for y in range(y0, y1, cell * 2):
        row = ""
        for x in range(x0, x1, cell):
            f = mask[y:y + cell * 2, x:x + cell].mean()
            row += "#" if f > 0.5 else "+" if f > 0.15 else "." if f > 0 else " "
        rows.append(row.rstrip())
    return "\n".join(rows)


def overlay_windows(dump):
    """(x, y, w, h) of this app's overlay windows, biggest first."""
    found, mine = [], False
    for line in dump.splitlines():
        if "Window #" in line:
            mine = f"u0 {PKG}}}" in line
        elif mine and "ty=APPLICATION_OVERLAY" in line:
            m = re.search(r"mAttrs=\{\((-?\d+),(-?\d+)\)\((\d+)x(\d+)\)", line)
            if m:
                found.append(tuple(map(int, m.groups())))
    return sorted(found, key=lambda r: r[2] * r[3], reverse=True)


def box(mask_shape, rect, top_skip):
    h, w = mask_shape
    x, y, rw, rh = rect
    m = np.zeros(mask_shape, bool)
    m[max(y, top_skip):max(min(y + rh, h), 0), max(x, 0):max(min(x + rw, w), 0)] = True
    return m


# ---- Crashes ----
if re.search(r"FATAL EXCEPTION|Unhandled Exception|AndroidRuntime: Process: io\.github", log):
    failures.append("the app crashed (see logcat.txt)")
if "on screen, area" not in log:
    failures.append("the mate never reported being put on the screen")

before, after, standing = load("0-home"), load("5-home-after"), load("1-standing")
home = after if after is not None else before
if home is None or standing is None:
    failures.append("screenshots missing")
else:
    h, w, _ = home.shape
    top_skip = int(h * 0.06)            # status bar: clock and the notification icon
    print(f"screen {w}x{h}")
    if before is not None and after is not None:
        noise = difference(before, after) > 40
        noise[:top_skip] = False
        print(f"home screen before vs after the test: {int(noise.sum())} pixels differ")

    diff = difference(home, standing)
    diff[:top_skip] = 0
    changed = diff > 40
    print("standing mate, what differs from the home screen:")
    print(outline(changed))

    windows = overlay_windows(read("1-standing-windows.txt"))
    print("overlay windows (x, y, w, h):", windows)
    if len(windows) < 2:
        failures.append(f"expected the stage and the hit box windows, found {len(windows)}")
    else:
        stage, hit = windows[0], windows[1]
        on_body = box(diff.shape, hit, top_skip)
        around = box(diff.shape, stage, top_skip) & ~on_body
        body_share = changed[on_body].mean() if on_body.any() else 0
        print(f"over the body: {body_share:.0%} of pixels changed")
        # The hit box is sized for a mate standing up; sitting or napping it fills less of it
        # (about 12% for Mochi), and a mate that is not drawn at all leaves close to nothing.
        if body_share < 0.05:
            failures.append(f"the mate is not visible: only {body_share:.0%} of its body area changed")
        if around.any():
            d = diff[around]
            share, median, p95 = (d > 40).mean(), float(np.median(d)), float(np.percentile(d, 95))
            print(f"rest of the stage: {share:.1%} of pixels changed; difference median {median:.0f}, 95th percentile {p95:.0f} (of 255)")
            # The floor shadow and the odd limb poke out past the body; a box or a tint would not stop there.
            if share > 0.10 or median > 6:
                failures.append(f"the stage is not see-through around the mate ({share:.0%} changed, median {median:.0f})")
        outside = changed & ~box(diff.shape, stage, top_skip)
        print(f"outside the stage: {int(outside.sum())} pixels changed")

    frames = [f for f in (load(f"2-dancing-{i}") for i in range(1, 7)) if f is not None]
    if len(frames) >= 2:
        moves = []
        for a, b in zip(frames, frames[1:]):
            m = difference(a, b) > 40
            m[:top_skip] = False
            moves.append(int(m.sum()))
        print("pixels changed between dancing screenshots:", moves)
        if max(moves) < 500:
            failures.append("the mate does not move while dancing")
        m = difference(home, frames[-1]) > 40
        m[:top_skip] = False
        print("while dancing:")
        print(outline(m))
    else:
        failures.append("dancing screenshots missing")

    for name, title in (("3-thrown", "just after the drag"), ("4-landed", "after landing"), ("4-acting", "Domo farting"),
                        ("4-tree", "Domo and his apple tree")):
        shot = load(name)
        if shot is not None:
            m = difference(home, shot) > 40
            m[:top_skip] = False
            print(f"{title}:")
            print(outline(m))

before_drag = overlay_windows(read("3-before-drag-windows.txt"))
if before_drag:
    print("overlay windows just before the drag (x, y, w, h):", before_drag)
if "drag started" not in log:
    failures.append("the mate did not pick up the scripted drag")
if "dancing: True" not in log:
    failures.append("the dance command did not start a dance")

# ---- An action ----
if "action 'action_fart' started" not in log:
    failures.append("the act command did not start Domo's Fart")
else:
    acting = log.split("action 'action_fart' started", 1)[1].split("command 'stop'", 1)[0]
    states = re.findall(r"state=(\w+) clip=(\w+)", acting)
    print("after the act command, as logged every two seconds:", states)
    if ("Act", "action_fart") not in states:
        failures.append("the mate never showed the Fart action")
    elif ("Idle", "idle") not in states[states.index(("Act", "action_fart")):]:
        failures.append("the mate did not go back to standing after its action")

if "action 'action_apple_tree' started" not in log:
    failures.append("the act command did not start Domo's Apple Tree")
else:
    acting = log.split("action 'action_apple_tree' started", 1)[1].split("command 'stop'", 1)[0]
    rows = re.findall(r"state=(\w+) clip=(\w+) foot=\((-?\d+),-?\d+\).*?hit=\(-?\d+,-?\d+ \d+x(\d+)\)", acting)
    states = [(state, clip) for state, clip, _, _ in rows]
    print("after the Apple Tree command, as logged every two seconds:", [(state, clip, int(x)) for state, clip, x, _ in rows])
    if ("Act", "action_apple_tree") not in states:
        failures.append("the mate never showed the Apple Tree action")
    elif ("Idle", "idle") not in states[states.index(("Act", "action_apple_tree")):]:
        failures.append("the mate did not go back to standing after the Apple Tree action")
    else:
        # He runs off one way and back the other. However little room the screen leaves
        # him, that is most of his own height.
        xs = [int(x) for _, _, x, _ in rows]
        tall = max(int(h) for _, _, _, h in rows)
        print(f"during it his feet were between {min(xs)} and {max(xs)} across, and he is about {tall} tall")
        if max(xs) - min(xs) < 0.6 * tall:
            failures.append(f"the Apple Tree action did not take the mate anywhere (his feet stayed between {min(xs)} and {max(xs)})")

# Frame rate and the time spent drawing, as the app logged them every two seconds. The
# emulator draws everything in software, so these are a floor, not what a phone does.
for state in ("Dance", "Idle"):
    rows = re.findall(r"state=" + state + r" .*?fps=(\d+) render=([\d.]+)ms", log)
    if rows:
        fps = [int(f) for f, _ in rows]
        ms = [float(r) for _, r in rows]
        print(f"{state.lower()}: {min(fps)}-{max(fps)} frames a second, drawing {min(ms):.1f}-{max(ms):.1f} ms a frame")

frame_counts = [int(x) for x in re.findall(r"DeskDancer: frame (\d+) ", log)]
print("frames drawn, as logged:", frame_counts[-5:])
if len(frame_counts) < 2 or frame_counts[-1] <= frame_counts[0]:
    failures.append("the frame loop is not running")

# ---- A character of the user's own, from the chosen folder ----
syncs = re.findall(r"characters folder synced: (\d+) character\(s\) \(([^)]*)\)", log)
print("characters folder read:", syncs or "never")
if "characters folder chosen" not in log:
    failures.append("no folder was chosen in the folder picker")
if not any("my-kori" in names.split(", ") for _, names in syncs):
    failures.append("the character put in the chosen folder was not copied in")
if "mate 'my-kori' on screen" not in log:
    failures.append("the character from the folder was not put on the screen")
kori = load("7-kori")
if kori is not None and home is not None:
    windows = overlay_windows(read("7-kori-windows.txt"))
    skip = int(home.shape[0] * 0.06)
    if len(windows) >= 2:
        diff = difference(home, kori)
        diff[:skip] = 0
        on_body = box(diff.shape, windows[1], skip)
        share = (diff > 40)[on_body].mean() if on_body.any() else 0
        print(f"the character from the folder: {share:.0%} of its body area changed")
        print(outline(diff > 40))
        if share < 0.05:
            failures.append(f"the character from the folder is not visible ({share:.0%} of its body area changed)")
    else:
        failures.append("the character from the folder has no windows on the screen")
resumed = [l.strip() for l in read("8-activities.txt").splitlines() if "ResumedActivity" in l]
print("in front after opening the folder:", resumed[:2])
if not any("documentsui" in l for l in resumed):
    failures.append("the folder did not open in the Files app")
if "move 'backflip' switched off" not in log:
    failures.append("unticking Backflip in the settings did not switch it off")

if failures:
    print("\nFAILED:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("\nPASS")
