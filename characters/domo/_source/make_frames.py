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
tea, and let off a cloud of gas: two of his actions, which play once through rather than
loop. The third has an apple tree and an apple in it, which are drawn here too.

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


def set_canvas(x0, y0, x1, y1):
    """Makes the canvas another size, and returns what it was. A clip that needs more room
    than the others is given it while it is drawn (see ROOM), and no other clip pays for
    it; the frames that are saved are cropped to what they use either way."""
    global X0, Y0, X1, Y1, W, H
    was = (X0, Y0, X1, Y1)
    X0, Y0, X1, Y1 = x0, y0, x1, y1
    W, H = round((X1 - X0) * OUT), round((Y1 - Y0) * OUT)
    return was

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
BARK = (158, 114, 76)
BARK_DARK = (126, 86, 54)                 # its shaded side, and the lines in it
BARK_LIGHT = (184, 142, 100)
LEAF = (104, 178, 74)
LEAF_DARK = (70, 140, 62)                 # the leaves at the back and underneath
LEAF_LIGHT = (150, 208, 98)               # and where the light catches them
LEAF_SHADE = (66, 134, 60)
APPLE = (226, 46, 40)
UNRIPE = (170, 208, 86)
STALK = (96, 64, 38)
APPLE_SHINE = (255, 220, 212)
APPLE_BLUSH = (248, 196, 76)              # the yellow side of a ripe one
SPARK = (255, 222, 96)
SPARK_EDGE = (226, 150, 26)
SPARK_CORE = (255, 251, 226)
PUFF = (246, 244, 236)

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

# An apple tree, measured from the foot of its trunk. It stands to his right and a little
# behind him, half as tall again as he is, with its leaves spreading over his head.
TREE_AT = 180.0                           # where the foot of the trunk is
TRUNK = ((0, 0), (8, -80), (-14, -160), (-8, -236))       # the line up the middle of the trunk, to where it forks
TRUNK_WIDE = (48.0, 30.0)                 # how wide the trunk is at its foot and at the fork
# Its boughs, from the fork: the line up the middle of each, and how wide it is at each end.
BOUGHS = [(((-8, -236), (-34, -262), (-62, -288), (-84, -318)), (24.0, 10.0)),
          (((-8, -236), (-14, -288), (-2, -328), (-8, -370)), (24.0, 10.0)),
          (((-8, -236), (18, -262), (42, -284), (58, -312)), (22.0, 9.0))]
ROOTS = [[(-20, 2), (-56, 2), (-44, -8), (-22, -22)], [(20, 2), (50, 2), (40, -7), (22, -18)]]
CROWN = (-32.0, -378.0)                   # the middle of the leaves
# The leaves are clumps: where each is from the middle of the leaves, its size, which layer
# it is in (0 shaded, at the back and underneath; 1 the body of the tree; 2 where the
# light catches it) and how long after the leaves start to come out it does, in seconds.
CLUMPS = [(-78, 46, 52, 0, 0.00), (74, 50, 54, 0, 0.03), (0, 62, 50, 0, 0.06), (-104, -6, 46, 0, 0.05), (86, -4, 40, 0, 0.08),
          (-52, -28, 62, 1, 0.10), (46, -34, 64, 1, 0.13), (0, 10, 70, 1, 0.08), (-6, -72, 58, 1, 0.17),
          (-84, -62, 42, 1, 0.20), (84, -64, 42, 1, 0.22),
          (-44, -66, 36, 2, 0.26), (20, -86, 34, 2, 0.29), (-78, -18, 28, 2, 0.31), (62, -56, 30, 2, 0.33), (4, -22, 30, 2, 0.30)]
# Leaves that stick out round the edge: where from the middle of the leaves, and which way they point.
TWIGS = [(-34, -118, -112), (38, -112, -62), (-104, -100, -142), (-148, -4, 176), (-128, 70, 146), (-34, 110, 104),
         (108, -98, -38), (104, 44, 22), (40, 104, 70), (-150, -40, -166)]
FRUIT = [(-70, 12), (-22, 44), (42, 26), (84, -12), (14, -40), (-48, -52)]     # the apples that stay on the tree, likewise
FRUIT_R = 9.5
HANG = (-26.0, 105.0)                     # where the apple that drops hangs from, from the middle of the leaves
STALK_LONG = 7.0                          # from there to the top of the apple
# Tufts of grass at its foot: how far along the ground, and which way each blade points.
GRASS = [(-58, -118), (-50, -96), (-64, -140), (48, -70), (56, -92), (42, -52)]

APPLE_R = 22.0
# The outline of an apple 18 units across its middle, measured from there: dimpled at the top and the bottom.
APPLE_SHAPE = [(0, -14), (8.5, -17.5), (16.5, -10.5), (18.4, 0), (14.5, 12.5), (6, 17.6), (0, 16.2),
               (-6, 17.6), (-14.5, 12.5), (-18.4, 0), (-16.5, -10.5), (-8.5, -17.5)]


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
               gas=None,                                     # a cloud of gas, by its age: 0 just let off, 1 gone
               tree=None,                                    # an apple tree: see tree_parts for what to give
               apple=None,                                   # an apple, in front of everything: see apple_parts
               fx=())                                        # twinkles ("spark", x, y, size, spin, solid) and puffs ("puff", x, y, size, solid)


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


def curve_at(points, u):
    """Places along a curve from the first point to the last, bent towards the two between."""
    p0, c1, c2, p1 = (np.array(p, float) for p in points)
    u = np.asarray(u, float)[:, None]
    return (1 - u) ** 3 * p0 + 3 * (1 - u) ** 2 * u * c1 + 3 * (1 - u) * u ** 2 * c2 + u ** 3 * p1


def leaf_shape(length, wide):
    """A leaf, pointed at both ends, lying along x from its stalk at (0, 0)."""
    return np.concatenate([bezier((0, 0), (length * 0.3, -wide), (length * 0.7, -wide), (length, 0)),
                           bezier((length, 0), (length * 0.7, wide), (length * 0.3, wide), (0, 0))])


def bent(points, sway):
    """The tree's points with the tree bent over: turned about its foot by `sway` degrees at
    the height of Domo's head, by less lower down and by more higher up."""
    p = np.asarray(points, float).reshape(-1, 2)
    a = np.radians(sway) * np.clip(-p[:, 1] / 300, 0, 1.7)
    c, sn = np.cos(a), np.sin(a)
    return np.stack([p[:, 0] * c - p[:, 1] * sn, p[:, 0] * sn + p[:, 1] * c], 1)


