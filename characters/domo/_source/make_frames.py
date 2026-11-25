#!/usr/bin/env python3
"""Draws Domo and builds every animation in the pack.

    python3 make_frames.py            # writes the clips and character.json into the pack
    python3 make_frames.py --sheet    # also saves sheet.png, every frame on one page

Nothing here starts from a picture. Domo is drawn by this script from the shapes listed
below: a body, two arms that hang from behind it, two stubby legs, two bead eyes and a
mouth full of teeth. Because he is drawn fresh for every frame, any part can move: the
arms lift and curl, the legs swing and lift, the mouth opens, snaps shut and roars, the
eyes blink, and the whole mate can squash, stretch, lean and jump. He can also sit down
with his legs out in front of him.

Each clip is a small function of time that returns a pose. The arms are not posed by
hand beyond that: a spring carries them, pushed about by how the shoulders move, so they
lag behind a stomp and flop when he lands.

Needs numpy and pillow. This folder starts with "_", so the app does not load anything
from it.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw

HERE = Path(__file__).resolve().parent
PACK = HERE.parent

# ---------------------------------------------------------------- sizes
# Positions are in units. Standing, Domo is 300 units tall. x = 0 runs up his middle and
# y = 0 is the floor, with y growing downwards as it does on screen.

OUT = 1.1                                # saved pixels per unit
SS = 4                                   # drawn this many times larger and averaged down, for smooth edges
X0, Y0, X1, Y1 = -230, -420, 230, 20     # the canvas: room for raised arms, leans and hops
W, H = round((X1 - X0) * OUT), round((Y1 - Y0) * OUT)

# ---------------------------------------------------------------- colours and lines

FUR = (126, 74, 44)
INK = (24, 13, 8)
GUM = (214, 10, 22)
TOOTH = (255, 255, 255)
EYE = (14, 11, 11)
GLINT = (188, 188, 196)

LINE = 2.4                               # the edge round each part, in units
LIP = 3.0                                # the edge round the mouth
FINE = 1.5                               # creases
TOOTH_LINE = 1.9                         # the edge round each tooth


# ---------------------------------------------------------------- shapes
# A shape is a closed run of points, close enough together to pass for a curve.

def bezier(p0, c1, c2, p1, n=14):
    """A curve from p0 to p1, bent towards c1 and c2. The last point is left for the next piece."""
    t = np.linspace(0, 1, n, endpoint=False)[:, None]
    p0, c1, c2, p1 = (np.array(p, float) for p in (p0, c1, c2, p1))
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t ** 2 * c2 + t ** 3 * p1


def both_sides(right):
    """A shape that is the same on both sides, from its right half listed from the top of
    the middle line round to the bottom of it."""
    right = np.asarray(right, float)
    return np.concatenate([right, (right * (-1, 1))[-2:0:-1]])


def oval(cx, cy, rx, ry=None, tilt=0.0, n=56):
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    pts = np.stack([rx * np.cos(a), (rx if ry is None else ry) * np.sin(a)], 1)
    return move(turn(tilt), pts) + (cx, cy)


def soften(corners, cuts, n=10):
    """A shape with straight sides, with each corner rounded off over `cut` units of the
    two sides that meet there."""
    corners = np.asarray(corners, float)
    out = []
    for i, cut in enumerate(cuts):
        here, before, after = corners[i], corners[i - 1], corners[(i + 1) % len(corners)]
        if not cut:
            out.append(here[None])
            continue
        a = here + (before - here) / np.hypot(*(before - here)) * cut
        b = here + (after - here) / np.hypot(*(after - here)) * cut
        t = np.linspace(0, 1, n)[:, None]
        out.append((1 - t) ** 2 * a + 2 * (1 - t) * t * here + t ** 2 * b)
    return np.concatenate(out)


def through(points, n=10):
    """A closed curve passing smoothly through every point."""
    p = np.asarray(points, float)
    t = np.linspace(0, 1, n, endpoint=False)[:, None]
    out = []
    for i in range(len(p)):
        a, b, c, d = p[i - 1], p[i], p[(i + 1) % len(p)], p[(i + 2) % len(p)]
        out.append(0.5 * (2 * b + (c - a) * t + (2 * a - 5 * b + 4 * c - d) * t ** 2 + (3 * b - a - 3 * c + d) * t ** 3))
    return np.concatenate(out)


def ribbon(points, widths):
    """A line that swells and thins along its length, as a shape."""
    p, half = np.asarray(points, float), np.asarray(widths, float)[:, None] / 2
    along = np.gradient(p, axis=0)
    across = np.stack([-along[:, 1], along[:, 0]], 1) / np.hypot(along[:, 0], along[:, 1])[:, None]
    return np.concatenate([p + across * half, (p - across * half)[::-1]])


def inset(points, by):
    """The same shape, drawn `by` further in all the way round."""
    p = np.asarray(points, float)
    along = np.roll(p, -1, 0) - np.roll(p, 1, 0)
    across = np.stack([-along[:, 1], along[:, 0]], 1)
    across /= np.maximum(np.hypot(across[:, 0], across[:, 1]), 1e-9)[:, None]
    x, y = p[:, 0], p[:, 1]
    clockwise = np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y) > 0
    return p + across * (by if clockwise else -by)


# Moving shapes about: a move is a 3x3 matrix, and `a @ b` does b first, then a.

def shift(dx, dy):
    return np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], float)


def turn(degrees, about=(0.0, 0.0)):
    """Clockwise on screen, so a positive turn about the feet tips the head to the right."""
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return shift(*about) @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float) @ shift(-about[0], -about[1])


def stretch(sx, sy):
    return np.diag([sx, sy, 1.0])


def move(m, points):
    return np.asarray(points, float) @ m[:2, :2].T + m[:2, 2]


# ---------------------------------------------------------------- the shape of the character

TOP, HEM = -300, -40                      # the top of his head, and where the body ends above the legs

BODY = both_sides(np.concatenate([
    bezier((0, TOP), (24, TOP), (44, TOP + 0.3), (62, TOP + 3)),                # the top, very slightly domed
    bezier((62, TOP + 3), (84, TOP + 6.5), (96, TOP + 22), (97, TOP + 46)),     # shoulder of the box
    bezier((97, TOP + 46), (98.5, -195), (96, -110), (92, -66)),                # the side, a little fuller in the middle
    bezier((92, -66), (91, -50), (82, HEM), (68, HEM)),                         # tucked in underneath
    [(68, HEM), (0, HEM)],
]))

# The arms hang from behind the body. Each is a tube that can curl, with a round hand.
SHOULDER = (87, -158)                     # the right one; the left is its mirror image
ARM = 62                                  # shoulder to wrist
ARM_R, WRIST_R, HAND_R = 16.0, 18.0, 21.5

# The legs, standing: short stubs that swing from the hip and tuck up behind the body.
HIP = (43, -50)
LEG = soften([(-28, -12), (28, -12), (31, 50), (-31, 50)], [0, 0, 22, 22])     # measured from the hip

# The legs, sitting: stuck out towards you, so what shows is the sole of each foot and a
# little of the leg behind it. Right leg; the left is its mirror image.
SEAT = 20                                 # how far the body comes down when he sits
SLUMP = 20                                # and how much further the shoulders do
THIGH = through([(100, -69), (87, -71.5), (74, -73), (61, -69.5), (47.5, -58), (40, -40), (38.5, -21),
                 (52, -9.5), (70, -1.8), (87, 0), (96, -20), (98, -46)])
SOLE = (92, -34.5, 19.5, 35.2, 11.0)      # an oval: middle, half width, half height, tilt
ANKLE = (58, -34)                         # a sitting foot waggles about here

EYES = (54.4, -261)                       # the right eye; the left is its mirror image
EYE_R = 10.3
MOUTH = (0, -180)
MOUTH_W, MOUTH_H = 58.4, 43.5             # half the width and half the height of the mouth, wide open
MOUTH_POWER = 5.3                         # how square its corners are
TEETH = (13.0, 39.0)                      # where the points of the teeth are, either side of the middle
TOOTH_TOP, TOOTH_BOTTOM = 18.0, 20.5      # how long the top and bottom teeth are


# ---------------------------------------------------------------- drawing

class Canvas:
    """A sheet to draw on. Everything is drawn hard-edged at SS times the saved size and
    averaged down at the end, which is where the smooth edges come from."""

    def __init__(self):
        self.img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        self.pen = ImageDraw.Draw(self.img)

    @staticmethod
    def px(points):
        return (np.asarray(points, float) - (X0, Y0)) * (OUT * SS)

    @staticmethod
    def _fill(pen, px, colour):
        pen.polygon(np.rint(px).astype(int).flatten().tolist(), fill=colour)

    def fill(self, points, colour):
        self._fill(self.pen, self.px(points), colour)

    def part(self, shapes, colour=FUR, line=LINE):
        """Shapes that belong together, drawn as one: a dark edge round the lot and none
        where they overlap."""
        shapes = [self.px(s) for s in shapes]
        for s in shapes:
            self._fill(self.pen, s, INK)
        for s in shapes:
            self._fill(self.pen, inset(s, line * OUT * SS), colour)

    def stroke(self, points, width, colour=INK):
        """A line of even width with round ends."""
        px = [tuple(p) for p in np.rint(self.px(points)).astype(int).tolist()]
        w = max(1, round(width * OUT * SS))
        self.pen.line(px, fill=colour, width=w, joint="curve")
        for x, y in (px[0], px[-1]):
            self.pen.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=colour)

    def inside(self, shape, paint):
        """Runs paint(layer) and keeps only what falls inside the shape."""
        layer = Canvas()
        paint(layer)
        mask = Image.new("L", self.img.size, 0)
        self._fill(ImageDraw.Draw(mask), self.px(shape), 255)
        box = mask.getbbox()
        if box is None:
            return
        cut = layer.img.crop(box)
        cut.putalpha(ImageChops.multiply(cut.getchannel("A"), mask.crop(box)))
        self.img.alpha_composite(cut, box[:2])

    def finish(self):
        """The drawing at its saved size."""
        # Averaged with each colour weighted by how solid it is, so that the empty space
        # round the edge does not darken it.
        return np.asarray(self.img.convert("RGBa").reduce(SS).convert("RGBA"))


# ---------------------------------------------------------------- the rig

DEFAULT = dict(eyes=("open", "open"),                        # each: "open", "wide", "happy", "closed", or 0..1 for how far shut
               look=(0.0, 0.0),                              # the face moved right and down, in units
               mouth=1.0,                                    # 0 teeth together, 1 as he usually has it, more is a roar
               arms=(24.0, 24.0), bend=(-14.0, -14.0),       # degrees each arm is lifted from hanging straight down, and curled
               legs=((0.0, 0.0), (0.0, 0.0)),                # each leg: degrees swung outwards (sitting: the foot tipped up), units lifted
               seated=False,
               squash=0.0, lean=0.0, dx=0.0, dy=0.0)         # the whole mate; dy < 0 is up


def whole(pose):
    """How the whole mate is squashed, leant and moved, about the point between his feet."""
    return (shift(pose["dx"], pose["dy"]) @ turn(pose["lean"])
            @ stretch(1 + 0.7 * pose["squash"], 1 - pose["squash"]))


def shoulder(pose, side):
    """Where an arm starts, before the whole mate is moved."""
    return side * SHOULDER[0], SHOULDER[1] + (SEAT + SLUMP if pose["seated"] else 0)


def arm_shapes(side, lift, bend, start):
    """The arm on one side (-1 left, 1 right): its shapes and the crease where the hand begins."""
    n = 22
    theta = np.radians(lift + bend * np.linspace(0, 1, n))
    heading = np.stack([side * np.sin(theta), np.cos(theta)], 1)
    steps = (heading[:-1] + heading[1:]) / 2 * ARM / (n - 1)
    line = np.array(start, float) + np.concatenate([[(0.0, 0.0)], np.cumsum(steps, 0)])
    across = np.stack([heading[:, 1], -heading[:, 0]], 1) * side          # towards the outside of the arm
    r = np.linspace(ARM_R, WRIST_R, n)[:, None]
    tube = np.concatenate([line + across * r, (line - across * r)[::-1]])
    hand = line[-1] + heading[-1] * 5
    crease = [hand + (HAND_R - LINE / 2) * (-heading[-1] * math.cos(a) + across[-1] * math.sin(a))
              for a in np.radians(np.linspace(56, -12, 14))]
    return [tube, oval(*line[0], ARM_R), oval(*hand, HAND_R)], crease


def draw_eye(c, m, cx, cy, state):
    r = EYE_R
    us = np.linspace(-1, 1, 25)
    if state == "closed":                                   # asleep: a line curving down
        line = [(cx + u * r * 1.1, cy + r * (0.05 + 0.42 * (1 - u * u))) for u in us]
        c.fill(move(m, ribbon(line, [1.6 + 2.0 * math.sqrt(1 - u * u) for u in us])), INK)
        return
    if state == "happy":                                    # ^ ^
        line = [(cx + u * r * 1.12, cy + r * (0.55 - 1.05 * (1 - u * u) ** 0.85)) for u in us]
        c.fill(move(m, ribbon(line, [2.0 + 2.6 * math.sqrt(1 - u * u) for u in us])), INK)
        return
    shut = state if isinstance(state, float) else 0.0
    if state == "wide":
        r *= 1.22
    c.fill(move(m, oval(cx, cy, r * (1 + 0.08 * shut), max(r * (1 - shut), 1.3))), EYE)
    if shut < 0.4:                                          # the shine along the top of the bead
        arc = [(cx + 0.60 * r * math.cos(a), cy + 0.60 * r * math.sin(a)) for a in np.radians(np.linspace(205, 335, 15))]
        c.fill(move(m, ribbon(arc, 0.36 * r * np.sin(np.linspace(0.25, math.pi - 0.25, 15)))), GLINT)


def lip_edge(x, half_w, half_h):
    """How far above or below the middle of the mouth its edge is at x."""
    return half_h * (1 - min(abs(x) / half_w, 1) ** MOUTH_POWER) ** (1 / MOUTH_POWER)


def draw_mouth(c, m, wide):
    half_h = MOUTH_H * max(wide, 0.26)                     # shut, the two rows of teeth still show
    half_w = MOUTH_W * (1 + 0.05 * (1 - min(wide, 1)))      # shut, it spreads a little
    cx, cy = MOUTH[0], MOUTH[1] + 6 * (wide - 1)            # the jaw drops as it opens
    a = np.linspace(0, 2 * math.pi, 200, endpoint=False)
    lip = np.stack([cx + half_w * np.sign(np.cos(a)) * np.abs(np.cos(a)) ** (2 / MOUTH_POWER),
                    cy + half_h * np.sign(np.sin(a)) * np.abs(np.sin(a)) ** (2 / MOUTH_POWER)], 1)
    lip_px = c.px(move(m, lip))
    c._fill(c.pen, lip_px, INK)
    gum = (inset(lip_px, LIP * OUT * SS) / (OUT * SS)) + (X0, Y0)      # back in units, already moved

    def teeth(layer):
        layer.fill(gum, GUM)
        valleys = [-4 * TEETH[0], -2 * TEETH[0], 0.0, 2 * TEETH[0], 4 * TEETH[0]]
        tips = [-TEETH[1], -TEETH[0], TEETH[0], TEETH[1]]
        for way, length, blunt in ((-1, TOOTH_TOP, 3.0), (1, TOOTH_BOTTOM, 6.5)):     # top row, then bottom row
            # The teeth grow from the lip and stop short of the middle, so that when the
            # mouth shuts the two rows meet point to point.
            length = min(length, half_h - 0.5)
            row = []
            for i, x in enumerate(valleys):
                row.append((cx + x, cy + way * (lip_edge(x, half_w, half_h) - 0.4)))
                if i < len(tips):
                    row.append((cx + tips[i], cy + way * (half_h - length)))
            cuts = [0 if i % 2 == 0 else min(blunt, length * 0.45) for i in range(len(row))]
            edge = soften(row + [(cx + half_w + 9, cy + way * (half_h + 9)), (cx - half_w - 9, cy + way * (half_h + 9))],
                          cuts + [0, 0], n=7)
            edge = move(m, edge)
            layer.fill(edge, TOOTH)
            layer.stroke(edge[:-2], TOOTH_LINE, INK)

    c.inside(gum, teeth)


def render(pose):
    """The pose, drawn."""
    pose = {**DEFAULT, **pose}
    c = Canvas()
    everything = whole(pose)
    seated = pose["seated"]
    body = everything @ shift(0, SEAT if seated else 0)

    for side, lift, bend in ((-1, pose["arms"][0], pose["bend"][0]), (1, pose["arms"][1], pose["bend"][1])):
        shapes, crease = arm_shapes(side, lift, bend, shoulder(pose, side))
        c.part([move(everything, s) for s in shapes])
        c.stroke(move(everything, crease), FINE)

    if not seated:
        for side, (swing, lift) in zip((-1, 1), pose["legs"]):
            hip = (side * HIP[0], HIP[1])
            c.part([move(everything @ shift(hip[0], hip[1] - lift) @ turn(-side * swing), LEG)])

    c.part([move(body, BODY)])
    face = body @ shift(*pose["look"])
    for side, state in zip((-1, 1), pose["eyes"]):
        draw_eye(c, face, side * EYES[0], EYES[1], state)
    draw_mouth(c, face, pose["mouth"])

    if seated:
        for side, (swing, lift) in zip((-1, 1), pose["legs"]):
            foot = everything @ stretch(side, 1) @ shift(0, -lift) @ turn(-swing, ANKLE)
            sx, sy, rx, ry, tilt = SOLE
            sole = oval(sx, sy, rx, ry, tilt)
            c.part([move(foot, THIGH), move(foot, sole)])
            # Drawn as one part, the sole has no edge where it lies over the leg, so that
            # stretch of it is put back with a finer line.
            rim = inset(sole, LINE / 2)
            c.stroke(move(foot, rim[15:42]), FINE)
    return c.finish()


# ---------------------------------------------------------------- movement

ARM_HZ, ARM_DAMPING = 3.4, 0.50         # how fast an arm swings back, and how soon it settles
ARM_PUSH = 0.55                         # how hard the body's movement throws the arms about
ARM_CURL = 2.6                          # degrees the hand trails behind per radian/second of swing


def animate(clip, seconds, fps, calm, step=1 / 500):
    """Samples clip(t) through one turn of the loop, lets the arms swing, and returns the
    frames as (pose, milliseconds). A frame is held for as long as nothing has visibly
    moved; a calm clip waits for a little more movement, so the tail end of a settling arm
    does not cost a frame every time."""
    n = int(round(seconds / step))
    poses = [{**DEFAULT, **clip(i * step)} for i in range(n)]
    lifts = np.array([p["arms"] for p in poses], np.float64)
    curls = np.array([p["bend"] for p in poses], np.float64)
    omega = 2 * math.pi * ARM_HZ
    blur = np.exp(-0.5 * (np.arange(-24, 25) * step / 0.012) ** 2)
    blur /= blur.sum()
    for a, side in enumerate((-1, 1)):
        # How the shoulder is being thrown about: its acceleration.
        root = np.array([move(whole(p), [shoulder(p, side)])[0] for p in poses])
        acc = (np.roll(root, -1, 0) - 2 * root + np.roll(root, 1, 0)) / step ** 2
        acc = np.stack([np.convolve(np.tile(acc[:, k], 3), blur, "same")[n:2 * n] for k in (0, 1)], 1)
        # A spring pulls the arm towards where the clip wants it. Three turns of the loop,
        # so that the last one starts as it ends and the loop joins up.
        target, posed = np.radians(lifts[:, a]), curls[:, a].copy()
        angle, speed = target[0], 0.0
        for _ in range(3):
            for i in range(n):
                # Lifting the arm moves the hand this way; a shove the other way lifts it.
                lifting = (side * math.cos(angle), -math.sin(angle))
                push = -(acc[i, 0] * lifting[0] + acc[i, 1] * lifting[1]) / ARM * ARM_PUSH
                speed += (-omega * omega * (angle - target[i]) - 2 * ARM_DAMPING * omega * speed + push) * step
                angle += speed * step
                lifts[i, a] = math.degrees(angle)
                curls[i, a] = min(max(posed[i] - ARM_CURL * speed, posed[i] - 22), posed[i] + 22)

    frames, every, ms, within = [], int(round(1 / fps / step)), round(1000 / fps), 1.2 if calm else 0.25
    for i in range(0, n, every):
        pose = {**poses[i], "arms": (round(float(lifts[i, 0]), 1), round(float(lifts[i, 1]), 1)),
                "bend": (round(float(curls[i, 0]), 1), round(float(curls[i, 1]), 1))}
        if frames and same(frames[-1][0], pose, within):
            frames[-1] = (frames[-1][0], frames[-1][1] + ms)
        else:
            frames.append((pose, ms))
    if len(frames) > 1 and same(frames[0][0], frames[-1][0], within):
        frames[0] = (frames[0][0], frames[0][1] + frames.pop()[1])
    return frames


def same(a, b, within):
    """Whether two poses would look the same on screen: nothing more than `within` degrees
    or units apart."""
    def flat(p):
        return [*p["arms"], *(0.5 * v for v in p["bend"]), *p["legs"][0], *p["legs"][1], *(2 * v for v in p["look"]),
                p["mouth"] * 60, p["squash"] * 150, p["lean"] * 2, p["dx"], p["dy"]]
    return ((a["eyes"], a["seated"]) == (b["eyes"], b["seated"])
            and max(abs(x - y) for x, y in zip(flat(a), flat(b))) < within)


def smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def ease(t, a=0.0, b=1.0):
    """0 before a, 1 after b, gliding between."""
    return smooth((t - a) / (b - a))


def bump(t, start, rise, hold, fall):
    """0, gliding up to 1 over `rise`, staying for `hold`, gliding back over `fall`."""
    return ease(t, start, start + rise) * (1 - ease(t, start + rise + hold, start + rise + hold + fall))


def blink(t, at):
    """The eyes for a blink that starts at `at`: quick to shut, a little slower to open."""
    for until, lids in ((0.05, 0.6), (0.15, 1.0), (0.20, 0.65)):
        if at <= t < at + until:
            return (lids, lids)
    return None


OPEN, WIDE, HAPPY, CLOSED = ("open", "open"), ("wide", "wide"), ("happy", "happy"), ("closed", "closed")


# ---------------------------------------------------------------- the clips

def idle(t):
    """Stands and looks about: blinks, glances to one side, snaps his teeth together
    twice, and, if he is left standing long enough, gives a little wave."""
    eyes = blink(t, 1.1) or blink(t, 3.3) or blink(t, 6.5) or blink(t, 6.8) or OPEN
    glance = bump(t, 2.2, 0.30, 1.6, 0.36)
    bite = max(bump(t, 5.0, 0.07, 0.05, 0.10), bump(t, 5.35, 0.07, 0.05, 0.14))
    wave = bump(t, 7.6, 0.24, 0.62, 0.28)
    flap = 15 * math.sin(2 * math.pi * (t - 7.78) / 0.36) * bump(t, 7.78, 0.08, 0.46, 0.10)
    return dict(eyes=eyes, mouth=round(1 - 0.95 * bite, 2), look=(round(9 * glance, 1), 0.0), lean=1.6 * glance - 1.2 * wave,
                arms=(24 + 5 * glance, 24 + 94 * wave + flap), bend=(-14, -14 + 40 * wave))


def walk(t):
    """A toddle: rocks from foot to foot, lifting the free one, arms swinging the other way."""
    u = 2 * math.pi * t / 0.52
    side = math.sin(u)
    left, right = max(0.0, side), max(0.0, -side)             # which foot is off the floor
    return dict(look=(8.0, 0.0), lean=1.5 + 4.5 * side, dy=-4.0 * abs(side), dx=2.0 * side,
                squash=0.02 * math.cos(u) ** 2,
                legs=((5 * left, 11 * left ** 0.8), (5 * right, 11 * right ** 0.8)),
                arms=(26 + 13 * side, 26 - 13 * side))


def happy_arms(t):
    """Shown during every built-in dance move, which adds its own body motion on top:
    both arms in the air, waving from side to side, and a great big grin."""
    u = 2 * math.pi * t / 1.0
    return dict(eyes=HAPPY, mouth=1.12, arms=(116 + 22 * math.sin(u), 116 - 22 * math.sin(u)),
                bend=(28 + 14 * math.cos(u), 28 - 14 * math.cos(u)))


def stomp(t):
    """A monster stomp, one foot and then the other. Clip dances get no motion from the
    app, so it is all here: he rears up on one leg with his arms raised like claws, slams
    the other foot down and roars."""
    beat, side = (t % 0.5) / 0.5, 1 if t % 1.0 < 0.5 else -1  # which foot comes down: 1 is his right
    up = ease(beat, 0.0, 0.40) * (1 - ease(beat, 0.58, 0.70))
    after = max(0.0, beat - 0.70) / 0.30                      # 0 as the foot lands, 1 at the end of the beat
    hit = ease(after, 0, 0.12) * (1 - after) ** 2 if beat >= 0.70 else 0.0
    leg = (9 * up, 26 * up)
    return dict(eyes=WIDE if hit > 0.25 else OPEN, mouth=1.0 + 0.32 * hit + 0.08 * up,
                lean=side * (-6.5 * up + 5.0 * hit), dx=side * (-5 * up + 7 * hit), dy=-7 * up,
                squash=0.13 * hit - 0.035 * up,
                legs=((0, 0), leg) if side > 0 else (leg, (0, 0)),
                arms=(104 + 24 * up - 24 * hit, 104 + 24 * up - 24 * hit), bend=(34 + 16 * up, 34 + 16 * up))


def chomp(t):
    """Bounces on the spot and bites the air on every beat: mouth wide open on the way up,
    teeth snapping shut as he lands, arms flapping."""
    hop, side = (t % 0.5) / 0.5, 1 if t % 1.0 < 0.5 else -1
    ground = 0.38                                             # share of each hop spent on the floor
    if hop < ground:
        g = hop / ground
        air, height = 0.0, 0.0
        squash = 0.12 * math.sin(math.pi * g) - 0.06 * (1 - ease(g, 0, 0.3)) - 0.06 * ease(g, 0.7, 1)
    else:
        air = (hop - ground) / (1 - ground)
        height = 30 * 4 * air * (1 - air)
        squash = -0.06 * abs(1 - 2 * air) ** 1.5
    up = math.sin(math.pi * air)
    gape = ease(hop, 0.20, 0.50) * (1 - ease(hop, 0.90, 0.99))       # open from the push-off, shut on landing
    shut = hop < 0.16 or hop > 0.94
    return dict(eyes=HAPPY if shut else OPEN, mouth=0.02 + 1.26 * gape,
                squash=squash, dy=-height, lean=side * 4.5 * up, dx=side * 4 * up,
                legs=((7 * up, 4 * up), (7 * up, 4 * up)),
                arms=(44 + 78 * up, 44 + 78 * up), bend=(-10 + 30 * up, -10 + 30 * up))


def carried(t):
    """Picked up by the scruff: eyes wide, mouth open, arms flailing, legs pedalling."""
    u = 2 * math.pi * t / 0.4
    return dict(eyes=WIDE, mouth=1.22 + 0.06 * math.sin(2 * u), squash=-0.045, lean=1.5 * math.sin(u),
                arms=(98 + 30 * math.sin(u), 98 - 30 * math.sin(u)), bend=(22, 22),
                legs=((7 + 9 * math.sin(u + 1.0), 3 + 3 * math.sin(u + 1.0)), (7 - 9 * math.sin(u + 1.0), 3 - 3 * math.sin(u + 1.0))))


def falling(t):
    """Dropped: arms streaming up, legs trailing, yelling all the way down."""
    u = 2 * math.pi * t / 0.24
    return dict(eyes=WIDE, mouth=1.34, squash=-0.07,
                arms=(126 + 8 * math.sin(u), 126 + 8 * math.sin(u + 1.6)), bend=(30 + 10 * math.sin(u - 1.0), 30 + 10 * math.sin(u + 0.6)),
                legs=((13 + 5 * math.sin(u), 5), (13 + 5 * math.sin(u + 2.0), 5)))


SITTING = dict(seated=True, arms=(38.0, 38.0), bend=(-14.0, -14.0))


def sitting(t):
    """Sat down with his legs out in front, hands on the floor. Blinks, and waggles his
    feet now and then."""
    eyes = blink(t, 1.4) or blink(t, 5.0) or blink(t, 5.3) or OPEN
    waggle = 8 * math.sin(2 * math.pi * (t - 2.8) / 0.45) * bump(t, 2.8, 0.12, 0.66, 0.12)
    return dict(SITTING, eyes=eyes, legs=((round(waggle, 1), 0.0), (round(-waggle, 1), 0.0)))


def asleep(t):
    """Slumped where he sits, eyes shut, mouth all but closed and opening a little with
    each breath. The app adds the breathing and the Zs."""
    snore = 0.5 - 0.5 * math.cos(2 * math.pi * t / 4.0)
    return dict(SITTING, eyes=CLOSED, mouth=0.26 + 0.04 * round(5 * snore), lean=2.5, look=(0.0, 3.0),
                arms=(33.0, 33.0), bend=(-20.0, -20.0))


CLIPS = {
    # key: file, name in the Dance move menu, the clip, its length, frames a second, calm
    "idle": ("idle.webp", None, idle, 10.0, 20, True),
    "walk": ("walk.webp", None, walk, 0.52, 25, False),
    "sit": ("sit.webp", None, sitting, 7.0, 20, True),
    "sleep": ("sleep.webp", None, asleep, 4.0, 20, True),
    "dance": ("dance.webp", "Happy Arms", happy_arms, 1.0, 25, False),
    "dance_chomp": ("dance_chomp.webp", "Chomp", chomp, 1.0, 25, False),
    "dance_stomp": ("dance_stomp.webp", "Monster Stomp", stomp, 1.0, 25, False),
    "drag": ("drag.webp", None, carried, 0.40, 25, False),
    "fall": ("fall.webp", None, falling, 0.24, 25, False),
}


def build(key):
    """Renders one clip: its frames cropped to what they use, their timings, and where the
    feet are in the cropped frames."""
    _, _, clip, seconds, fps, calm = CLIPS[key]
    timeline = animate(clip, seconds, fps, calm)
    images = [render(pose) for pose, _ in timeline]
    used = np.max([im[..., 3] for im in images], axis=0) > 0
    ys, xs = np.nonzero(used.any(axis=1))[0], np.nonzero(used.any(axis=0))[0]
    assert xs[0] > 0 and ys[0] > 0 and xs[-1] < W - 1 and ys[-1] < H - 1, f"{key} runs off the canvas"
    x0, y0, x1, y1 = max(xs[0] - 2, 0), max(ys[0] - 2, 0), xs[-1] + 3, ys[-1] + 3
    anchor = [round(-X0 * OUT - x0, 1), round(-Y0 * OUT - y0, 1)]
    return [Image.fromarray(im[y0:y1, x0:x1], "RGBA") for im in images], [ms for _, ms in timeline], anchor


def main():
    manifest = {"name": "Domo", "height": 150, "facing": "right", "removeBackground": False, "clips": {}}
    standing = render({})[..., 3].any(axis=1).sum()            # how tall the mate is standing still, in saved pixels
    rows, pixels = [], 0
    for key, (file, name, *_) in CLIPS.items():
        images, durations, anchor = build(key)
        if len(images) == 1:
            file = file.rsplit(".", 1)[0] + ".png"
            images[0].save(PACK / file, optimize=True)
        else:
            images[0].save(PACK / file, save_all=True, append_images=images[1:], duration=durations, loop=0,
                           lossless=True, quality=100, method=4)
        manifest["clips"][key] = {"file": file, "anchor": anchor, **({"name": name} if name else {})}
        if key == "idle":
            # The app makes the idle clip, at its tallest, `height` pixels high. Should idle
            # ever reach above his head, that would shrink him, so allow for it.
            manifest["height"] = round(150 * (images[0].height - 4) / standing)
        rows.append(images)
        pixels += len(images) * images[0].width * images[0].height
        print(f"{file}: {len(images)} frames of {images[0].width}x{images[0].height}, {sum(durations) / 1000:.2f}s, "
              f"{(PACK / file).stat().st_size // 1024} KB")
    print(f"all clips: {sum(len(r) for r in rows)} frames, {pixels * 4 / 2 ** 20:.0f} MB once the app has unpacked them")

    (PACK / "character.json").write_text(json.dumps(manifest, indent=2) + "\n")
    written = {clip["file"] for clip in manifest["clips"].values()}
    for stray in sorted(f.name for f in PACK.iterdir() if f.suffix in (".webp", ".png", ".gif") and f.name not in written):
        print(f"note: {stray} was not written by this run; the app will load it as a clip of its own")

    if "--sheet" in sys.argv:
        cell = 110
        cols = 26
        lines = sum(-(-len(r) // cols) for r in rows)
        sheet, line = Image.new("RGBA", (cols * cell, lines * cell), (40, 44, 64, 255)), 0
        for images in rows:
            for i, im in enumerate(images):
                t = im.copy()
                t.thumbnail((cell - 4, cell - 4), Image.LANCZOS)
                sheet.alpha_composite(t, ((i % cols) * cell + (cell - t.width) // 2,
                                          (line + i // cols) * cell + (cell - t.height) // 2))
            line += -(-len(images) // cols)
        sheet.save(HERE / "sheet.png")


if __name__ == "__main__":
    main()
