#!/usr/bin/env python3
"""Decides whether the Android smoke test passed, from its screenshots and log.

    python3 check.py out-dir

Checks, in order:
  * the app is still running and nothing crashed;
  * the mate is on the screen: the screenshot differs from the home screen taken before it,
    in a patch about the size of a character, near the floor;
  * the stage is see-through: inside the stage window, most pixels are still the home screen
    (an opaque window would change all of them);
  * it moves while dancing: the dancing screenshots differ from one another;
  * it can be dragged: the log shows a drag that started from the scripted swipe.
The outline of what changed is printed as text, so the result can be read in the job log.
"""
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

out = Path(sys.argv[1])
log = (out / "logcat.txt").read_text(errors="replace") if (out / "logcat.txt").exists() else ""
failures = []


def load(name):
    p = out / f"{name}.png"
    if not p.exists() or p.stat().st_size == 0:
        return None
    return np.asarray(Image.open(p).convert("RGB")).astype(np.int16)


def changed(a, b, top_skip):
    d = np.abs(a - b).max(axis=2) > 40
    d[:top_skip] = False            # status bar: clock and the new notification icon
    return d


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


def last_rect(name):
    m = re.findall(name + r"=\((-?\d+),(-?\d+) (\d+)x(\d+)\)", log)
    return tuple(map(int, m[-1])) if m else None


# ---- Crashes ----
if re.search(r"FATAL EXCEPTION|Unhandled Exception|AndroidRuntime: Process: io\.github", log):
    failures.append("the app crashed (see logcat.txt)")
if "on screen, area" not in log:
    failures.append("the mate never reported being put on the screen")

home = load("0-home")
standing = load("1-standing")
if home is None or standing is None:
    failures.append("screenshots missing")
else:
    h, w, _ = home.shape
    top_skip = int(h * 0.06)
    mask = changed(home, standing, top_skip)
    n = int(mask.sum())
    print(f"screen {w}x{h}; {n} pixels changed between the home screen and the standing mate")
    print(outline(mask))
    stage = last_rect("stage")
    print("stage window:", stage, " hit box:", last_rect("hit"))
    if n < 2000:
        failures.append(f"the mate is not visible: only {n} pixels changed")
    elif stage:
        sx, sy, sw, sh = stage
        x0, y0 = max(sx, 0), max(sy, top_skip)
        x1, y1 = min(sx + sw, w), min(sy + sh, h)
        if x1 > x0 and y1 > y0:
            inside = mask[y0:y1, x0:x1]
            share = inside.mean()
            print(f"inside the stage window {share:.0%} of pixels changed; outside it {int(mask.sum() - inside.sum())}")
            if share > 0.85:
                failures.append(f"the stage is not see-through: {share:.0%} of it covers the home screen")

    frames = [f for f in (load(f"2-dancing-{i}") for i in range(1, 7)) if f is not None]
    if len(frames) >= 2:
        moves = [int(changed(a, b, top_skip).sum()) for a, b in zip(frames, frames[1:])]
        print("pixels changed between dancing screenshots:", moves)
        if max(moves) < 500:
            failures.append("the mate does not move while dancing")
        dancing = changed(home, frames[-1], top_skip)
        print("while dancing:")
        print(outline(dancing))
    else:
        failures.append("dancing screenshots missing")

    thrown, landed = load("3-thrown"), load("4-landed")
    if thrown is not None:
        print("just after the drag:")
        print(outline(changed(home, thrown, top_skip)))
    if landed is not None:
        print("after landing:")
        print(outline(changed(home, landed, top_skip)))

if "drag started" not in log:
    failures.append("the mate did not pick up the scripted drag")
if "dancing: True" not in log:
    failures.append("the dance command did not start a dance")

frame_counts = [int(x) for x in re.findall(r"DeskDancer: frame (\d+) ", log)]
print("frames drawn, as logged:", frame_counts[-5:])
if len(frame_counts) < 2 or frame_counts[-1] <= frame_counts[0]:
    failures.append("the frame loop is not running")

if failures:
    print("\nFAILED:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("\nPASS")