def tree_parts(rise, leaves, sway, tall, size):
    """The shapes an apple tree is made of. `rise` is how much of it has come up, from 0 to
    1: the trunk first and then the boughs. `leaves` is how many seconds ago its leaves
    began to come out, which they do a clump at a time; `sway` bends it over, in degrees;
    `tall` stretches it upwards (more than 1) or squashes it down; `size` is how big all of
    it is. Also where the apple that drops hangs from."""
    m = shift(TREE_AT, 0) @ stretch(size * (1 + 0.5 * (1 - tall)), size * tall)

    def place(points):
        return move(m, bent(points, sway))

    def limb(line, wide, upto, foot=0.0):
        """A trunk or a bough, as far as it has grown: its shapes, and the line up its middle with how wide it is there."""
        u = np.linspace(0, max(upto, 0.04), 26)
        middle = curve_at(line, u)
        across = (wide[0] + (wide[1] - wide[0]) * u) * (0.45 + 0.55 * rise) * (1 + foot * np.exp(-u / 0.035))
        return [ribbon(middle, across), oval(*middle[-1], across[-1] / 2, n=24)], middle, across

    grown = min(rise / 0.7, 1.0)
    out = ease(rise, 0.66, 1.0)                                              # how far the boughs have come out
    shapes, middle, across = limb(TRUNK, TRUNK_WIDE, grown, foot=0.5)
    wood = [place(s) for s in shapes]
    along = np.gradient(middle, axis=0)
    side = np.stack([-along[:, 1], along[:, 0]], 1) / np.hypot(along[:, 0], along[:, 1])[:, None]      # to its right, as it is drawn

    def strip(a, b):                                                         # a band up the trunk, between two places across it
        half = across[:, None] / 2
        return place(np.concatenate([middle + side * half * a, (middle + side * half * b)[::-1]]))

    shade, shine, bark = [strip(0.30, 0.84)], [strip(-0.84, -0.56)], []
    if grown > 0.3:
        wood += [place(soften(root, [0, 6, 4, 0])) for root in ROOTS]
        for at, lo, hi, phase in ((-0.34, 0.10, 0.46, 0.0), (0.02, 0.26, 0.72, 2.0), (-0.16, 0.56, 0.94, 4.0), (0.52, 0.14, 0.62, 1.0)):
            u = np.linspace(lo, min(hi, grown), 14)
            if u[-1] - u[0] > 0.08:                                          # the lines in the bark, as far up as it has grown
                k = np.clip(np.rint(u / max(grown, 0.04) * 25).astype(int), 0, 25)
                bark.append(place(middle[k] + side[k] * across[k, None] / 2 * (at + 0.07 * np.sin(11 * u + phase))[:, None]))
        if grown > 0.6:                                                      # and a knot
            k = int(round(0.52 / grown * 25))
            bark.append(place(oval(*(middle[k] + side[k] * across[k] * 0.04), 4.6, 7.2, n=18)))
    if out > 0.02:
        for line, wide in BOUGHS:
            wood += [place(s) for s in limb(line, wide, out)[0]]
    grass = [place(move(shift(x, 1) @ turn(angle), leaf_shape(16, 3.6) * ease(rise, 0.08, 0.4)))
             for x, angle in GRASS] if rise > 0.12 else []

    # Two leaves on the tip of the shoot, until the rest come out and hide them.
    shoot = ease(rise, 0.02, 0.06) * (1 - ease(leaves, 0.0, 0.2))
    tip = curve_at(BOUGHS[1][0], [out])[0] if out > 0.02 else middle[-1]
    sprout = [place(move(shift(*tip) @ turn(angle), leaf_shape(26 * shoot, 8.5 * shoot))) for angle in (-128, -40)] if shoot > 0.05 else []

    back, body, light, scallops, fruit = [], [], [], [], []
    centre = np.array(CROWN)
    if leaves > 0:
        for dx, dy, r, layer, wait in CLUMPS:
            big = r * spring(leaves - wait, 2.8, 10.0)
            if big < 1.5:
                continue
            (back, body, light)[layer].append(place(oval(centre[0] + dx, centre[1] + dy, big, n=48)))
            if layer == 1:                                                   # a curl on each clump of leaves
                a = np.radians(np.linspace(205, 318, 12))
                scallops.append(place(np.stack([centre[0] + dx + 0.56 * big * np.cos(a), centre[1] + dy + 0.56 * big * np.sin(a)], 1)))
        out_ = spring(leaves - 0.24, 3.0, 9.0)
        if out_ > 0.1:
            body += [place(move(shift(centre[0] + dx, centre[1] + dy) @ turn(angle), leaf_shape(19 * out_, 7 * out_))) for dx, dy, angle in TWIGS]
        for k, (dx, dy) in enumerate(FRUIT):
            ripe = spring(leaves - 0.46 - 0.04 * k, 3.0, 9.0)
            if ripe > 0.1:
                r = FRUIT_R * ripe
                fruit.append((place(oval(centre[0] + dx, centre[1] + dy, r, r * 0.95, n=24)),
                              place(oval(centre[0] + dx - 0.4 * r, centre[1] + dy - 0.36 * r, 0.2 * r, 0.3 * r, 26, n=12))))
    hang = centre + np.array(HANG) * min(spring(leaves, 2.8, 10.0), 1.0) if leaves > 0 else np.array(tip, float)
    # `space` is how the tree's own space lies on the canvas, near enough: for a painter that gives it a texture.
    return dict(space=m @ turn(sway), grass=grass, wood=wood, shade=shade, shine=shine, bark=bark, sprout=sprout,
                back=back, body=body, light=light, scallops=scallops, fruit=fruit,
                hang=tuple(float(v) for v in place([hang])[0]))


