#!/usr/bin/env python3
"""Draws Domo and builds every animation in the pack.

    python3 make_frames.py            # writes the clips and character.json into the pack
    python3 make_frames.py --sheet    # also saves sheet.png, every frame on one page

Nothing here starts from a picture. Domo is drawn by this script from the shapes listed
below: a body, two arms that hang from behind it, two stubby legs, two bead eyes and a
mouth full of teeth. Because he is drawn fresh for every frame, any part can move: the
arms lift and curl, the legs swing and lift, the mouth opens, snaps shut and roars, the
eyes blink, and the whole mate can squash, stretch, lean and jump. He can also sit down
with his legs out in front of him, bring an arm round in front to hold a cup of bubble
tea, and let off a cloud of gas: his two actions, which play once through rather than loop.

Each clip is a small function of time that returns a pose. The arms are not posed by
hand beyond that: a spring carries them, pushed about by how the shoulders move, so they
lag behind a stomp and flop when he lands.

What a pose looks like is up to a painter. The one here, Flat, fills each shape with one
colour and gives it a dark edge. The Plush Domo pack (characters/domo-plush) borrows
everything in this file but the painter, and draws the same poses in fleece.

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
PLASTIC = (232, 240, 244)
TEA = (222, 184, 146)
PEARL = (46, 28, 22)
STRAW = (247, 226, 166)
GAS = (204, 222, 132)

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

# A cup of bubble tea, standing upright and measured from the middle of its base.
CUP_TALL = 68.0
CUP_BASE, CUP_RIM = 19.0, 26.0            # half its width at the bottom and at the top
CUP_WALL = 2.4                            # how far inside the cup the tea stops
CUP_FULL = 0.84                           # how far up a full cup the tea comes
LID = (29.5, 4.5)                         # half the lid's width, and how thick it is
STRAW_FOOT, STRAW_TIP = (6.0, -10.0), (-18.0, -102.0)
STRAW_WIDE = 7.5
PEARLS = [(0, -26), (13, -21), (-13, -20), (6, -17.5), (-6, -17), (11, -8), (0, -7.5), (-11, -8)]   # the top ones are drunk first
PEARL_R = 5.0
GRIP = (-30.0, 44.0)                      # from the middle of the hand that holds the cup to the middle of its base

# A cloud of gas: where it is let off, behind him and low down, and where it has drifted to
# by the time it is gone; how big it is at each end; and the puffs it is made of, each
# given by where it sits in the cloud and its size, in multiples of the cloud's.
GAS_FROM, GAS_TO = (-80.0, -56.0), (-134.0, -138.0)
GAS_SIZE = (10.0, 36.0)
PUFFS = [(0.0, 0.0, 1.0), (-0.78, 0.22, 0.68), (0.74, 0.30, 0.64), (-0.28, -0.66, 0.72), (0.48, -0.58, 0.60)]


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
               squash=0.0, lean=0.0, dx=0.0, dy=0.0,         # the whole mate; dy < 0 is up
               front=(False, False),                         # whether each arm is drawn in front of the body, not behind it
               loose=(1.0, 1.0),                             # how far the spring may carry each arm from its pose; 0 pins it there
               cup=None,                                     # a cup of bubble tea: see cup_parts for what to give
               gas=None)                                     # a cloud of gas, by its age: 0 just let off, 1 gone


def whole(pose):
    """How the whole mate is squashed, leant and moved, about the point between his feet."""
    return (shift(pose["dx"], pose["dy"]) @ turn(pose["lean"])
            @ stretch(1 + 0.7 * pose["squash"], 1 - pose["squash"]))


def shoulder(pose, side):
    """Where an arm starts, before the whole mate is moved."""
    return side * SHOULDER[0], SHOULDER[1] + (SEAT + SLUMP if pose["seated"] else 0)


def arm_line(side, lift, bend, start):
    """The line down the middle of an arm, from the shoulder to the wrist, and which way it
    is heading at each point along it."""
    n = 22
    theta = np.radians(lift + bend * np.linspace(0, 1, n))
    heading = np.stack([side * np.sin(theta), np.cos(theta)], 1)
    steps = (heading[:-1] + heading[1:]) / 2 * ARM / (n - 1)
    line = np.array(start, float) + np.concatenate([[(0.0, 0.0)], np.cumsum(steps, 0)])
    return line, heading


def hand_at(side, lift, bend, seated=False):
    """Where the middle of a hand is, before the whole mate is moved."""
    line, heading = arm_line(side, lift, bend, shoulder({"seated": seated}, side))
    return tuple(float(v) for v in line[-1] + heading[-1] * 5)


def reach(side, x, y, seated=False, elbow_out=True):
    """How far to lift and curl an arm, as (lift, bend), for the middle of its hand to be at
    (x, y). The arm bows outwards on the way there, or inwards if `elbow_out` is False. A
    place it cannot reach gets a straight arm pointing at it."""
    sx, sy = shoulder({"seated": seated}, side)
    out, down = side * (x - sx), y - sy                    # the hand, measured outwards and downwards from the shoulder

    def hanging(bend):                                     # the same, for an arm that sets off straight down and curls
        hx, hy = hand_at(1, 0.0, bend)
        return hx - SHOULDER[0], hy - SHOULDER[1]

    low, high = 0.0, 200.0                                 # the more it curls, the nearer the hand comes to the shoulder
    if math.hypot(out, down) >= math.hypot(*hanging(0.0)):
        high = 0.0
    for _ in range(40):
        mid = (low + high) / 2
        if math.hypot(*hanging(-mid)) > math.hypot(out, down):
            low = mid
        else:
            high = mid
    bend = -high if elbow_out else high
    hx, hy = hanging(bend)
    return math.degrees(math.atan2(out, down) - math.atan2(hx, hy)), bend


def arm_shapes(side, lift, bend, start):
    """The arm on one side (-1 left, 1 right): its shapes and the crease where the hand begins."""
    n = 22
    line, heading = arm_line(side, lift, bend, start)
    across = np.stack([heading[:, 1], -heading[:, 0]], 1) * side          # towards the outside of the arm
    r = np.linspace(ARM_R, WRIST_R, n)[:, None]
    tube = np.concatenate([line + across * r, (line - across * r)[::-1]])
    hand = line[-1] + heading[-1] * 5
    crease = [hand + (HAND_R - LINE / 2) * (-heading[-1] * math.cos(a) + across[-1] * math.sin(a))
              for a in np.radians(np.linspace(56, -12, 14))]
    return [tube, oval(*line[0], ARM_R), oval(*hand, HAND_R)], crease


def eye_line(cx, cy, state):
    """The shape of an eye that is drawn as a line, "closed" or "happy"; None for any other."""
    r = EYE_R
    us = np.linspace(-1, 1, 25)
    if state == "closed":                                   # asleep: a line curving down
        line = [(cx + u * r * 1.1, cy + r * (0.05 + 0.42 * (1 - u * u))) for u in us]
        return ribbon(line, [1.6 + 2.0 * math.sqrt(1 - u * u) for u in us])
    if state == "happy":                                    # ^ ^
        line = [(cx + u * r * 1.12, cy + r * (0.55 - 1.05 * (1 - u * u) ** 0.85)) for u in us]
        return ribbon(line, [2.0 + 2.6 * math.sqrt(1 - u * u) for u in us])
    return None


def eye_size(state):
    """Half the width and half the height of an eye that is drawn as a bead, and how far shut it is."""
    shut = state if isinstance(state, float) else 0.0
    r = EYE_R * (1.22 if state == "wide" else 1)
    return r * (1 + 0.08 * shut), max(r * (1 - shut), 1.3), shut


def draw_eye(c, m, cx, cy, state):
    line = eye_line(cx, cy, state)
    if line is not None:
        c.fill(move(m, line), INK)
        return
    r = EYE_R
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


def mouth_shapes(m, wide):
    """The mouth, in place: its lip, and the edge of each row of teeth, top then bottom. An
    edge runs along the teeth from one side of the mouth to the other and ends with two
    points well outside it, so that as a shape it takes in all of the row."""
    half_h = MOUTH_H * max(wide, 0.26)                     # shut, the two rows of teeth still show
    half_w = MOUTH_W * (1 + 0.05 * (1 - min(wide, 1)))      # shut, it spreads a little
    cx, cy = MOUTH[0], MOUTH[1] + 6 * (wide - 1)            # the jaw drops as it opens
    a = np.linspace(0, 2 * math.pi, 200, endpoint=False)
    lip = np.stack([cx + half_w * np.sign(np.cos(a)) * np.abs(np.cos(a)) ** (2 / MOUTH_POWER),
                    cy + half_h * np.sign(np.sin(a)) * np.abs(np.sin(a)) ** (2 / MOUTH_POWER)], 1)
    valleys = [-4 * TEETH[0], -2 * TEETH[0], 0.0, 2 * TEETH[0], 4 * TEETH[0]]
    tips = [-TEETH[1], -TEETH[0], TEETH[0], TEETH[1]]
    rows = []
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
        rows.append(move(m, edge))
    return move(m, lip), rows


def draw_mouth(c, m, wide):
    lip, rows = mouth_shapes(m, wide)
    lip_px = c.px(lip)
    c._fill(c.pen, lip_px, INK)
    gum = (inset(lip_px, LIP * OUT * SS) / (OUT * SS)) + (X0, Y0)      # back in units, already moved

    def teeth(layer):
        layer.fill(gum, GUM)
        for edge in rows:
            layer.fill(edge, TOOTH)
            layer.stroke(edge[:-2], TOOTH_LINE, INK)

    c.inside(gum, teeth)


def cup_parts(place, tilt, grow, level, drawn):
    """The shapes a cup of bubble tea is made of, with the middle of its base at `place`.
    It is tipped `tilt` degrees, `grow` times its full size and `level` full, from 1 down to
    0. `drawn` counts the pearls that have gone up the straw: 1.5 is one swallowed and
    another half way up."""
    m = shift(*place) @ turn(tilt) @ stretch(grow, grow)
    top = -CUP_TALL * CUP_FULL * level                                      # the surface of the tea
    half = CUP_BASE + (CUP_RIM - CUP_BASE) * (-top / CUP_TALL)              # half the cup's width there
    cup = soften([(-CUP_RIM, -CUP_TALL), (CUP_RIM, -CUP_TALL), (CUP_BASE, 0), (-CUP_BASE, 0)], [0, 0, 5, 5])
    tea = soften([(-half + CUP_WALL, top), (half - CUP_WALL, top),
                  (CUP_BASE - CUP_WALL, -CUP_WALL), (-CUP_BASE + CUP_WALL, -CUP_WALL)], [0, 0, 4, 4])
    lid = soften([(-LID[0], -CUP_TALL - LID[1]), (LID[0], -CUP_TALL - LID[1]),
                  (LID[0], -CUP_TALL + 1), (-LID[0], -CUP_TALL + 1)], [1.8] * 4, n=5)
    # The straw shows from the surface of the tea upwards; below that the tea hides it.
    foot, tip = np.array(STRAW_FOOT), np.array(STRAW_TIP)
    wet = foot + (tip - foot) * (top - foot[1]) / (tip[1] - foot[1])
    along = wet + (tip - wet) * np.linspace(0, 1, 12)[:, None]
    straw = ribbon(along, [STRAW_WIDE] * 12)
    left = PEARLS[min(math.ceil(drawn - 1e-9), len(PEARLS)):]              # a pearl leaves the cup as it starts up the straw
    rising = [wet + (tip - wet) * (drawn % 1)] if drawn % 1 > 1e-9 else []
    return dict(space=m, cup=move(m, cup), tea=move(m, tea), lid=move(m, lid), straw=move(m, straw),
                pearls=[move(m, oval(x, y, PEARL_R, n=20)) for x, y in left],
                rising=[move(m, oval(x, y, 3.0, n=16)) for x, y in rising])


def gas_cloud(age):
    """A cloud of gas at an age from 0, just let off, to 1, gone: where its middle is, how
    big it is and how solid."""
    out = 1 - (1 - age) ** 2.2                                             # away fast, then slowing
    cx, cy = (a + (b - a) * out for a, b in zip(GAS_FROM, GAS_TO))
    return cx, cy, GAS_SIZE[0] + (GAS_SIZE[1] - GAS_SIZE[0]) * out, ease(age, 0.0, 0.06) * (1 - ease(age, 0.5, 1.0))


def gas_parts(age):
    """The puffs of that cloud, and how solid it is."""
    cx, cy, r, solid = gas_cloud(age)
    return [oval(cx + x * r, cy + y * r, size * r, n=40) for x, y, size in PUFFS], solid


class Flat:
    """The painter for the look this pack has: every shape one flat colour with a dark edge.
    render() tells a painter what there is to draw, from the back to the front, in units
    and already in place, and then asks for the finished picture."""

    def __init__(self):
        self.c = Canvas()

    def gas(self, puffs, solid):
        layer = Canvas()
        layer.part(puffs, GAS, FINE)
        layer.img.putalpha(layer.img.getchannel("A").point(lambda a: round(a * solid)))
        self.c.img.alpha_composite(layer.img)

    def fur(self, shapes, attach, name):
        """One furry part: its shapes, how its own space lies on the canvas (for a painter
        that gives it a texture), and what it is called."""
        self.c.part(shapes)

    def crease(self, points):
        self.c.stroke(points, FINE)

    def eye(self, m, cx, cy, state):
        draw_eye(self.c, m, cx, cy, state)

    def mouth(self, m, wide):
        draw_mouth(self.c, m, wide)

    def cup(self, parts):
        c = self.c
        c.part([parts["cup"]], PLASTIC)
        c.fill(parts["tea"], TEA)
        for pearl in parts["pearls"]:
            c.fill(pearl, PEARL)
        c.part([parts["lid"]], PLASTIC)
        c.part([parts["straw"]], STRAW)
        for pearl in parts["rising"]:
            c.fill(pearl, PEARL)

    def finish(self):
        return self.c.finish()


def render(pose, painter=Flat):
    """The pose, drawn by a painter."""
    pose = {**DEFAULT, **pose}
    p = painter()
    everything = whole(pose)
    seated = pose["seated"]
    body = everything @ shift(0, SEAT if seated else 0)

    def arm(side):
        which = 0 if side < 0 else 1
        lift, bend = pose["arms"][which], pose["bend"][which]
        start = shoulder(pose, side)
        shapes, crease = arm_shapes(side, lift, bend, start)
        along = everything @ shift(*start) @ turn(-side * (lift + bend / 2))
        p.fur([move(everything, s) for s in shapes], along, "arm_l" if side < 0 else "arm_r")
        p.crease(move(everything, crease))

    if pose["gas"] is not None:
        p.gas(*gas_parts(pose["gas"]))

    for side, front in zip((-1, 1), pose["front"]):
        if not front:
            arm(side)

    if not seated:
        for side, (swing, lift) in zip((-1, 1), pose["legs"]):
            hip = (side * HIP[0], HIP[1])
            leg = everything @ shift(hip[0], hip[1] - lift) @ turn(-side * swing)
            p.fur([move(leg, LEG)], leg, "leg_l" if side < 0 else "leg_r")

    p.fur([move(body, BODY)], body, "body")
    face = body @ shift(*pose["look"])
    for side, state in zip((-1, 1), pose["eyes"]):
        p.eye(face, side * EYES[0], EYES[1], state)
    p.mouth(face, pose["mouth"])

    if seated:
        for side, (swing, lift) in zip((-1, 1), pose["legs"]):
            foot = everything @ stretch(side, 1) @ shift(0, -lift) @ turn(-swing, ANKLE)
            sx, sy, rx, ry, tilt = SOLE
            sole = oval(sx, sy, rx, ry, tilt)
            p.fur([move(foot, THIGH), move(foot, sole)], foot, "foot_l" if side < 0 else "foot_r")
            # Drawn as one part, the sole has no edge where it lies over the leg, so that
            # stretch of it is put back with a finer line.
            rim = inset(sole, LINE / 2)
            p.crease(move(foot, rim[15:42]))

    if pose["cup"] is not None:
        x, y, tilt, grow, level, drawn = pose["cup"]
        p.cup(cup_parts(move(everything, [(x, y)])[0], tilt + pose["lean"], grow, level, drawn))

    for side, front in zip((-1, 1), pose["front"]):
        if front:
            arm(side)
    return p.finish()


# ---------------------------------------------------------------- movement

ARM_HZ, ARM_DAMPING = 3.4, 0.50         # how fast an arm swings back, and how soon it settles
ARM_PUSH = 0.55                         # how hard the body's movement throws the arms about
ARM_CURL = 2.6                          # degrees the hand trails behind per radian/second of swing


def animate(clip, seconds, fps, calm, loop=True, step=1 / 500):
    """Samples clip(t) through one turn of the loop, lets the arms swing, and returns the
    frames as (pose, milliseconds). A frame is held for as long as nothing has visibly
    moved; a calm clip waits for a little more movement, so the tail end of a settling arm
    does not cost a frame every time. A clip that is played once and not looped (an action)
    is worked out the same way, as it starts and ends standing at rest, but its last frame
    is kept where it is and not joined on to its first."""
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
                loose = poses[i]["loose"][a]
                if loose != 1:                             # an arm with something to hold is kept to its pose
                    lifts[i, a] = math.degrees(target[i] + loose * (angle - target[i]))
                    curls[i, a] = posed[i] + loose * (curls[i, a] - posed[i])

    frames, every, ms, within = [], int(round(1 / fps / step)), round(1000 / fps), 1.2 if calm else 0.25
    for i in range(0, n, every):
        pose = {**poses[i], "arms": (round(float(lifts[i, 0]), 1), round(float(lifts[i, 1]), 1)),
                "bend": (round(float(curls[i, 0]), 1), round(float(curls[i, 1]), 1))}
        if frames and same(frames[-1][0], pose, within):
            frames[-1] = (frames[-1][0], frames[-1][1] + ms)
        else:
            frames.append((pose, ms))
    if loop and len(frames) > 1 and same(frames[0][0], frames[-1][0], within):
        frames[0] = (frames[0][0], frames[0][1] + frames.pop()[1])
    return frames


def same(a, b, within):
    """Whether two poses would look the same on screen: nothing more than `within` degrees
    or units apart."""
    def flat(p):
        x, y, tilt, grow, level, drawn = p["cup"] or (0, 0, 0, 0, 0, 0)
        cx, cy, r, solid = gas_cloud(p["gas"]) if p["gas"] is not None else (0, 0, 0, 0)
        return [*p["arms"], *(0.5 * v for v in p["bend"]), *p["legs"][0], *p["legs"][1], *(2 * v for v in p["look"]),
                p["mouth"] * 60, p["squash"] * 150, p["lean"] * 2, p["dx"], p["dy"],
                x, y, tilt, grow * 44, level * 47, drawn * 60, cx, cy, 2 * r, solid * 40]
    def kind(p):
        return p["eyes"], p["seated"], p["front"], p["cup"] is None, p["gas"] is None
    return kind(a) == kind(b) and max(abs(x - y) for x, y in zip(flat(a), flat(b))) < within


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


def mix(a, b, t):
    """From a to b as t goes from 0 to 1, for numbers or runs of them."""
    return tuple(x + (y - x) * t for x, y in zip(a, b)) if isinstance(a, tuple) else a + (b - a) * t


def bubble_tea(t):
    """Brings out a cup of bubble tea and gives it a shake. Takes three long pulls at the
    straw, each fetching a pearl up it, lowers the cup with a happy sigh and sways, then
    goes back for the rest, four more pulls, until the tea is all but gone. Peers into the
    cup at the one pearl left at the bottom, shakes it, gives up with a sigh and puts the
    cup away. The arm that holds the cup comes round in front of him, and is kept from
    swinging while it has something to hold."""
    rest, out = (24.0, -14.0), (52.0, 4.0)                   # the arm hanging, and swung out to the side
    raised = reach(1, 69, -109)                              # lifting the straw into his mouth
    shaking = bump(t, 0.70, 0.08, 0.56, 0.08)                # shaking the cup to mix it up
    wobble = math.sin(2 * math.pi * (t - 0.70) / 0.28)
    peer = bump(t, 6.50, 0.22, 0.90, 0.20)                   # holding it up to look inside
    jiggle = math.sin(2 * math.pi * (t - 6.86) / 0.24) * bump(t, 6.86, 0.05, 0.38, 0.05)
    held = reach(1, 70 + 5 * wobble * shaking + 10 * peer, -98 - 3 * abs(wobble) * shaking + 6 * peer)
    have = 0.24 <= t < 8.06                                  # the cup is out, and that arm is in front
    first, second = (1.70, 2.14, 2.58), (4.74, 5.16, 5.58, 6.00)
    pulls = first + second
    pull = max(bump(t, at, 0.10, 0.14, 0.12) for at in pulls)
    sipping = bump(t, 1.46, 0.14, 1.44, 0.14) + bump(t, 4.50, 0.14, 1.70, 0.14)
    sigh = bump(t, 3.22, 0.10, 0.30, 0.16)                   # a happy one after the first sips
    sway = bump(t, 3.56, 0.20, 0.56, 0.20)
    glum = bump(t, 7.42, 0.12, 0.30, 0.18)                   # and a glum one when it has run out
    hop = bump(t, 0.24, 0.10, 0.0, 0.16)                     # a little jump for joy as the cup appears

    arm = mix(mix(rest, out, ease(t, 0.0, 0.24)), held, ease(t, 0.28, 0.56))
    arm = mix(arm, raised, sipping)
    arm = mix(mix(arm, out, ease(t, 7.80, 8.06)), rest, ease(t, 8.08, 8.34))
    cup = None
    if have:
        grow = (0.3 + 0.82 * ease(t, 0.24, 0.42) - 0.12 * ease(t, 0.42, 0.54)) * (1 - 0.7 * ease(t, 7.82, 8.06))
        tilt = (14 * (1 - ease(t, 0.28, 0.54)) + 14 * ease(t, 7.80, 8.04)
                + 9 * wobble * shaking - 12 * peer + 10 * jiggle)
        hx, hy = hand_at(1, *arm)
        cup = (round(hx + GRIP[0] * grow, 1), round(hy + GRIP[1] * grow, 1), round(tilt, 1), round(grow, 2),
               round(1 - 0.38 * ease(t, first[0], first[-1] + 0.36) - 0.52 * ease(t, second[0], second[-1] + 0.36), 2),
               round(sum(ease(t, at + 0.04, at + 0.38) for at in pulls), 2))
    if 0.34 <= t < 6.50:
        eyes = HAPPY
    elif glum > 0.3:
        eyes = (0.6, 0.6)
    else:
        eyes = OPEN
    return dict(eyes=eyes,
                mouth=round(1 + 0.12 * hop - 0.48 * sipping - 0.10 * pull + 0.24 * sigh - 0.3 * peer + 0.12 * glum, 2),
                squash=0.018 * pull - 0.022 * sigh - 0.03 * hop + 0.02 * glum, dy=-8 * hop,
                lean=round(-2.0 * sigh + 2.5 * math.sin(2 * math.pi * (t - 3.56) / 0.98) * sway + 1.5 * glum, 2),
                look=(round(4 * peer, 1), round(3 * sipping + 6 * peer, 1)),
                arms=(24 + 10 * sigh + 14 * glum, arm[0]), bend=(-14 + 24 * sigh + 30 * glum, arm[1]),
                front=(False, have), loose=(1.0, 1 - ease(t, 0.16, 0.24) + ease(t, 8.06, 8.20)), cup=cup)


def fart(t):
    """Glances one way and the other to see that no one is looking, and strains, but
    nothing comes. Looks round behind him, puzzled, tries again harder and lets one go with
    a hop. Looks relieved, wafts the cloud away with the arm on that side for a good while,
    and then looks off into the distance as if nothing had happened."""
    first = ease(t, 1.05, 1.50) * (1 - ease(t, 2.05, 2.30))  # a try that comes to nothing
    second = ease(t, 2.85, 3.30) * (1 - ease(t, 3.64, 3.68)) # and one that does
    strain = max(0.8 * first, second)
    shaking = 0.6 * ease(t, 1.25, 1.40) * (1 - ease(t, 2.00, 2.10)) + ease(t, 3.05, 3.25) * (1 - ease(t, 3.62, 3.66))
    shake = (1.2 if int(t / 0.06) % 2 else -1.2) * shaking
    huh = bump(t, 2.28, 0.16, 0.36, 0.16)                    # puzzled that nothing came
    air = min(max((t - 3.66) / 0.34, 0.0), 1.0)              # the hop, from leaving the floor to landing
    landed = max(0.0, t - 4.00)
    relief = bump(t, 4.00, 0.14, 1.0, 0.3)
    waft = bump(t, 4.40, 0.18, 1.40, 0.20)
    innocent = bump(t, 6.18, 0.20, 0.66, 0.20)               # nothing to do with him
    if t < 1.2:
        eyes = OPEN
    elif t < 3.66:
        eyes = CLOSED if second > 0.5 else (0.55, 0.55) if first > 0.5 else OPEN
    elif t < 4.00:
        eyes = WIDE
    else:
        eyes = HAPPY if t < 4.56 else OPEN
    look = (-7 * bump(t, 0.10, 0.16, 0.22, 0.14) + 7 * bump(t, 0.64, 0.16, 0.22, 0.14)
            - 6 * huh - 8 * bump(t, 4.50, 0.20, 1.30, 0.22) + 7 * innocent,
            2 * huh - 4 * innocent)
    return dict(eyes=eyes,
                mouth=round(1 - 0.95 * strain + 0.25 * math.sin(math.pi * air) + 0.06 * relief - 0.3 * huh - 0.45 * innocent, 2),
                squash=0.075 * strain - 0.07 * math.sin(math.pi * air)
                       + (0.07 * math.exp(-landed * 9) * math.cos(landed * 16) if t >= 4.00 else 0.0),
                dy=-14 * 4 * air * (1 - air), dx=round(shake, 1) + 3 * relief,
                lean=round(-2.5 * strain + 3.0 * relief - 2.0 * huh + 1.5 * math.sin(2 * math.pi * (t - 6.18) / 0.76) * innocent, 2),
                look=(round(look[0], 1), round(look[1], 1)),
                arms=(24 + 12 * strain + 16 * huh + 70 * waft
                      + 16 * math.sin(2 * math.pi * (t - 4.48) / 0.36) * bump(t, 4.54, 0.08, 1.18, 0.1),
                      24 + 12 * strain + 16 * huh),
                bend=(-14 - 44 * strain + 20 * huh + 44 * waft, -14 - 44 * strain + 20 * huh),
                gas=round((t - 3.64) / 2.4, 3) if 3.64 < t < 6.04 else None)


CLIPS = {
    # key: file, name in the Dance move or Actions menu, the clip, its length, frames a second, calm
    "idle": ("idle.webp", None, idle, 10.0, 20, True),
    "walk": ("walk.webp", None, walk, 0.52, 25, False),
    "sit": ("sit.webp", None, sitting, 7.0, 20, True),
    "sleep": ("sleep.webp", None, asleep, 4.0, 20, True),
    "dance": ("dance.webp", "Happy Arms", happy_arms, 1.0, 25, False),
    "dance_chomp": ("dance_chomp.webp", "Chomp", chomp, 1.0, 25, False),
    "dance_stomp": ("dance_stomp.webp", "Monster Stomp", stomp, 1.0, 25, False),
    # Actions: played once through, off the beat, so they begin and end standing at rest.
    "action_bubble_tea": ("action_bubble_tea.webp", "Bubble Tea", bubble_tea, 8.6, 12.5, True),
    "action_fart": ("action_fart.webp", "Fart", fart, 7.32, 50 / 3, True),
    "drag": ("drag.webp", None, carried, 0.40, 25, False),
    "fall": ("fall.webp", None, falling, 0.24, 25, False),
}


def build(key, painter=Flat):
    """Renders one clip: its frames cropped to what they use, their timings, and where the
    feet are in the cropped frames."""
    _, _, clip, seconds, fps, calm = CLIPS[key]
    timeline = animate(clip, seconds, fps, calm, loop=not key.startswith("action"))
    images = [render(pose, painter) for pose, _ in timeline]
    used = np.max([im[..., 3] for im in images], axis=0) > 0
    ys, xs = np.nonzero(used.any(axis=1))[0], np.nonzero(used.any(axis=0))[0]
    assert xs[0] > 0 and ys[0] > 0 and xs[-1] < W - 1 and ys[-1] < H - 1, f"{key} runs off the canvas"
    x0, y0, x1, y1 = max(xs[0] - 2, 0), max(ys[0] - 2, 0), xs[-1] + 3, ys[-1] + 3
    anchor = [round(-X0 * OUT - x0, 1), round(-Y0 * OUT - y0, 1)]
    return [Image.fromarray(im[y0:y1, x0:x1], "RGBA") for im in images], [ms for _, ms in timeline], anchor


def build_pack(pack, name, painter=Flat, sheet=None, **webp):
    """Builds every clip and character.json into a pack folder, drawn by a painter. `webp`
    is how the animations are saved; `sheet` is where to put every frame on one page."""
    manifest = {"name": name, "height": 150, "facing": "right", "removeBackground": False, "clips": {}}
    standing = render({}, painter)[..., 3].any(axis=1).sum()   # how tall the mate is standing still, in saved pixels
    rows, pixels = [], 0
    for key, (file, title, *_) in CLIPS.items():
        images, durations, anchor = build(key, painter)
        if len(images) == 1:
            file = file.rsplit(".", 1)[0] + ".png"
            images[0].save(pack / file, optimize=True)
        else:
            images[0].save(pack / file, save_all=True, append_images=images[1:], duration=durations, loop=0, **webp)
        manifest["clips"][key] = {"file": file, "anchor": anchor, **({"name": title} if title else {})}
        if key == "idle":
            # The app makes the idle clip, at its tallest, `height` pixels high. Should idle
            # ever reach above his head, that would shrink him, so allow for it.
            manifest["height"] = round(150 * (images[0].height - 4) / standing)
        rows.append(images)
        pixels += len(images) * images[0].width * images[0].height
        print(f"{file}: {len(images)} frames of {images[0].width}x{images[0].height}, {sum(durations) / 1000:.2f}s, "
              f"{(pack / file).stat().st_size // 1024} KB")
    print(f"all clips: {sum(len(r) for r in rows)} frames, {pixels * 4 / 2 ** 20:.0f} MB once the app has unpacked them")

    (pack / "character.json").write_text(json.dumps(manifest, indent=2) + "\n")
    written = {clip["file"] for clip in manifest["clips"].values()}
    for stray in sorted(f.name for f in pack.iterdir() if f.suffix in (".webp", ".png", ".gif") and f.name not in written):
        print(f"note: {stray} was not written by this run; the app will load it as a clip of its own")

    if sheet:
        cell = 110
        cols = 26
        lines = sum(-(-len(r) // cols) for r in rows)
        page, line = Image.new("RGBA", (cols * cell, lines * cell), (40, 44, 64, 255)), 0
        for images in rows:
            for i, im in enumerate(images):
                t = im.copy()
                t.thumbnail((cell - 4, cell - 4), Image.LANCZOS)
                page.alpha_composite(t, ((i % cols) * cell + (cell - t.width) // 2,
                                         (line + i // cols) * cell + (cell - t.height) // 2))
            line += -(-len(images) // cols)
        page.save(sheet)


def main():
    # Flat colour packs down to very little with no loss at all.
    build_pack(PACK, "Domo", sheet=HERE / "sheet.png" if "--sheet" in sys.argv else None,
               lossless=True, quality=100, method=4)


if __name__ == "__main__":
    main()