def apple_parts(x, y, spin, size, squash, ripe):
    """The shapes of an apple with its middle at (x, y), turned `spin` degrees, `size` times
    full size, squashed against the floor by `squash`, and `ripe` from 0, green, to 1, red."""
    r = APPLE_R * size
    m = (shift(x, y) @ shift(0, r) @ stretch(1 + 0.7 * squash, 1 - squash) @ shift(0, -r)
         @ turn(spin) @ stretch(r / 18, r / 18))
    return dict(space=m, ripe=ripe, body=move(m, through(APPLE_SHAPE, n=8)),
                stalk=move(m, ribbon([(0, -13), (1.2, -19), (4, -25)], [4.4, 3.6, 3.2])),
                leaf=move(m, move(shift(2.5, -21.5) @ turn(-24), leaf_shape(16, 5.6))),
                blush=move(m, oval(6.0, 5.0, 8.0, 9.4, 18, n=28)),
                shine=move(m, oval(-8.2, -6.5, 3.4, 6.0, 26, n=20)))


def spark_parts(x, y, size, spin):
    """A twinkle, as a four-pointed star, its edge and a smaller star inside it."""
    def star(r, waist=0.36):
        a = np.radians(spin + np.arange(8) * 45)
        far = np.where(np.arange(8) % 2 == 0, r, waist * r)
        return np.stack([x + far * np.sin(a), y - far * np.cos(a)], 1)
    return star(size + 2.2, 0.46), star(size), star(size * 0.5)


def puff_parts(x, y, r):
    """A puff of dust or smoke."""
    return [oval(x + px * r, y + py * r, size * r, n=36) for px, py, size in PUFFS]


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

    def tree(self, parts):
        c = self.c
        if parts["grass"]:
            c.part(parts["grass"], LEAF, FINE)
        c.part(parts["wood"], BARK)
        for band, colour in ((parts["shade"], BARK_DARK), (parts["shine"], BARK_LIGHT)):
            for shape in band:
                c.fill(shape, colour)
        for line in parts["bark"]:
            c.stroke(line, FINE, BARK_DARK)
        if parts["sprout"]:
            c.part(parts["sprout"], LEAF, FINE)
        if parts["back"]:
            c.part(parts["back"], LEAF_DARK)
        if parts["body"]:
            c.part(parts["body"], LEAF)
        for clump in parts["light"]:
            c.fill(clump, LEAF_LIGHT)
        for curl in parts["scallops"]:
            c.stroke(curl, FINE, LEAF_SHADE)
        for apple, shine in parts["fruit"]:
            c.part([apple], APPLE, FINE)
            c.fill(shine, APPLE_SHINE)

    def apple(self, parts):
        c = self.c
        c.part([parts["stalk"]], STALK, 1.0)
        c.part([parts["leaf"]], LEAF, FINE)
        skin = tuple(round(a + (b - a) * parts["ripe"]) for a, b in zip(UNRIPE, APPLE))
        c.part([parts["body"]], skin, 2.0)
        c.fill(parts["blush"], tuple(round(a + (b - a) * parts["ripe"]) for a, b in zip(skin, APPLE_BLUSH)))
        c.fill(parts["shine"], APPLE_SHINE)

    def _faded(self, paint, solid):
        """Paints on a sheet of its own and lays that on at a strength from 0 to 1."""
        layer = Canvas()
        paint(layer)
        if solid < 1:
            layer.img.putalpha(layer.img.getchannel("A").point(lambda a: round(a * solid)))
        self.c.img.alpha_composite(layer.img)

    def spark(self, edge, star, core, solid):
        def paint(layer):
            layer.fill(edge, SPARK_EDGE)
            layer.fill(star, SPARK)
            layer.fill(core, SPARK_CORE)
        self._faded(paint, solid)

    def puff(self, puffs, solid):
        self._faded(lambda layer: layer.part(puffs, PUFF, FINE), solid)

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

    if pose["tree"] is not None:
        p.tree(tree_parts(*pose["tree"]))
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

    # What is not part of him is not moved with him: it is given in units, where it is.
    if pose["apple"] is not None:
        p.apple(apple_parts(*pose["apple"]))
    for kind, x, y, size, *more in pose["fx"]:
        if kind == "spark":
            p.spark(*spark_parts(x, y, size, more[0]), more[1])
        else:
            p.puff(puff_parts(x, y, size), more[0])
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
        rise, leaves, sway, tall, size = p["tree"] or (0, 0, 0, 0, 0)
        ax, ay, spin, big, flat_, ripe = p["apple"] or (0, 0, 0, 0, 0, 0)
        return [*p["arms"], *(0.5 * v for v in p["bend"]), *p["legs"][0], *p["legs"][1], *(2 * v for v in p["look"]),
                p["mouth"] * 60, p["squash"] * 150, p["lean"] * 2, p["dx"], p["dy"],
                x, y, tilt, grow * 44, level * 47, drawn * 60, cx, cy, 2 * r, solid * 40,
                rise * 500, leaves * 400, sway * 8, tall * 500, size * 500,
                ax, ay, spin * 0.3, big * 40, flat_ * 40, ripe * 30]
    def kind(p):
        return (p["eyes"], p["seated"], p["front"], p["cup"] is None, p["gas"] is None,
                p["tree"] is None, p["apple"] is None, p["fx"])
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


# ---- the apple tree

def spring(since, hz, fade):
    """From 0 to 1 the way something on a spring gets there: fast, a little too far, and back."""
    if since <= 0:
        return 0.0
    w = 2 * math.pi * hz
    return 1 - math.exp(-fade * since) * (math.cos(w * since) + fade / w * math.sin(w * since))


def ring(since, hz, fade):
    """A wobble that starts from nothing, swings out and dies away."""
    return math.exp(-fade * since) * math.sin(2 * math.pi * hz * since) if since > 0 else 0.0


def arc(t, start, long):
    """0, up to 1 and back to 0, the way something thrown goes up and comes down."""
    u = min(max((t - start) / long, 0.0), 1.0)
    return 4 * u * (1 - u)


# When things happen, in seconds.
SHOOT = 0.84                               # a shoot pops out of the ground
BURST = 1.80                               # the tree is up, and its leaves burst out
SNAP = 4.10                                # the apple's stalk gives
POOF = 4.72                                # the tree goes back where it came from
RUN_FROM = 5.42                            # he bolts, to the left
LEAP, LEAP_LONG = 8.00, 0.74               # the apple is at his heels: he jumps, and it rolls on under him
TURN = LEAP + 1.26                         # the apple, which had stopped, starts back towards him
RUN_BACK = TURN + 0.28                     # so he bolts the other way
BUMP = 13.16                               # the apple hits something and is thrown up in the air
CATCH = BUMP + 0.60                        # and comes down in his mouth
GULP = CATCH + 0.90                        # which, after a moment, he shuts

RUN_SPEED = 310.0                          # units a second, flat out
STRIDE = 0.30                              # seconds for two steps, flat out
FALLING = 2600.0                           # how fast things pick up speed as they fall, units a second every second
BOUNCE = 0.42                              # how much of its speed the apple keeps when it hits the floor


def his_speed(t):
    """How fast he is running, in units a second. Less than nothing is to the left."""
    if t < RUN_BACK:
        return -RUN_SPEED * ease(t, RUN_FROM, RUN_FROM + 0.35) * (1 - ease(t, LEAP + 0.05, LEAP + 0.50))
    return RUN_SPEED * ease(t, RUN_BACK, RUN_BACK + 0.35) * (1 - ease(t, CATCH, CATCH + 0.48))


def apple_speed(t):
    """How fast the apple is rolling along the floor, likewise. It is slow to get going,
    then comes on faster than he can run; rolls on under him when he jumps, and stops;
    and then comes back the other way."""
    if t < TURN:
        return -(300 * ease(t, RUN_FROM + 0.08, RUN_FROM + 0.63) + 150 * ease(t, LEAP - 0.82, LEAP - 0.42)) * (1 - ease(t, LEAP + 0.50, LEAP + 1.00))
    return 290 * ease(t, TURN, TURN + 0.78) + 46 * ease(t, RUN_BACK + 1.9, RUN_BACK + 2.3)


# Where each has got to by each 500th of a second, and how many strides he has run.
_HE = np.concatenate([[0.0], np.cumsum([his_speed(i / 500) for i in range(17 * 500)]) / 500])
_IT = np.concatenate([[0.0], np.cumsum([apple_speed(i / 500) for i in range(17 * 500)]) / 500])
_STRIDES = np.concatenate([[0.0], np.cumsum([abs(his_speed(i / 500)) for i in range(17 * 500)]) / 500]) / (RUN_SPEED * STRIDE)


def at_time(table, t):
    return float(table[min(max(int(round(t * 500)), 0), len(table) - 1)])


def apple_tree_travel(t):
    """Where the Apple Tree action has taken him by a time, in units: off to the left, and
    then back to the right and on past where he started. The clip itself keeps him in the
    middle of the picture, running on the spot, and the app moves him by this much."""
    return at_time(_HE, min(t, CATCH + 0.5))


def the_tree(t):
    """The tree at a time, as tree_parts wants it; None while there is none."""
    if t < SHOOT or t >= POOF + 0.22:
        return None
    rise = 0.05 * ease(t, SHOOT, SHOOT + 0.08) + 0.95 * ease(t, 1.12, BURST)       # a shoot, and then all of it at once
    swinging = ease(t, 3.30, 3.70) * (1 - ease(t, 3.78, 3.96))
    # It whips about as it shoots up, shivers while the apple swings and springs back when the apple lets go.
    sway = (3.6 * ring(t - 1.50, 2.1, 2.8) + 0.8 * swinging * math.sin(2 * math.pi * (t - 3.30) / 0.32)
            - 2.0 * ring(t - SNAP, 3.0, 5.0))
    tall = 1 + 0.02 * ring(t - 1.74, 3.0, 6.0)
    size = ease(t, SHOOT, SHOOT + 0.07) * (1 - ease(t, POOF + 0.06, POOF + 0.22))
    if size < 0.04:
        return None
    return round(rise, 3), round(min(max(t - BURST, 0.0), 1.4), 2), round(sway, 2), round(tall, 3), round(size, 3)


def apple_swing(t):
    """Degrees the apple hangs off straight down: a lazy sway, then swinging wider and
    wider, then dead still for a moment before it drops."""
    swinging = ease(t, 3.30, 3.70) * (1 - ease(t, 3.78, 3.96))
    return (2.5 * math.sin(2 * math.pi * t / 1.1) * (1 - ease(t, 3.6, 3.96))
            + 25 * swinging * math.sin(2 * math.pi * (t - 3.30) / 0.32))


# Where the apple drops from, and when it hits the floor: once from the tree and twice more
# as it bounces, each with the speed it leaves the floor at.
_HANG = tree_parts(*the_tree(SNAP - 0.002))["hang"]
_DROP = (_HANG[0], _HANG[1] + STALK_LONG + 5.0 + APPLE_R)
LANDS = [(SNAP + math.sqrt(2 * (-APPLE_R - _DROP[1]) / FALLING), BOUNCE * math.sqrt(2 * (-APPLE_R - _DROP[1]) * FALLING))]
for _ in range(2):
    LANDS.append((LANDS[-1][0] + 2 * LANDS[-1][1] / FALLING, LANDS[-1][1] * BOUNCE))
LAND = LANDS[0][0]
APPLE_RESTS = (_DROP[0] + 4.0, 16.0)       # where the apple comes to rest, between him and the tree, and how far it has turned
# The hops it takes as it bowls along after him: when, how high and how long.
HOPS = [(6.30, 9, 0.18), (RUN_BACK + 0.86, 8, 0.18), (RUN_BACK + 1.46, 12, 0.20), (RUN_BACK + 2.04, 16, 0.22),
        (RUN_BACK + 2.60, 20, 0.24), (RUN_BACK + 3.14, 24, 0.26)]


def apple_beside(t):
    """How far to his right the apple is while it is rolling: less than nothing is to his left."""
    return APPLE_RESTS[0] + at_time(_IT, t) - at_time(_HE, t)


def the_apple(t):
    """The apple at a time, as apple_parts wants it; None before there is one, and from
    when it lands in his mouth, where apple_tree puts it itself."""
    if t < 2.55 or t >= CATCH:
        return None
    floor = -APPLE_R
    if t < SNAP:                                              # on the tree, hanging from its stalk
        hx, hy = tree_parts(*the_tree(t))["hang"]
        size = spring(t - 2.55, 2.4, 9.0)
        swing = apple_swing(t)
        long = STALK_LONG + 5.0 * ease(t, 3.96, SNAP) + APPLE_R * size      # the stalk stretches before it gives
        a = math.radians(swing)
        return (round(hx - long * math.sin(a), 1), round(hy + long * math.cos(a), 1), round(swing, 1),
                round(size, 3), 0.0, round(ease(t, 2.85, 3.25), 2))
    if t < RUN_FROM:                                          # dropping, bouncing twice and lying there
        if t < LAND:
            y = _DROP[1] + 0.5 * FALLING * (t - SNAP) ** 2
        else:
            y = floor
            for (at, speed), (until, _) in zip(LANDS, LANDS[1:]):
                if at <= t < until:
                    y = floor - (speed * (t - at) - 0.5 * FALLING * (t - at) ** 2)
        hit = sum(0.26 * (speed / LANDS[0][1]) * math.exp(-(t - at) * 24) for at, speed in LANDS if t >= at)
        settle = ease(t, LAND, LANDS[2][0])
        return (round(_DROP[0] + (APPLE_RESTS[0] - _DROP[0]) * settle, 1), round(min(y, floor), 1),
                round(APPLE_RESTS[1] * settle, 1), 1.0, round(hit, 3), 1.0)
    # Rolling, so it turns by as much as it has moved along the floor; and rocking where it stops.
    spin = APPLE_RESTS[1] + math.degrees(at_time(_IT, t) / APPLE_R) + 7 * ring(t - LEAP - 1.0, 4.5, 6.0)
    if t < BUMP:
        x = apple_beside(t)
        y = floor - sum(high * arc(t, at, long) for at, high, long in HOPS)
        hit = sum(0.16 * math.exp(-(t - at - long) * 26) for at, high, long in HOPS if t >= at + long)
        return round(x, 1), round(y, 1), round(spin % 360, 1), 1.0, round(hit, 3), 1.0
    # Thrown up by a bump, over, and down into his mouth.
    u = (t - BUMP) / (CATCH - BUMP)
    x = apple_beside(BUMP) * (1 - u) ** 1.6
    y = floor + (MOUTH[1] + 3 - floor) * u - 600 * u * (1 - u)
    return round(x, 1), round(y, 1), round((spin - 540 * u) % 360, 1), round(1 - 0.1 * ease(u, 0.7, 1.0), 3), 0.0, 1.0


def twinkle(t, at, x, y, size, long=0.34):
    """A twinkle that comes and goes at a place, or nothing if this is not its moment."""
    on = bump(t, at, 0.07, long - 0.20, 0.13)
    return [("spark", x, y, round(size * on, 1), round(70 * (t - at), 1), 1.0)] if on > 0.08 else []


def puff(t, at, x, y, small, big, long, drift=(0.0, 0.0)):
    """A puff that swells, drifts and fades, or nothing if this is not its moment."""
    age = (t - at) / long
    if not 0 < age < 1:
        return []
    out = 1 - (1 - age) ** 2
    solid = ease(age, 0.0, 0.10) * (1 - ease(age, 0.40, 1.0))
    return [("puff", round(x + drift[0] * out, 1), round(y + drift[1] * out, 1),
             round(small + (big - small) * out, 1), round(solid, 2))] if solid > 0.03 else []


def tree_fx(t):
    """The twinkles and puffs that go with the tree and the apple."""
    fx = []
    if 0.28 < t < SHOOT + 0.02:                                # twinkles out of thin air, spiralling in to one spot
        close = ease(t, 0.30, SHOOT)
        for k in range(7):
            born = 0.30 + 0.035 * k
            on = bump(t, born, 0.08, SHOOT - born - 0.16, 0.08)
            if on > 0.08:
                a = math.radians(51 * k + 250 * (t - 0.30))
                far = 84 * (1 - close) ** 1.3 + 5
                fx.append(("spark", round(TREE_AT + 0.6 * far * math.cos(a), 1), round(-14 - 70 * (1 - close) + 0.8 * far * math.sin(a), 1),
                           round((8.5 + 2.5 * math.sin(11 * t + k)) * on, 1), round(45 * math.sin(3 * t + k), 1), 1.0))
    fx += twinkle(t, SHOOT - 0.03, TREE_AT, -16, 26, 0.30)                          # pop
    fx += puff(t, SHOOT, TREE_AT + 2, -7, 8, 18, 0.36)
    for at, x, y, size in ((BURST + 0.04, 26, -436, 14), (BURST + 0.10, 264, -398, 12), (BURST + 0.16, 140, -506, 11),
                           (BURST + 0.22, 50, -300, 10), (BURST + 0.28, 252, -300, 10)):       # the leaves burst out
        fx += twinkle(t, at, x, y, size)
    fx += twinkle(t, 3.20, _DROP[0] - 16, _DROP[1] - 22, 12, 0.36)                  # ripe
    fx += puff(t, LAND, APPLE_RESTS[0] + 2, -6, 7, 17, 0.34)                        # it hits the floor
    for at, x, y, small, big in ((POOF + 0.10, 86, -396, 34, 58), (POOF + 0.11, 200, -410, 30, 54), (POOF + 0.12, 146, -322, 36, 62),
                                 (POOF + 0.14, 180, -196, 24, 42), (POOF + 0.16, 178, -64, 20, 34)):     # and the tree is gone again
        fx += puff(t, at, x, y, small, big, 0.50, (0, -8))
    for at, x, y, size in ((POOF + 0.16, 34, -350, 12), (POOF + 0.20, 258, -340, 11), (POOF + 0.24, 140, -478, 11),
                           (POOF + 0.28, 216, -236, 10), (POOF + 0.32, 140, -130, 10)):
        fx += twinkle(t, at, x, y, size)
    fx += puff(t, RUN_FROM + 0.05, 56, -8, 9, 21, 0.42, (58, -4))                   # the dust he leaves as he bolts
    fx += puff(t, LEAP, 44, -7, 8, 18, 0.36, (40, -3))                              # as he jumps
    fx += puff(t, LEAP + LEAP_LONG, 0, -6, 10, 23, 0.36, (0, -2))                   # as he comes down
    fx += puff(t, RUN_BACK + 0.05, -56, -8, 9, 21, 0.42, (-58, -4))                 # as he bolts the other way
    fx += puff(t, BUMP, apple_beside(BUMP) - 4, -6, 7, 16, 0.30, (-26, -2))         # where the apple hits the bump
    fx += twinkle(t, BUMP - 0.02, apple_beside(BUMP) + 8, -30, 13, 0.28)
    fx += twinkle(t, CATCH - 0.02, 30, MOUTH[1] - 36, 15, 0.32)                     # pop, into his mouth
    fx += puff(t, CATCH + 0.16, 60, -7, 8, 20, 0.40, (24, -3))                      # and the dust he kicks up as he pulls up
    return tuple(fx)


def apple_tree(t):
    """An apple tree comes up out of thin air beside him: twinkles gather, a shoot pops out
    of the ground, and all at once it is a tree, taller than he is, with its leaves bursting
    out over his head. He ducks, and gawps up at it. An apple swells on it and ripens,
    which he likes the look of, and reaches for; it swings on its stalk, hangs still, and
    drops in front of him to bounce at his feet. He jumps out of his skin, the tree goes back
    where it came from, and he bolts the other way with his arms in the air.

    The apple rolls after him. He looks back and it is a long way behind; looks back again
    and it is at his heels. He jumps for his life, and it bowls on underneath him and comes
    to a stop. He watches it. It rocks, and starts back towards him, so he bolts the way he
    came, and it bounds after him in bigger and bigger hops, until it hits something, sails
    over his shoulder and lands in his open mouth. He skids to a stop with it stuck there,
    blinks, and swallows it.

    The running is done on the spot. apple_tree_travel says how far he has really gone, and
    the app moves him by that."""
    way = -1 if t < RUN_BACK else 1                           # which way he is running: -1 is to the left
    run = abs(his_speed(t)) / RUN_SPEED                       # how fast, from 0 to 1
    pace = run ** 0.6                                         # his legs stay busy as he slows
    step = 2 * math.pi * at_time(_STRIDES, t)
    side = math.sin(step)
    left, right = max(0.0, side) * pace, max(0.0, -side) * pace          # which foot is off the floor

    def mixed(value, towards, by):
        return value + (towards - value) * by

    # ---- what he is doing, each from 0 to 1
    glance = bump(t, 0.42, 0.16, 0.24, 0.12)                  # at the twinkles by his foot
    jolt = bump(t, SHOOT, 0.05, 0.10, 0.20)                   # the shoot pops out
    gawp = ease(t, 1.14, 1.50) * (1 - ease(t, 2.75, 3.00))    # watching the tree go up, and up
    flinch = bump(t, BURST, 0.07, 0.05, 0.30)                 # the leaves burst out over his head
    fruit = ease(t, 2.75, 3.00) * (1 - ease(t, SNAP, SNAP + 0.05))       # looking at the apple on the tree
    want = ease(t, 2.95, 3.25) * (1 - ease(t, 3.80, 3.94))    # it is ripe, and he likes the look of it
    hush = ease(t, 3.82, 3.96) * (1 - ease(t, SNAP, SNAP + 0.06))        # it has stopped swinging
    fell = ease(t, SNAP, LAND)                                # his eyes go down with it
    air = min(max((t - LAND - 0.07) / 0.40, 0.0), 1.0)        # he jumps out of his skin
    down = LAND + 0.47                                        # and comes down
    scare = ease(t, LAND + 0.05, LAND + 0.13) * (1 - ease(t, down + 0.02, down + 0.12))
    tremble = ease(t, down, down + 0.08) * (1 - ease(t, RUN_FROM - 0.22, RUN_FROM - 0.16))
    antic = bump(t, RUN_FROM - 0.20, 0.11, 0.04, 0.07)        # winds up, leaning away from the way he will go
    antic2 = bump(t, RUN_BACK - 0.17, 0.10, 0.03, 0.06)
    flee = ease(t, RUN_FROM - 0.04, RUN_FROM + 0.10) * (1 - ease(t, LEAP - 0.06, LEAP + 0.04))
    flee2 = ease(t, RUN_BACK - 0.04, RUN_BACK + 0.10) * (1 - ease(t, CATCH, CATCH + 0.06))
    fleeing = flee + flee2
    back = (bump(t, 6.38, 0.10, 0.40, 0.12) + bump(t, LEAP - 0.36, 0.08, 0.24, 0.08)   # looking back at it
            + bump(t, RUN_BACK + 1.10, 0.10, 0.40, 0.12) + bump(t, RUN_BACK + 2.20, 0.10, 0.34, 0.10)
            + bump(t, RUN_BACK + 3.04, 0.10, 0.28, 0.10) + (ease(t, CATCH - 0.38, CATCH - 0.26) if CATCH - 0.38 <= t < CATCH else 0.0))
    back = min(back, 1.0)
    air3 = min(max((t - LEAP) / LEAP_LONG, 0.0), 1.0)         # the jump the apple goes under
    leap = ease(t, LEAP - 0.04, LEAP + 0.06) * (1 - ease(t, LEAP + LEAP_LONG - 0.04, LEAP + LEAP_LONG + 0.06))
    phew = ease(t, LEAP + LEAP_LONG + 0.06, LEAP + LEAP_LONG + 0.24) * (1 - ease(t, TURN + 0.04, TURN + 0.10))
    breath = 0.5 - 0.5 * math.cos(2 * math.pi * (t - LEAP - LEAP_LONG) / 0.36)
    take = bump(t, TURN + 0.05, 0.05, 0.07, 0.08)             # it is coming back
    caught = ease(t, CATCH, CATCH + 0.05) if t < GULP else 0.0            # it is in his mouth
    braking = bump(t, CATCH + 0.02, 0.12, 0.22, 0.26)
    gulp = bump(t, GULP, 0.04, 0.10, 0.16)
    shut = (1 - ease(t, GULP + 0.28, GULP + 0.46)) if t >= GULP else 0.0
    up, up3 = math.sin(math.pi * air), math.sin(math.pi * air3)

    # ---- his eyes
    if t < SHOOT:
        eyes = blink(t, 0.14) or OPEN
    elif t < 1.14:
        eyes = WIDE
    elif t < 2.95:
        eyes = blink(t, 2.44) or OPEN
    elif t < 3.82:
        eyes = HAPPY
    elif t < LAND:
        eyes = OPEN
    elif t < LEAP + LEAP_LONG + 0.08:
        eyes = OPEN if 6.96 <= t < LEAP - 0.36 else WIDE      # for a moment he thinks he has lost it
    elif t < TURN + 0.05:
        eyes = blink(t, LEAP + 0.96) or (0.3, 0.3)
    elif t < GULP:
        eyes = blink(t, CATCH + 0.62) or WIDE
    elif t < GULP + 0.26:
        eyes = CLOSED
    else:
        eyes = blink(t, GULP + 0.44) or OPEN

    # ---- where he is looking: right and down
    look = (9 * glance, 5 * glance)
    look = (mixed(look[0], 9, gawp), mixed(look[1], -9, gawp))
    look = (mixed(look[0], 10, fruit), mixed(look[1], -3, fruit))
    if SNAP <= t < RUN_FROM:
        watching = 1 - ease(t, RUN_FROM - 0.15, RUN_FROM)
        look = (10 * watching, (-3 + 12 * fell) * watching)
    ahead = ease(t, RUN_FROM - 0.12, RUN_FROM + 0.08) * (1 - ease(t, LEAP - 0.05, LEAP + 0.05))
    look = (mixed(look[0], -9, ahead), look[1])
    look = (mixed(look[0], min(max(apple_beside(t) / 10, -10), 10), leap), mixed(look[1], 9, leap))     # down at it as it goes under him
    eyeing = ease(t, LEAP + LEAP_LONG - 0.06, LEAP + LEAP_LONG + 0.06) * (1 - ease(t, RUN_BACK - 0.06, RUN_BACK + 0.08))
    look = (mixed(look[0], -10, eyeing), mixed(look[1], 6, eyeing))
    ahead2 = ease(t, RUN_BACK - 0.02, RUN_BACK + 0.14) * (1 - ease(t, CATCH, CATCH + 0.10))
    look = (mixed(look[0], 9, ahead2), mixed(look[1], 0, ahead2))
    look = (mixed(look[0], -10 * way, back), mixed(look[1], 3, back))
    look = (look[0], mixed(look[1], 3, caught))

    # ---- his mouth
    mouth = 1.0 + 0.10 * jolt
    mouth = mixed(mouth, 0.74, max(gawp, fruit * (1 - want)))                       # "ooh"
    mouth = mixed(mouth, 1.20, want)
    mouth = mixed(mouth, 0.86, hush)
    mouth = mixed(mouth, 0.80, fell * (1 - ease(t, LAND, LAND + 0.06)) if t >= SNAP else 0.0)
    mouth = mixed(mouth, 1.34, scare)
    mouth = mixed(mouth, 0.44 + (0.16 if int(t / 0.04) % 2 else -0.12), tremble)   # teeth chattering
    lost_it = bump(t, 6.96, 0.12, LEAP - 0.36 - 7.08, 0.06)
    mouth = mixed(mouth, 1.30 + 0.05 * math.sin(2 * step) + 0.05 * back - 0.26 * lost_it, fleeing)
    mouth = mixed(mouth, 1.36, leap)
    mouth = mixed(mouth, 0.92 + 0.16 * breath, phew)                                # puffing
    mouth = mixed(mouth, 1.30, take)
    mouth = mixed(mouth, 0.90, caught)                                              # his teeth close on it
    mouth = mixed(mouth, 0.02, shut)

    # ---- his body
    landed, landed3 = max(0.0, t - down), max(0.0, t - LEAP - LEAP_LONG)
    squash = (-0.03 * jolt + 0.07 * flinch + 0.018 * want * math.sin(2 * math.pi * (t - 3.1) / 0.36)
              - 0.05 * up + (0.10 * math.exp(-landed * 9) * math.cos(landed * 16) if t >= down else 0.0) * (1 - flee)
              + 0.09 * antic + 0.08 * antic2
              - 0.06 * (bump(t, RUN_FROM, 0.07, 0.04, 0.18) + bump(t, RUN_BACK, 0.07, 0.04, 0.18))
              + (0.022 * math.cos(step) ** 2 - 0.02) * pace
              - 0.07 * up3 + (0.13 * math.exp(-landed3 * 9) * math.cos(landed3 * 16) if t >= LEAP + LEAP_LONG else 0.0) * (1 - flee2)
              + 0.035 * breath * phew - 0.03 * take
              + (0.06 * math.exp(-(t - CATCH) * 12) if t >= CATCH else 0.0)
              + (0.08 * math.exp(-(t - GULP) * 9) * math.cos((t - GULP) * 14) if t >= GULP else 0.0) + 0.03 * gulp)
    dy = (-9 * arc(t, SHOOT, 0.2) - 34 * 4 * air * (1 - air) - 9 * abs(side) * pace
          - 92 * 4 * air3 * (1 - air3) - 9 * arc(t, TURN + 0.05, 0.16))
    shied = ease(t, LAND + 0.07, down) * (1 - ease(t, RUN_FROM - 0.20, RUN_FROM))  # he comes down a little further off
    shake = (1.3 if int(t / 0.05) % 2 else -1.3) * tremble
    dx = -4 * jolt - 5 * flinch - 4 * shied + shake + 6 * antic - 6 * antic2 + 2.2 * side * pace
    lean = (-2.0 * jolt - 3.5 * flinch - 2.0 * max(gawp, fruit) * (1 - want) + 1.6 * want - 3.0 * tremble
            + 4.5 * antic - 4.5 * antic2 + way * 5.5 * run ** 0.5 + 2.4 * side * pace
            - 2.5 * eyeing * (1 - take) - 4.0 * braking)

    # ---- his arms: how far each is lifted, and curled
    arms, bend = (24 + 18 * jolt + 10 * gawp, 24 + 18 * jolt + 10 * gawp), (-14.0, -14.0)
    bob = 7 * math.sin(2 * math.pi * (t - 3.1) / 0.36)

    def to(lift, curl, by):
        nonlocal arms, bend
        arms = tuple(mixed(a, b, by) for a, b in zip(arms, lift))
        bend = tuple(mixed(a, b, by) for a, b in zip(bend, curl))

    # Running, the arm in front is flung up and the one behind flails.
    leading, trailing = (150 + 10 * math.sin(step + 1.0), 30), (106 + 24 * math.sin(step), 26 + 10 * math.cos(step))
    to((48 + bob, 128 - bob), (0, 16), want)                  # reaching up for it
    to((42, 58), (-6, 6), hush)
    to((40, 40), (-10, -10), fell if SNAP <= t < LAND + 0.1 else 0.0)
    to((138, 138), (34, 34), scare)
    to((50, 50), (-44, -44), tremble)
    to((36, 36), (-30, -30), antic + antic2)
    to((leading[0], trailing[0]), (leading[1], trailing[1]), flee)
    to((142, 142), (30, 30), leap)
    to((16, 16), (-20, -20), phew)
    to((64, 64), (0, 0), take)
    to((trailing[0], leading[0]), (trailing[1], leading[1]), flee2)
    to((58, 58), (6, 6), caught)
    to((34, 34), (-8, -8), shut)

    hop = 9 * up + 9 * arc(t, TURN + 0.05, 0.16)
    tuck = 20 * up3                                           # his feet come up out of the apple's way
    pose = dict(eyes=eyes, look=(round(look[0], 1), round(look[1], 1)), mouth=round(mouth, 2),
                squash=round(squash, 4), dy=round(dy, 1), dx=round(dx, 1), lean=round(lean, 2),
                arms=(round(arms[0], 1), round(arms[1], 1)), bend=(round(bend[0], 1), round(bend[1], 1)),
                legs=((round(7 * left + hop + 0.5 * tuck, 1), round(23 * left ** 0.8 + 0.6 * hop + tuck, 1)),
                      (round(7 * right + hop + 0.5 * tuck, 1), round(23 * right ** 0.8 + 0.6 * hop + tuck, 1))),
                tree=the_tree(t), apple=the_apple(t), fx=tree_fx(t))
    if CATCH <= t < GULP:
        # The apple is in his mouth, and goes where his mouth goes.
        face = whole({**DEFAULT, **pose}) @ shift(*pose["look"])
        x, y = move(face, [(MOUTH[0], MOUTH[1] + 6 * (pose["mouth"] - 1))])[0]
        pose["apple"] = (round(float(x), 1), round(float(y), 1), 24.0, 0.9, 0.0, 1.0)
    return pose


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
    "action_apple_tree": ("action_apple_tree.webp", "Apple Tree", apple_tree, 15.4, 25, True),
    "drag": ("drag.webp", None, carried, 0.40, 25, False),
    "fall": ("fall.webp", None, falling, 0.24, 25, False),
}

# Clips that need a bigger canvas than the rest, as its left, top, right and bottom. The
# app's window for a mate reaches a height either side of his feet and 1.8 heights above
# them (300 and 540 units), and nothing that goes further than that will be seen.
ROOM = {"action_apple_tree": (-240, -530, 300, 20)}

# Clips to save with other settings than the rest of a pack, where the pack is not saved
# exactly: a long clip of a big picture is a lot of megabytes otherwise.
SAVE = {"action_apple_tree": dict(quality=80)}

# Actions that take him somewhere: how far he has got at a time, in units, and when he sets
# off and arrives. It goes into character.json, and the app moves him by it.
TRAVEL = {"action_apple_tree": (apple_tree_travel, RUN_FROM, CATCH + 0.52)}


def build(key, painter=Flat):
    """Renders one clip: its frames cropped to what they use, their timings, and where the
    feet are in the cropped frames."""
    _, _, clip, seconds, fps, calm = CLIPS[key]
    timeline = animate(clip, seconds, fps, calm, loop=not key.startswith("action"))
    usual = set_canvas(*ROOM[key]) if key in ROOM else None
    try:
        images = [render(pose, painter) for pose, _ in timeline]
        used = np.max([im[..., 3] for im in images], axis=0) > 0
        ys, xs = np.nonzero(used.any(axis=1))[0], np.nonzero(used.any(axis=0))[0]
        assert xs[0] > 0 and ys[0] > 0 and xs[-1] < W - 1 and ys[-1] < H - 1, f"{key} runs off the canvas"
        x0, y0, x1, y1 = max(xs[0] - 2, 0), max(ys[0] - 2, 0), xs[-1] + 3, ys[-1] + 3
        anchor = [round(float(-X0 * OUT - x0), 1), round(float(-Y0 * OUT - y0), 1)]
        return [Image.fromarray(im[y0:y1, x0:x1], "RGBA") for im in images], [ms for _, ms in timeline], anchor
    finally:
        if usual:
            set_canvas(*usual)


def build_pack(pack, name, painter=Flat, sheet=None, **webp):
    """Builds every clip and character.json into a pack folder, drawn by a painter. `webp`
    is how the animations are saved; `sheet` is where to put every frame on one page."""
    manifest = {"name": name, "height": 150, "facing": "right", "removeBackground": False, "clips": {}}
    standing = render({}, painter)[..., 3].any(axis=1).sum()   # how tall the mate is standing still, in saved pixels
    rows, pixels, travels = [], 0, {}
    for key, (file, title, *_) in CLIPS.items():
        images, durations, anchor = build(key, painter)
        if len(images) == 1:
            file = file.rsplit(".", 1)[0] + ".png"
            images[0].save(pack / file, optimize=True)
        else:
            how = {**webp, **SAVE.get(key, {})} if webp.get("lossless") is False else webp
            images[0].save(pack / file, save_all=True, append_images=images[1:], duration=durations, loop=0, **how)
        manifest["clips"][key] = {"file": file, "anchor": anchor, **({"name": title} if title else {})}
        if key == "idle":
            # The app makes the idle clip, at its tallest, `height` pixels high. Should idle
            # ever reach above his head, that would shrink him, so allow for it.
            manifest["height"] = round(150 * (images[0].height - 4) / standing)
        if key in TRAVEL:
            # Where the action takes him, for the app: [seconds, how far], every 25th of a
            # second while he is on the move. The app measures in heights of the mate, of
            # which he is one standing, and takes positive to be to the right.
            far, start, end = TRAVEL[key]
            a_height = -TOP * manifest["height"] / 150
            travels[key] = [[round(start + i / 25, 2), round(far(start + i / 25) / a_height, 4)]
                            for i in range(int(round((end - start) * 25)) + 1)]
            manifest["clips"][key]["travel"] = f"@travel {key}@"
        rows.append(images)
        if not key.startswith("action"):                       # the app reads an action as it shows it, and keeps none of it
            pixels += len(images) * images[0].width * images[0].height
        print(f"{file}: {len(images)} frames of {images[0].width}x{images[0].height}, {sum(durations) / 1000:.2f}s, "
              f"{(pack / file).stat().st_size // 1024} KB")
    print(f"all clips: {sum(len(r) for r in rows)} frames; the ones the app unpacks, which are all but the actions, "
          f"take {pixels * 4 / 2 ** 20:.0f} MB between them")

    text = json.dumps(manifest, indent=2)
    for key, pairs in travels.items():                         # a long list, so several pairs to a line
        lines = [", ".join(json.dumps(pair) for pair in pairs[i:i + 6]) for i in range(0, len(pairs), 6)]
        text = text.replace(f'"@travel {key}@"', "[\n" + ",\n".join(" " * 8 + line for line in lines) + "\n      ]")
    (pack / "character.json").write_text(text + "\n")
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
