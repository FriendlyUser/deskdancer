#!/usr/bin/env python3
"""Draws Piplup and builds every animation in the pack.

    python3 make_frames.py            # writes the clips and character.json into the pack
    python3 make_frames.py --sheet    # also saves sheet.png, every frame on one page
    python3 make_frames.py walk drag  # rebuilds only the clips named

No picture is read here. Piplup is drawn by this script. Its measurements below were
taken from one picture of it, so that Piplup standing still, as drawn here, lies on top of
that picture. It is painted the way it looks as a soft toy lit in 3D, after pictures of
Piplup drawn that way: no line round anything, each part one smooth colour that goes
darker and cooler where it turns away from the light, a band of pale light along the top
of the head, and soft shadows where one part lies over another.

The head and the body are two balls. Everything painted on them, the white face, the
crown between the eyes, the eyes themselves, the cape and the two white buttons, is laid
out in degrees round the ball, as places are on a globe, and the ball is turned before it
is drawn. So Piplup can look about, nod, and turn right round on the spot, and what is
painted on it slides round the ball and goes out of sight behind it as it should. The
beak, the flippers, the tail and the feet stick out of the balls and turn with them. Each
pixel of a ball is lit by which way the ball faces there; the flat parts are rounded off
at their edges like cushions, and lit the same way.

Each clip is a small function of time that returns a pose. The flippers are not posed by
hand beyond that: a spring carries them, pushed about by how the shoulders move, so they
lag behind a hop and flap when Piplup lands.

Needs numpy and pillow. This folder starts with "_", so the app does not load anything
from it.
"""
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw

HERE = Path(__file__).resolve().parent
PACK = HERE.parent

# ---------------------------------------------------------------- sizes
# Positions are in units. x = 0 is between Piplup's feet and y = 0 is the floor, with y
# growing downwards as it does on screen. Standing, Piplup is about 300 units tall.

# Both of these can be set from outside for a quick look at a change, which is rougher but
# several times faster: PIPLUP_SS=2 python3 make_frames.py walk. Build without it to keep.
OUT = float(os.environ.get("PIPLUP_OUT", 1.1))            # saved pixels per unit
SS = int(os.environ.get("PIPLUP_SS", 4))                  # drawn this many times larger and averaged down, for smooth edges
X0, Y0, X1, Y1 = -280, -430, 280, 40     # the canvas: room to hop, spin, lie down and blow bubbles
W, H = round((X1 - X0) * OUT), round((Y1 - Y0) * OUT)

# The two balls. Neither is quite round. The head is wider than it is tall; the body is a
# little taller than it is wide, and its top is hidden behind the head. Both are fuller
# below the middle than a true oval, which is what gives them their weight: the pair of
# numbers says how square each is, above the middle and below it (2 is a plain oval, and
# larger is squarer).
HEAD_RX, HEAD_RY, HEAD_SQUARE = 93.0, 81.7, (1.97, 2.56)
BODY_RX, BODY_RY, BODY_SQUARE = 64.7, 70.8, (2.6, 2.7)
BODY_X, BODY_Y = 2.0, -91.0              # the middle of the body: a little ahead of the feet, and above the floor
HEAD_AT = (-4.3, -119.3)                 # the middle of the head, from the middle of the body, whose top it hides
SEAT = 14.0                              # how far the body comes down to sit

# Which way it faces standing still, in degrees: 0 is straight at us, 90 is side on,
# facing right. The head is turned a little less than the body and tipped to one side.
YAW = 26.0
HEAD_YAW = 21.0
HEAD_TILT = -10.8                        # the face is tipped; the shape of the head is not
BODY_ABOVE = 15.7                        # we look down a little on its chest, so what is on the far side of it sits higher

# Seen three-quarters on, as it stands, some parts are drawn a little further round than
# they really are, so that they show: the shoulders and the feet are turned out to the
# side, the tail peeps out from behind, and the eyes sit a little to the near side of the
# beak. Each of these is so many degrees at its most, which is half way between facing us
# and side on, and nothing when it faces us squarely or stands side on, so that it is the
# same seen from either side.
SHOULDER_ROUND, FEET_ROUND, TAIL_ROUND, EYE_ROUND = 14.4, 22.4, 65.8, -4.0

# The face. Places on a ball are (degrees round from the front, degrees down from the
# middle), and sizes are degrees too.
FACE = ((56.3, 24.3, 38.5, 55.0),        # the white round the right eye; the left is its mirror image
        (0.0, 64.2, 50.0, 40.8))         # and the white chin that joins the two
CROWN = ((-26.9, -13.7), (-10.1, -3.8), (4.0, -17.2), (14.7, -3.7), (25.2, -10.9))    # the top of the pale blue crown
EYE = (39.4, 15.2)
EYE_A, EYE_B = 8.3, 18.5                 # half as wide, half as tall
EYE_LEAN = 7.6                           # the eyes stand nearly upright in the tipped face, and so does the beak
EYE_FAR = 0.36                           # how much shorter the eye further from us is drawn
SHUT_WIDE, SHUT_THIN = 5.0, 3.1          # the dark line an eye makes shut, in units: across its middle, and at its ends
SMILE = (11.0, 8.5, -4.0, 100.0)         # an eye shut in a smile is an arch: half as wide and as high as it is, where its
                                         # top is from the middle of the eye, and how far round its legs run, in degrees
BEAK = (0.0, 26.9)
BEAK_POINTS = 10.5                       # degrees down from level that it points
BEAK_W, BEAK_H, BEAK_OUT = 0.226, 0.258, 0.258  # in head radii: half as wide, half as tall, how far it sticks out
BEAK_JAW = 1.15                          # how much deeper the lower half is than the dome it is cut from
BEAK_GAPE = 38.0                         # degrees the lower half drops when the beak is wide open

# The body.
BUTTON = (29.7, -1.3)
BUTTON_A, BUTTON_B = 13.8, 14.8
GROOVE = 1.5                             # how wide the groove round each button is, in units
# The hem of the cape, all the way round: two scallops on the chest with a notch between
# them, up over each shoulder, and well down its back, above the tail. The notch is
# at CAPE_NOTCH, and each scallop is CAPE_DROP deep below it and CAPE_LOBE to either side
# of its lowest point; after them, the hem is at these (degrees round, degrees down).
CAPE_NOTCH, CAPE_DROP, CAPE_LOBE = -36.5, 17.2, 24.6
CAPE_HEM = ((40, -17.5), (55, -20), (70, -25), (92, -44), (104, -40), (116, -20), (130, 0), (145, 14), (162, 23), (180, 26))
SHOULDER = (88.85, -38.8)                # high up, under the head
FLIPPER, FLIPPER_W = 98.0, 33.4          # shoulder to tip, and across at the widest
FLIPPER_NEAR = 0.26                      # how much longer the one nearer to us is drawn
FLIPPER_WIDER, FLIPPER_NARROWER = 0.23, 0.29      # how much wider it is, and how much narrower the further one
TAIL = (180.0, -3.5)
HIP, HIP_BACK = 43.1, 25.4               # the feet: either side of the middle, and behind it
THIGH = (11.5, 39.5, 1.0)                # the top of a leg, a round lump low on the body over each foot: how big it is,
                                         # how far above the floor, and how far out from the hip
SPLAY = 42.8                             # how far each foot turns out
FOOT_LONG, FOOT_HEEL, FOOT_HALF = 44.5, 5.8, 14.4     # a foot: heel to toe, half across the heel, and half across the toes
FOOT_FAN = 0.61                          # how far along it is at its widest: from there on, its front is round
FOOT_HIGH, FOOT_THIN, ANKLE = 12.2, 3.0, 6.0          # how thick it is over the heel and at the toes, and the ankle above that
FOOT_TOES = 0.42                         # where the lines between its three toes run, as a share of half its width
FOOT_SEEN = 0.34                         # how much of the top of a foot we see: we look down on them a little

# ---------------------------------------------------------------- colours
# Piplup is painted as a soft toy looks lit in 3D: no line round anything, each part one
# smooth colour that goes darker and cooler where it turns away from the light, a band of
# pale light along the top of the head, and a soft shadow wherever one part lies over
# another. Each colour is a pair, 0..1: what it is where the light falls full on it, and
# what it goes where it turns away. They were taken from pictures of Piplup drawn that
# way, in the cool light of an evening, and lightened a little.

def rgb(r, g, b):
    return np.array([r, g, b], np.float32) / 255


BLUE = (rgb(6, 80, 224), rgb(0, 54, 182))            # the head, the cape, the tail and the backs of the flippers
WHITE = (rgb(214, 210, 244), rgb(152, 152, 208))     # the face and the buttons, with a little lavender in the white
PALE = (rgb(120, 178, 236), rgb(82, 130, 206))       # the crown between the eyes
BODY = (rgb(112, 178, 244), rgb(76, 126, 202))
FIN = (rgb(128, 192, 250), rgb(86, 140, 214))        # the fronts of the flippers, a little lighter than the body
ORANGE = (rgb(236, 178, 86), rgb(182, 118, 72))      # the beak and the feet
UNDER = (rgb(218, 156, 78), rgb(166, 102, 68))       # the lower half of the beak
RING = (rgb(84, 116, 166), rgb(62, 88, 140))         # the groove round each button
EYE_DARK = rgb(10, 10, 38)                           # the eyes, and the lines they make shut
EYE_LOW = rgb(46, 74, 160)                           # the light caught low down in an open eye
PUPIL = rgb(2, 2, 16)
SHINE = rgb(255, 255, 255)
MOUTH = (rgb(128, 40, 66), rgb(92, 26, 54))
TONGUE = (rgb(238, 122, 148), rgb(188, 86, 122))
HOLLOW = (0.60, 0.64, 0.80)                          # what is left of the light in a crease, or under something
SHEEN = (0.58, 0.48, 0.78)                           # the band of pale light along the top, laid over a colour as a screen
BUBBLE = rgb(156, 214, 252)
DROP_EDGE = rgb(70, 140, 222)
SPARK = rgb(252, 204, 18)
SPARK_LIGHT = rgb(255, 236, 112)
DASH = rgb(168, 212, 248)

# The light comes from up, to the left and in front. The sheen lies along the top of a
# part, a little towards the light, from where the surface has turned SHEEN_FROM of the
# way from facing us to facing up, and it has a sharp edge, SHEEN_SOFT wide.
LIGHT = tuple(float(v) for v in np.array([-0.45, -0.62, 0.64]) / np.linalg.norm([-0.45, -0.62, 0.64]))
UP = tuple(float(v) for v in np.array([-0.20, -0.98]) / np.hypot(-0.20, -0.98))
SHEEN_FROM, SHEEN_SOFT = 0.43, 0.05

ROOM = 12.0                              # room left round each part as it is drawn, in units, for its soft edges and shadows


# ---------------------------------------------------------------- shapes
# A shape is a closed run of points, close enough together to pass for a curve.

CIRCLE = np.stack([np.cos(np.linspace(0, 2 * math.pi, 96, endpoint=False)),
                   np.sin(np.linspace(0, 2 * math.pi, 96, endpoint=False))], 1)


def oval(cx, cy, rx, ry=None, tilt=0.0):
    return (CIRCLE[::2] * (rx, rx if ry is None else ry)) @ turn(tilt).T + (cx, cy)


def turn(degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return np.array([[c, -s], [s, c]])


def squarer(points, above, below):
    """Points on a round disc, pushed out towards its corners: 2 leaves it round, and
    more makes it squarer, by `above` over the top half and `below` under it."""
    p = np.asarray(points, float)
    r = np.maximum(np.hypot(p[:, 0], p[:, 1]), 1e-9)
    c, s = np.abs(p[:, 0]) / r, np.abs(p[:, 1]) / r
    t = np.clip((p[:, 1] / r + 0.4) / 0.8, 0.0, 1.0)
    n = above + (below - above) * t * t * (3 - 2 * t)
    return p * ((c ** n + s ** n) ** (-1.0 / n))[:, None]


def hull(points):
    """The shape a rubber band would make round these points."""
    pts = sorted(set(map(tuple, np.round(np.asarray(points, float), 3))))
    if len(pts) < 3:
        return np.array(pts)

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(p)
        return out[:-1]

    return np.array(half(pts) + half(pts[::-1]))


def star(cx, cy, size, angle=0.0, thin=0.22):
    """A four-pointed sparkle."""
    a = np.radians(angle) + np.arange(8) * math.pi / 4
    r = np.where(np.arange(8) % 2 == 0, size, size * thin)
    return np.stack([cx + r * np.cos(a), cy + r * np.sin(a)], 1)


def drop(cx, cy, r, angle=0.0):
    """A drop of water, its point upwards before it is turned."""
    a = np.linspace(0, 2 * math.pi, 40, endpoint=False)
    pts = np.stack([r * np.sin(a) * (1 - 0.45 * (np.cos(a) > 0) * np.cos(a) ** 2), -r * np.cos(a) * (1 + 0.55 * (np.cos(a) > 0))], 1)
    return pts @ turn(angle).T + (cx, cy)


def runs(points, keep, closed=True):
    """The stretches of a line where `keep` holds, each as a line of its own."""
    points, keep = np.asarray(points, float), np.asarray(keep, bool)
    n = len(points)
    if keep.all():
        return [np.concatenate([points, points[:2]])] if closed else [points]
    if not keep.any():
        return []
    start = int(np.argmin(keep)) if closed else 0         # begin where the line is out of sight
    order = [(start + i) % n for i in range(n)] if closed else list(range(n))
    out, run = [], []
    for i in order:
        if keep[i]:
            run.append(points[i])
        else:
            if len(run) > 1:
                out.append(np.array(run))
            run = []
    if len(run) > 1:
        out.append(np.array(run))
    return out


def stretches(keep):
    """Where a row of yeses and noes says yes for two or more in a row, as slices."""
    out, start = [], None
    for i, yes in enumerate(list(np.asarray(keep, bool)) + [False]):
        if yes and start is None:
            start = i
        elif not yes and start is not None:
            if i - start > 1:
                out.append(slice(start, i))
            start = None
    return out


def ribbon(points, widths):
    """A line so wide at each of its points, with round ends, as shapes."""
    p, w = np.asarray(points, float), np.asarray(widths, float)
    d = np.gradient(p, axis=0)
    d /= np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-9)[:, None]
    out = np.stack([-d[:, 1], d[:, 0]], 1) * (w / 2)[:, None]
    return [np.concatenate([p + out, (p - out)[::-1]]), oval(*p[0], w[0] / 2), oval(*p[-1], w[-1] / 2)]


# ---------------------------------------------------------------- balls

def globe(lam, phi):
    """Places on a ball, (degrees round from the front, degrees down), as points in space:
    x to the right, y down, z towards us."""
    lam, phi = np.radians(np.asarray(lam, float)), np.radians(np.asarray(phi, float))
    lam, phi = np.broadcast_arrays(lam, phi)
    return np.stack([np.cos(phi) * np.sin(lam), np.sin(phi), np.cos(phi) * np.cos(lam)], -1)


def spot(lam, phi, a, b, n=48):
    """An oval patch on a ball, as places round its edge."""
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return lam + a * np.cos(t), phi + b * np.sin(t)


def trace(corners, step=3.0, closed=False):
    """Places joined by straight runs, with extra places along each run."""
    corners = np.asarray(corners, float)
    pairs = zip(corners, np.roll(corners, -1, 0)) if closed else zip(corners[:-1], corners[1:])
    out = []
    for a, b in pairs:
        n = max(2, int(np.hypot(*(b - a)) / step))
        out.append(a + (b - a) * np.linspace(0, 1, n, endpoint=False)[:, None])
    if not closed:
        out.append(corners[-1:])
    return np.concatenate(out)


class Ball:
    """A ball that has been turned, and where it sits in the picture."""

    def __init__(self, centre, rx, ry, square, yaw, pitch, roll, whole, tipped=0.0, above=0.0):
        y = math.radians(yaw)
        about_upright = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
        nod = lambda p: np.array([[1, 0, 0], [0, math.cos(math.radians(p)), math.sin(math.radians(p))],
                                  [0, -math.sin(math.radians(p)), math.cos(math.radians(p))]])
        self.plain = about_upright @ nod(pitch)            # nodded, then turned: where its limbs are
        self.turned = nod(above) @ self.plain              # and looked down on: where what is painted on it is
        self.square = square
        self.tipped = turn(tipped)                         # what is on the ball, turned inside its outline
        self.lin = whole[:, :2] @ turn(roll)               # sizes and directions, into the picture
        self.A = self.lin @ np.diag([rx, ry])
        self.c = whole[:, :2] @ np.asarray(centre, float) + whole[:, 2]

    def spin(self, v, limb=False):
        return np.asarray(v, float) @ (self.plain if limb else self.turned).T

    def flat(self, v, wrap=True, limb=False):
        """Points of the ball in the picture, and how far towards us each one is. A point
        round the back is slid out to the ball's edge, so that a patch that is half out
        of sight is cut off by the edge. A limb is not tipped or looked down on, as what is
        painted on the ball is."""
        tip = not limb
        r = self.spin(np.atleast_2d(v), limb)
        xy = r[:, :2].copy()
        if wrap:
            back = r[:, 2] < 0
            xy[back] /= np.maximum(np.hypot(xy[back, 0], xy[back, 1]), 1e-9)[:, None]
        return self.disc(xy, tip), r[:, 2]

    def disc(self, xy, tip=True):
        """Points of the round disc the ball is seen as, in the picture."""
        xy = np.asarray(xy, float)
        return squarer(xy @ self.tipped.T if tip else xy, *self.square) @ self.A.T + self.c

    def outline(self, scale=1.0, shift=(0.0, 0.0)):
        return (squarer(CIRCLE, *self.square) * scale) @ self.A.T + self.c + shift

    def rim(self, start, end, inset, n=28):
        """Part of a line just inside the ball's edge, between two angles (degrees, 0
        pointing right, going round by way of the bottom)."""
        a = np.radians(np.linspace(start, end, n))
        edge = squarer(np.stack([np.cos(a), np.sin(a)], 1), *self.square) @ self.A.T
        return edge * (1 - inset / np.maximum(np.hypot(edge[:, 0], edge[:, 1]), 1e-9))[:, None] + self.c


# ---------------------------------------------------------------- drawing

def both(a, b):
    return ImageChops.multiply(a, b)


def less(a, b):
    return ImageChops.subtract(a, b)


def amount(mask):
    """A stencil as amounts from 0 to 1."""
    return np.asarray(mask, np.float32) * np.float32(1 / 255)


def glide(a):
    """0 below 0, 1 above 1, gliding between, for a whole picture at once."""
    a = np.clip(a, 0.0, 1.0)
    return a * a * (3 - 2 * a)


def blur(a, by):
    """A picture of amounts, smoothed over about `by` pixels: three box blurs each way,
    which is as near a bell curve as makes no difference, with nothing coming in from
    beyond its edges."""
    a = np.asarray(a, np.float32)
    r = int(round((math.sqrt(4 * by * by + 1) - 1) / 2))
    if r < 1:
        return a
    for axis in (0, 1):
        n = a.shape[axis]
        pad = [(r + 1, r) if i == axis else (0, 0) for i in range(2)]
        for _ in range(3):
            total = np.cumsum(np.pad(a, pad), axis=axis, dtype=np.float64)
            if axis == 0:
                a = ((total[2 * r + 1:2 * r + 1 + n] - total[:n]) / (2 * r + 1)).astype(np.float32)
            else:
                a = ((total[:, 2 * r + 1:2 * r + 1 + n] - total[:, :n]) / (2 * r + 1)).astype(np.float32)
    return a


def unit(x, y, z):
    """Directions, each made one long, as one picture of them."""
    k = 1 / np.sqrt(np.maximum(x * x + y * y + z * z, 1e-12))
    return np.stack([x * k, y * k, z * k], -1).astype(np.float32)


def facing(c, centre, A, square=(2.0, 2.0), box=None):
    """Which way the surface of a ball faces at each pixel of a sheet, or of a box on it,
    as directions one long: x to the right, y down and z towards us. The ball is a round
    one squared off as `squarer` squares an outline, then stretched and turned into the
    picture by A, and it is as deep as it is wide."""
    xs, ys = c.grid(box)
    inv = [[float(v) for v in row] for row in np.linalg.inv(A)]
    dx, dy = xs - np.float32(centre[0]), ys - np.float32(centre[1])
    u, v = inv[0][0] * dx + inv[0][1] * dy, inv[1][0] * dx + inv[1][1] * dy
    r = np.maximum(np.hypot(u, v), np.float32(1e-6))
    n = square[0] + (square[1] - square[0]) * glide((v / r + 0.4) / 0.8)
    across = np.maximum(np.abs(u) / r, np.float32(1e-6)) ** n + np.maximum(np.abs(v) / r, np.float32(1e-6)) ** n
    reach = across ** (-1.0 / n)                          # how far out the outline is, this way from the middle
    u, v = u / reach, v / reach
    z = np.sqrt(np.clip(1 - u * u - v * v, 0.0, 1.0))
    deep = math.sqrt(abs(float(np.linalg.det(A))))
    return unit(deep * (inv[0][0] * u + inv[1][0] * v), deep * (inv[0][1] * u + inv[1][1] * v), z)


def puffed(solid, soft, steep=3.0, tip=0.0):
    """Which way the surface faces on a flat part rounded off all round its edge like a
    cushion, over about `soft` pixels: flat in the middle and turning away towards the
    edge, by about `steep` (how far it goes sideways for each step it comes towards us)
    at the very edge. `tip` tips the whole of it back by so many degrees, so that its
    middle faces up more than it faces us."""
    height = blur(solid, soft)
    gy, gx = np.gradient(height)
    k = np.float32(2.5 * steep * soft)
    x, y, z = -k * gx, -k * gy, np.ones_like(height)
    if tip:
        a = math.radians(tip)
        y, z = y * np.float32(math.cos(a)) - z * np.float32(math.sin(a)), y * np.float32(math.sin(a)) + z * np.float32(math.cos(a))
    return unit(x, y, z)


class Coat:
    """What a part is painted with, pixel by pixel: the colour each pixel would be in full
    light, and in shade."""

    def __init__(self, c):
        w, h = c.img.size
        self.lit = np.zeros((h, w, 3), np.float32)
        self.dark = np.zeros((h, w, 3), np.float32)

    def fill(self, mask, colours):
        where = np.asarray(mask) > 127
        self.lit[where], self.dark[where] = colours


def lit(coat, n, hollow=None, sheen=0.0):
    """The colours of a part, as the light falls on it. Each pixel goes from its colour in
    shade to its colour in full light as it turns to the light, and darker still close to
    the outline, more so on the side away from the light. `hollow`, from 0 to 1, is how far
    each pixel is shut away from the light by something lying over it, and `sheen` how
    strongly the band of pale light along the top shows."""
    x, y, z = n[..., 0], n[..., 1], np.clip(n[..., 2], 0.0, 1.0)
    towards = x * LIGHT[0] + y * LIGHT[1] + z * LIGHT[2]
    edge = (1 - z) ** 3
    t = (0.55 + 0.45 * glide((towards + 0.5) / 1.2)) * (1 - 0.85 * edge * (1 - 0.6 * np.clip(towards, 0.0, 1.0)))
    out = coat.dark + (coat.lit - coat.dark) * t[..., None]
    if hollow is not None:
        out *= 1 - (1 - np.array(HOLLOW, np.float32)) * np.clip(hollow, 0.0, 1.0)[..., None]
    if sheen:
        rim = (1 - z) * (0.1 + 0.9 * np.clip(x * UP[0] + y * UP[1], 0.0, 1.0) ** 1.3)
        s = np.float32(sheen) * glide((rim - SHEEN_FROM) / SHEEN_SOFT)
        out = 1 - (1 - out) * (1 - np.array(SHEEN, np.float32) * s[..., None])
    return out


class Canvas:
    """A sheet to draw on. Everything is drawn hard-edged at SS times the saved size and
    averaged down at the end, which is where the smooth edges come from. Parts are cut
    out as stencils first, so that one can be kept inside another, and coloured pixel by
    pixel as the light falls on them."""

    def __init__(self, corner=(0, 0), size=None):
        self.corner = corner                               # of this sheet on the whole one, in drawn pixels
        self.img = Image.new("RGBA", size or (W * SS, H * SS), (0, 0, 0, 0))

    def window(self, points, margin):
        """A smaller sheet covering just these points and a margin, to draw one part on:
        there is far less of it to fill. `onto` lays it back on this one."""
        k = OUT * SS
        lo = np.floor((np.min(points, 0) - margin - (X0, Y0)) * k).astype(int)
        hi = np.ceil((np.max(points, 0) + margin - (X0, Y0)) * k).astype(int)
        lo, hi = np.maximum(lo, 0), np.minimum(hi, (W * SS, H * SS))
        return Canvas((int(lo[0]), int(lo[1])), (max(1, int(hi[0] - lo[0])), max(1, int(hi[1] - lo[1]))))

    def onto(self, sheet):
        sheet.img.alpha_composite(self.img, self.corner)

    def px(self, points):
        return [tuple(p) for p in (np.rint((np.asarray(points, float) - (X0, Y0)) * (OUT * SS)).astype(int) - self.corner).tolist()]

    def grid(self, box=None):
        """Where each pixel of this sheet, or of a box on it, is in units: a row of the x of
        each column and a column of the y of each row."""
        k = OUT * SS
        x0, y0, x1, y1 = box or (0, 0) + self.img.size
        return ((X0 + (self.corner[0] + np.arange(x0, x1, dtype=np.float32)) / k)[None, :],
                (Y0 + (self.corner[1] + np.arange(y0, y1, dtype=np.float32)) / k)[:, None])

    def box(self, points, margin):
        """The pixels of this sheet round some points and a margin, as left, top, right
        and bottom."""
        k = OUT * SS
        lo = np.floor((np.min(points, 0) - margin - (X0, Y0)) * k).astype(int) - self.corner
        hi = np.ceil((np.max(points, 0) + margin - (X0, Y0)) * k).astype(int) - self.corner
        lo, hi = np.maximum(lo, 0), np.minimum(hi, self.img.size)
        return int(lo[0]), int(lo[1]), max(int(hi[0]), int(lo[0]) + 1), max(int(hi[1]), int(lo[1]) + 1)

    def mask(self, shapes):
        """A stencil of these shapes."""
        m = Image.new("L", self.img.size, 0)
        pen = ImageDraw.Draw(m)
        for s in shapes:
            if len(s) >= 3:
                pen.polygon(self.px(s), fill=255)
        return m

    def strokes(self, lines, width):
        """A stencil of these lines, with round ends."""
        m = Image.new("L", self.img.size, 0)
        pen = ImageDraw.Draw(m)
        w = max(1, round(width * OUT * SS))
        for line in lines:
            px = self.px(line)
            pen.line(px, fill=255, width=w, joint="curve")
            for x, y in (px[0], px[-1]):
                pen.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=255)
        return m

    def paint(self, mask, colour):
        """One colour, 0..1, painted through a stencil."""
        self.img.paste(tuple(int(round(float(v) * 255)) for v in colour) + (255,), (0, 0), mask)

    def lay(self, mask, colours, at=(0, 0)):
        """A picture of colours, 0..1, painted through a stencil the same size as it, with
        its top left corner `at` that pixel of this sheet."""
        rgb = Image.fromarray((np.clip(colours, 0.0, 1.0) * 255 + 0.5).astype(np.uint8), "RGB")
        self.img.paste(rgb, at, mask if isinstance(mask, Image.Image) else Image.fromarray(np.asarray(mask, np.uint8), "L"))

    def glaze(self, colours, solid):
        """A picture of colours laid over what is there, each pixel `solid` (0..1) of the way."""
        layer = np.dstack([np.clip(colours, 0.0, 1.0), np.clip(solid, 0.0, 1.0)])
        self.img.alpha_composite(Image.fromarray((layer * 255 + 0.5).astype(np.uint8), "RGBA"))

    def finish(self):
        """The drawing at its saved size."""
        # Averaged with each colour weighted by how solid it is, so that the empty space
        # round the edge does not darken it.
        return np.asarray(self.img.convert("RGBa").reduce(SS).convert("RGBA"))


# ---------------------------------------------------------------- the rig

OPEN, WIDE, HAPPY, CLOSED, SQUINT = ("open", "open"), ("wide", "wide"), ("happy", "happy"), ("closed", "closed"), ("squint", "squint")

REST = (26.0, 24.4)                      # how far the flippers hang out from its sides, standing still

DEFAULT = dict(eyes=OPEN,                # each: "open", "wide", "happy", "closed", "squint", or 0..1 for how far shut
               look=(0.0, 0.0),          # where the pupils are, in degrees right and down
               beak=0.0,                 # 0 shut, 1 wide open
               turn=0.0, nod=0.0, tilt=0.0,       # the head: degrees turned to the right, nodded down, tipped over
               bob=(0.0, 0.0),           # and moved, in units
               yaw=0.0,                  # the whole of it turned round
               twist=0.0,                # the body turned without the head
               sway=0.0,                 # the body rolled to one side, degrees
               puff=0.0,                 # chest out
               flippers=REST,            # degrees each is lifted from hanging down: its right one, the nearer as it stands, then its left
               sweep=(0.0, 0.0),         # and swung forwards
               feet=((0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)),   # right, then left: moved along, lifted, turned out more, toes tipped up
               hips=(0.0, 0.0),          # the body moved over its feet, in units: walking, the feet stay where they are put
               seated=0.0,               # 1 is sat down
               tail=0.0,                 # wagged, degrees
               squash=0.0, lean=0.0, dx=0.0, dy=0.0,
               fx=())

FLOOR = 0.0                              # set below, once a standing foot can be measured


def round_by(most, yaw):
    """One of the liberties taken in a three-quarter view (see the top), at this turn."""
    return most * math.sin(math.radians(2 * yaw))


def whole(pose):
    """Where the whole mate is: squashed, leant about its feet and moved."""
    m = turn(pose["lean"]) @ np.diag([1 + 0.6 * pose["squash"], 1 - pose["squash"]])
    return np.concatenate([m, [[pose["dx"]], [pose["dy"]]]], 1)


class Piplup:
    """A pose worked out: where the two balls are and how they are turned."""

    def __init__(self, pose):
        self.pose = pose = {**DEFAULT, **pose}
        self.whole = whole(pose)
        self.body_yaw = YAW + pose["yaw"] + pose["twist"]
        centre = np.array([BODY_X + pose["hips"][0], BODY_Y + SEAT * pose["seated"] + pose["hips"][1]])
        self.body = Ball(centre, BODY_RX * (1 + 0.09 * pose["puff"]), BODY_RY * (1 + 0.03 * pose["puff"]), BODY_SQUARE,
                         self.body_yaw, 0.0, pose["sway"], self.whole, above=BODY_ABOVE)
        neck = turn(pose["sway"]) @ np.array(HEAD_AT) + pose["bob"] + (0.0, -3.0 * pose["puff"])
        self.head_yaw = HEAD_YAW + pose["yaw"] + pose["turn"]
        self.head = Ball(centre + neck, HEAD_RX, HEAD_RY, HEAD_SQUARE, self.head_yaw, pose["nod"],
                         pose["tilt"] + 0.5 * pose["sway"], self.whole, tipped=HEAD_TILT)
        planted = min(max((abs(pose["lean"]) - 20.0) / 30.0, 0.0), 1.0)     # leaning a little, its feet stay flat on the floor
        self.feet_whole = whole({**pose, "lean": pose["lean"] * planted * planted * (3 - 2 * planted)})
        self.shoulders = round_by(SHOULDER_ROUND, self.body_yaw)
        self.tail_at = TAIL[0] + round_by(TAIL_ROUND, self.body_yaw) + pose["tail"]
        self.eyes_at = round_by(EYE_ROUND, self.head_yaw)


def beak_points(p):
    """The beak, a dome on the front of the head cut in two by the mouth, which slopes
    down towards the tip: the outline of the upper half, of the lower half swung down
    on its hinge as far as the beak is open, of the inside of the mouth and the tongue,
    and a function that places a point given across, down and out from the middle."""
    h = p.head
    gape = math.radians(BEAK_GAPE * p.pose["beak"])
    mid, points = globe(*BEAK), globe(BEAK[0], BEAK_POINTS)
    lam, phi = math.radians(BEAK[0]), math.radians(BEAK[1])
    across = np.array([math.cos(lam), 0.0, -math.sin(lam)])
    down = np.array([-math.sin(phi) * math.sin(lam), math.cos(phi), -math.sin(phi) * math.cos(lam)])

    lean = turn(EYE_LEAN)

    def place(u, v, out):
        u, v, out = np.broadcast_arrays(np.asarray(u, float), np.asarray(v, float), np.asarray(out, float))
        u, v = lean[0, 0] * u + lean[0, 1] * v, lean[1, 0] * u + lean[1, 1] * v
        return h.flat(mid + np.outer(out, points) + np.outer(u, across) + np.outer(v, down), wrap=False)[0]

    a, b = np.meshgrid(np.linspace(0, 2 * math.pi, 64, endpoint=False), np.linspace(0, math.pi / 2, 11))
    a, b = a.ravel(), b.ravel()
    u, v, out = BEAK_W * np.cos(a) * np.cos(b), BEAK_H * np.sin(a) * np.cos(b), BEAK_OUT * np.sin(b)
    hinge, slope = 0.22 * BEAK_H, 0.65 * BEAK_H
    cut = hinge * np.cos(b) + slope * np.sin(b)           # where the mouth is, at each distance out
    # The mouth itself, as a line round the dome from one corner to the other.
    bb = np.linspace(0, math.atan2(BEAK_H - hinge, slope), 16)
    lip_v = hinge * np.cos(bb) + slope * np.sin(bb)
    half = BEAK_W * np.sqrt(np.clip(1 - (lip_v / (BEAK_H * np.cos(bb))) ** 2, 0, 1)) * np.cos(bb)
    lip = (np.concatenate([-half, half[::-1]]), np.concatenate([lip_v, lip_v[::-1]]),
           np.concatenate([BEAK_OUT * np.sin(bb), BEAK_OUT * np.sin(bb)[::-1]]))

    def dropped(u, v, out):
        """The lower half, swung down about the hinge."""
        dv = (v - hinge) * np.where(out < 1e-6, BEAK_JAW, 1.0)
        return u, hinge + dv * math.cos(gape) + out * math.sin(gape) * 0.9, out * math.cos(gape) - dv * math.sin(gape) * 0.3

    upper = hull(np.concatenate([place(u[v <= cut], v[v <= cut], out[v <= cut]), place(*lip)]))
    lower = hull(np.concatenate([place(*dropped(u[v >= cut], v[v >= cut], out[v >= cut])), place(*dropped(*lip))]))
    inside = hull(np.concatenate([place(*lip), place(*dropped(*lip))])) if gape > 0.02 else None
    tongue = hull(place(*dropped(lip[0] * 0.62, lip[1] + 0.02, lip[2] * 0.62))) if gape > 0.02 else None
    return upper, lower, inside, tongue, place


def draw_beak(sheet, p):
    """The beak: a dome in two halves, rounded off at its edges and lit as the head is.
    Shut, the line of the mouth is the soft shadow the upper half throws on the lower;
    open, the inside of the mouth and the tongue show between them, in shadow under the
    upper half."""
    upper, lower, inside, tongue, place = beak_points(p)
    shapes = [upper, lower] + ([inside] if inside is not None else [])
    c = sheet.window(np.concatenate(shapes), ROOM)
    k = OUT * SS
    solid = c.mask(shapes)
    top = c.mask([upper])
    coat = Coat(c)
    coat.fill(solid, UNDER)
    if inside is not None:
        throat = less(c.mask([inside]), top)
        coat.fill(throat, MOUTH)
        coat.fill(both(c.mask([tongue]), throat), TONGUE)
    coat.fill(top, ORANGE)
    upper_half = amount(top)
    hollow = np.clip(2.2 * blur(upper_half, 1.3 * k), 0.0, 1.0) * (1 - upper_half) * 0.5
    size = float(np.max(np.ptp(np.concatenate([upper, lower]), axis=0)))      # across the beak at its widest, in units
    c.lay(solid, lit(coat, puffed(amount(solid), 0.3 * size * k, steep=2.4), hollow, sheen=0.2))
    c.onto(sheet)


def draw_head(sheet, p):
    """The head, lit as a ball: blue, with the pale crown and the white face painted on it
    where they have been turned to, the beak's soft shadow on the face, and the band of
    pale light along its top. Then the eyes, and the beak behind the head or in front."""
    h = p.head
    rim = h.outline()
    beak_towards_us = h.spin(globe(*BEAK))[2] > 0
    if not beak_towards_us:
        draw_beak(sheet, p)
    c = sheet.window(rim, ROOM)
    k = OUT * SS
    inside = c.mask([rim])
    coat = Coat(c)
    coat.fill(inside, BLUE)

    # The crown: a patch of pale blue from the beak up to three points on the forehead.
    edge = trace(list(CROWN) + [(CROWN[-1][0], 48), (CROWN[0][0], 48)], closed=True)
    pts, z = h.flat(globe(edge[:, 0], edge[:, 1]))
    if (z > 0).sum() > 3:
        coat.fill(both(c.mask([pts]), inside), PALE)

    # The white of the face: an oval round each eye and the chin, as one shape.
    shapes = []
    for lam, phi, a, b in [(-FACE[0][0], *FACE[0][1:]), FACE[0], FACE[1]]:
        pts, z = h.flat(globe(*spot(lam, phi, a, b, 96)))
        if (z > 0).sum() >= 4:
            shapes.append(pts)
    if shapes:
        coat.fill(both(c.mask(shapes), inside), WHITE)

    hollow = None
    if beak_towards_us:                                    # the soft shadow the beak throws on the face
        upper, lower, *_ = beak_points(p)
        throw = hull(np.concatenate([upper, lower])) + h.lin @ np.array([4.0, 7.0])
        hollow = 0.55 * blur(amount(c.mask([throw])), 3.5 * k)
    c.lay(inside, lit(coat, facing(c, h.c, h.A, h.square), hollow, sheen=1.0))
    for side, state in zip((-1, 1), p.pose["eyes"]):
        draw_eye(c, p, inside, side, state)
    c.onto(sheet)
    if beak_towards_us:
        draw_beak(sheet, p)


def draw_eye(c, p, inside, side, state):
    """An eye. Open, it is dark and glossy, with the light caught in it low down, a pupil
    that looks about and a white shine. Shut, it is a dark line, thickest in the middle
    and thinner to its round ends: an arch when it smiles, a curve down when it sleeps,
    and > or < when it is screwed up."""
    h = p.head
    lam0, phi0 = side * EYE[0] + p.eyes_at, EYE[1]
    lx, ly = p.pose["look"]

    def upright(lam, phi):
        """Places round the eye, turned about its middle."""
        d = np.stack([np.asarray(lam, float) - lam0, np.asarray(phi, float) - phi0], -1) @ turn(EYE_LEAN).T
        return lam0 + d[..., 0], phi0 + d[..., 1]

    if state in ("closed", "happy", "squint"):
        if state == "happy":                              # an arch, its legs running down at each side
            a = np.radians(np.linspace(-SMILE[3], SMILE[3], 41))
            lines = [(lam0 + SMILE[0] * np.sin(a), phi0 + SMILE[2] + SMILE[1] * (1 - np.cos(a)))]
        elif state == "closed":                           # the lid shut in sleep curves down
            t = np.linspace(-1, 1, 33)
            lines = [(lam0 + EYE_A * 1.25 * t, phi0 + 3 + EYE_B * 0.36 * (0.5 - t * t))]
        else:                                             # two strokes from a point by the beak
            t = np.linspace(0, 1, 13)
            lines = [(lam0 - side * EYE_A * 0.9 * (1 - 2 * t), phi0 + 2 + way * EYE_B * 0.5 * t) for way in (-1, 1)]
        shapes = []
        for lam, phi in lines:
            pts, z = h.flat(globe(*upright(lam, phi)))
            along = np.linspace(0.0, 1.0, len(pts))
            if state == "squint":
                wide = SHUT_WIDE + (SHUT_THIN - SHUT_WIDE) * along
            else:
                wide = SHUT_THIN + (SHUT_WIDE - SHUT_THIN) * np.sin(math.pi * along) ** 0.7
            for run in stretches(z > 0):
                shapes += ribbon(pts[run], wide[run])
        if shapes:
            c.paint(both(c.mask(shapes), inside), EYE_DARK)
        return
    a, b = (EYE_A * 1.06, EYE_B * 1.08) if state == "wide" else (EYE_A, EYE_B)
    b *= min(max(1 - EYE_FAR * (0.885 - float(h.spin(globe(lam0, phi0))[2])), 0.8), 1.04)
    shut = float(state) if not isinstance(state, str) else 0.0
    lam, phi = upright(*spot(lam0, phi0, a, b))
    lid = phi0 - b + 1.85 * b * shut
    pts, z = h.flat(globe(lam, np.maximum(phi, lid)))
    if (z > 0).sum() < 4:
        return
    eye = both(c.mask([pts]), inside)
    x0, y0, x1, y1 = c.box(pts, 3.0)
    glint, _ = h.flat(globe(lam - 0.22 * a, phi - 0.34 * b))      # the light caught along the bottom and the far side
    low = np.clip(1.6 * blur(amount(less(eye, c.mask([glint])))[y0:y1, x0:x1], 1.4 * OUT * SS), 0.0, 1.0)
    c.lay(eye.crop((x0, y0, x1, y1)), EYE_DARK + (EYE_LOW - EYE_DARK) * low[..., None], (x0, y0))
    small = 0.8 if state == "wide" else 1.0
    pl, pp = upright(*spot(lam0, phi0 + 0.04 * b, 0.40 * a * small, 0.58 * b * small, 32))
    pupil, pz = h.flat(globe(pl + lx, np.maximum(pp + ly, lid)))
    c.paint(both(c.mask([pupil]), eye), PUPIL)
    if phi0 - 0.5 * b > lid:                              # the shine
        sl, sp = upright(*spot(lam0 - 0.40 * a, phi0 - 0.50 * b, 0.40 * a, 0.40 * a * 1.05, 24))
        shine, sz = h.flat(globe(sl + 0.4 * lx, np.maximum(sp + 0.4 * ly, lid)))
        if (sz > 0).all():
            c.paint(both(c.mask([shine]), inside), SHINE)


def _hem():
    lam = np.arange(0.0, 181.0)
    front = CAPE_NOTCH + CAPE_DROP * np.sin(np.radians(90.0 * np.minimum(lam, CAPE_LOBE) / CAPE_LOBE)) ** 0.72
    rest = np.interp(lam, [CAPE_LOBE] + [l for l, _ in CAPE_HEM], [CAPE_NOTCH + CAPE_DROP] + [p for _, p in CAPE_HEM])
    for _ in range(3):                                    # round off the corners of the part that is given as places
        rest[1:-1] = (rest[:-2] + 2 * rest[1:-1] + rest[2:]) / 4
    return np.where(lam <= CAPE_LOBE, front, rest)


HEM = _hem()


def cape_hem(lam):
    """How far down the cape comes, at so many degrees round from the front."""
    lam = np.abs((np.asarray(lam, float) + 180.0) % 360.0 - 180.0)
    return np.interp(lam, np.arange(0.0, 181.0), HEM)


def cape_shape(b):
    """The part of the cape that shows: the shape it makes with the edge of the body over
    the top, and the hem where it faces us, as a line."""
    lam = np.linspace(-180.0, 180.0, 361)[:-1]
    places = globe(lam, cape_hem(lam))
    turned = b.spin(places)
    seen = turned[:, 2] > 0
    if seen.all() or not seen.any():
        return (b.flat(places)[0], b.flat(places)[0]) if seen.all() else (np.zeros((0, 2)), np.zeros((0, 2)))
    first = next(i for i in range(len(lam)) if seen[i] and not seen[i - 1])      # the run of it that faces us, from left to right
    run = [(first + i) % len(lam) for i in range(int(seen.sum()))]
    hem = b.flat(places[run], wrap=False)[0]
    start, end = (math.atan2(turned[i, 1], turned[i, 0]) for i in (run[0], run[-1]))
    if start > -math.pi / 2:
        start -= 2 * math.pi
    over = np.linspace(end, start, 48)                    # back from its right end, over the top, to its left
    return np.concatenate([hem, b.disc(np.stack([np.cos(over), np.sin(over)], 1))]), hem


def thighs(p):
    """The tops of its legs: a round lump low on each side of the body, over the foot.
    Each is where it is and the shape it is, as (middle, shape)."""
    if p.pose["seated"] > 0.5:                             # sat down, its legs are out in front
        return []
    yaw, b, lumps = math.radians(p.body_yaw), p.body, []
    for side in (-1, 1):
        lifted = p.pose["feet"][0 if side < 0 else 1][1]
        along = side * (HIP + THIGH[2]) * math.cos(yaw) - HIP_BACK * math.sin(yaw)
        middle = b.c + b.lin @ np.array([along - p.pose["hips"][0], -THIGH[1] - BODY_Y - p.pose["hips"][1] - 0.35 * lifted])
        nearness = -side * HIP * math.sin(yaw)              # how far towards us this hip is
        lumps.append((middle, CIRCLE[::2] * THIGH[0] @ b.lin.T + middle, nearness))
    return sorted(lumps, key=lambda lump: lump[2])         # the nearer one last


def draw_body(sheet, p, shadows=()):
    """The body, lit as a ball, the tops of its legs and its two white buttons, with the
    soft shadows thrown on it by whatever lies across it. The cape goes on afterwards,
    over the tops of the flippers."""
    b = p.body
    rim = b.outline()
    lumps = thighs(p)
    c = sheet.window(np.concatenate([rim] + [shape for _, shape, _ in lumps]), ROOM)
    k = OUT * SS
    ball = c.mask([rim])
    inside = c.mask([rim] + [shape for _, shape, _ in lumps])
    n = facing(c, b.c, b.A, b.square)
    for middle, shape, nearness in lumps:                 # where a leg sticks out of the body, it is a small ball of its own
        x0, y0, x1, y1 = c.box(shape, 1.0)
        out = np.asarray(less(c.mask([shape]), ball))[y0:y1, x0:x1] > 127
        if out.any():
            n[y0:y1, x0:x1][out] = facing(c, middle, b.lin * THIGH[0], box=(x0, y0, x1, y1))[out]
    coat = Coat(c)
    coat.fill(inside, BODY)
    cape, hem = cape_shape(b)
    hollow = 0.55 * blur(amount(c.mask([cape + b.lin @ np.array([1.0, 3.0])])), 2.5 * k)      # just under the hem of the cape
    for s in shadows:                                     # and under the flippers in front of it
        hollow = np.maximum(hollow, 0.5 * blur(amount(c.mask([s + b.lin @ np.array([5.0, 3.0])])), 3.0 * k))
    for middle, shape, nearness in lumps[-1:]:
        # Where the nearer leg sticks out of the body, the body's own edge runs on a little
        # way under it, as a soft crease: from where the two meet above the leg, curling in.
        if nearness < 4.0:                                 # seen from the front or the back, neither leg is the nearer
            continue
        angles = np.linspace(0.0, 360.0, 361)
        edge = b.rim(0.0, 360.0, 0.0, 361)
        under = np.hypot(*((edge - middle) @ np.linalg.inv(b.lin).T).T) < THIGH[0]
        if not under.any() or under.all() or not (np.hypot(*((shape - b.c) @ np.linalg.inv(b.A).T).T) > 1.0).any():
            continue
        top = min(np.nonzero(under)[0], key=lambda i: edge[i, 1])          # the higher end of the stretch that is under the leg
        way = 1 if under[(top + 1) % 360] else -1
        t = np.linspace(0.0, 1.0, 10)
        fold = np.concatenate([b.rim(a, a, i, 1) for a, i in zip(angles[top] + way * (-3.0 + 17.0 * t), 5.0 * t ** 1.6)])
        hollow = np.maximum(hollow, 0.8 * blur(amount(c.strokes([fold], 1.6)), 0.8 * k))

    for side in (-1, 1):                                  # the two white buttons, each in a fine groove
        pts, bz = b.flat(globe(*spot(side * BUTTON[0], BUTTON[1], BUTTON_A, BUTTON_B)))
        if (bz > 0).sum() < 4:
            continue
        coat.fill(both(c.mask([pts]), inside), WHITE)
        coat.fill(both(c.strokes(runs(pts, bz > 0), GROOVE), inside), RING)
    c.lay(inside, lit(coat, n, hollow))
    c.onto(sheet)


def draw_cape(sheet, p):
    """The cape, lit as the body is, and in the soft shadow of the head just under it."""
    b = p.body
    rim = b.outline()
    c = sheet.window(rim, ROOM)
    k = OUT * SS
    inside = c.mask([rim])
    cape, hem = cape_shape(b)
    cloth = both(c.mask([cape]), inside)
    coat = Coat(c)
    coat.fill(cloth, BLUE)
    shadow = p.head.outline(1.0, tuple(p.head.lin @ np.array([2.0, 6.0])))
    c.lay(cloth, lit(coat, facing(c, b.c, b.A, b.square), 0.4 * blur(amount(c.mask([shadow])), 4.0 * k)))
    c.onto(sheet)


# How wide a flipper is along its length, from the shoulder to the tip.
FLIP_T = (-0.05, -0.035, -0.015, 0.0, 0.07, 0.14, 0.254, 0.346, 0.415, 0.5, 0.6, 0.7, 0.785, 0.842, 0.914, 0.971, 0.99, 1.0)
FLIP_H = (0.0, 0.25, 0.42, 0.50, 0.60, 0.675, 0.81, 0.95, 1.0, 0.95, 0.90, 0.85, 0.76, 0.66, 0.44, 0.19, 0.08, 0.0)


def flipper_shape(p, side):
    """A flipper: its outline, the line down its middle, half its width along that, the
    direction away from the body, how far towards us its shoulder is, and how much
    bigger than life it is drawn for being near."""
    lift = p.pose["flippers"][0 if side < 0 else 1]
    sweep = p.pose["sweep"][0 if side < 0 else 1]
    b = p.body
    at = side * SHOULDER[0] + p.shoulders
    root, z = b.flat(globe(at, SHOULDER[1]), wrap=False, limb=True)
    near = math.tanh(5.0 * (float(z[0]) - 0.1))            # 1 for the one on the near side, -1 for the one on the far side
    wider, near = 1 + (FLIPPER_WIDER if near > 0 else FLIPPER_NARROWER) * near, 1 + FLIPPER_NEAR * max(near, 0.0)
    out3, forward3 = b.spin(globe(at, 0.0), limb=True), b.spin(globe(at - side * 90.0, 0.0), limb=True)
    th, sw = math.radians(lift), math.radians(sweep)
    way3 = np.array([0.0, 1.0, 0.0]) * math.cos(th) * math.cos(sw) + out3 * math.sin(th) + forward3 * math.cos(th) * math.sin(sw)
    way = b.lin @ way3[:2]
    seen = float(np.hypot(*way))                          # a flipper pointing at us looks shorter
    way = way / max(seen, 1e-6) if seen > 0.05 else b.lin @ np.array([0.0, 1.0])
    outward = b.lin @ out3[:2]
    across = np.array([-way[1], way[0]])
    if abs(float(across @ outward)) < 0.08:
        outward = b.lin @ np.array([side * 1.0, 0.0])
    if across @ outward < 0:
        across = -across
    s = np.linspace(FLIP_T[0], 1.0, 64)
    length = FLIPPER * near * max(seen, 0.55)
    half = 0.5 * FLIPPER_W * wider * np.interp(s, FLIP_T, FLIP_H)
    middle = root[0] + np.outer(s, way) * length + np.outer(np.sin(math.pi * np.clip(s, 0, 1)), across) * length * 0.035
    return dict(shape=np.concatenate([middle + across * half[:, None], (middle - across * half[:, None])[::-1]]),
                middle=middle, half=half, across=across, s=s, depth=float(z[0]), near=near)


def draw_flipper(sheet, p, f, near):
    """A flipper, rounded off at its edges: pale in front, with its dark back showing along
    the top of its outer edge. The far one is in the shade of the body."""
    middle, half, across = f["middle"], f["half"][:, None], f["across"]
    s = (f["s"] - 0.07) / 0.93                             # measured from where the flipper comes out from under the head
    c = sheet.window(f["shape"], ROOM)
    k = OUT * SS
    solid = c.mask([f["shape"]])
    coat = Coat(c)
    coat.fill(solid, FIN)
    # Its dark back: a wedge from the shoulder that narrows to nothing half way down the outer edge.
    outer, near_by = middle + across * half, f["near"]
    top = s <= 0.46
    edge = (middle + across * np.maximum(half - (12.0 * near_by * np.clip((0.46 - s) / 0.2, 0.0, 1.0))[:, None], -half))[top]
    coat.fill(both(c.mask([np.concatenate([(outer + across * 3.0)[top], edge[::-1]])]), solid), BLUE)
    hollow = None if near else np.full(solid.size[::-1], 0.45, np.float32)
    n = puffed(amount(solid), 0.28 * FLIPPER_W * near_by * k, steep=2.6)
    c.lay(solid, lit(coat, n, hollow, sheen=0.8))
    c.onto(sheet)


def tail_shapes(p):
    """The tail: two leaves that fan out from one point on its back, a long one and a
    shorter one above it. Returns them, the short one first."""
    b = p.body
    lam, phi = p.tail_at, TAIL[1]
    at = globe(lam, phi)
    root = b.flat(at * 0.9, wrap=False, limb=True)[0][0]
    long_tip = b.flat(at * 1.43 + (0.0, -0.054, 0.0), wrap=False, limb=True)[0][0]
    short_tip = b.flat(globe(lam + 0.4 * p.pose["tail"], phi - 9.75) * 1.316, wrap=False, limb=True)[0][0]
    prong = lambda tip, r: hull(np.concatenate([oval(*root, r[0]), oval(*(root + (tip - root) * 0.55), r[1]), oval(*tip, r[2])]))
    return prong(short_tip, (4.6, 5.4, 4.2)), prong(long_tip, (7.0, 8.6, 6.0))


def draw_tail(sheet, p):
    """The tail: two blue leaves, rounded off, the long one over the short one and
    throwing a soft shadow on it."""
    short, long = tail_shapes(p)
    c = sheet.window(np.concatenate([short, long]), ROOM)
    k = OUT * SS
    for shape, over in ((short, long), (long, None)):
        solid = c.mask([shape])
        coat = Coat(c)
        coat.fill(solid, BLUE)
        hollow = None if over is None else 0.5 * blur(amount(c.mask([over + np.array([1.5, 2.5])])), 2.0 * k)
        c.lay(solid, lit(coat, puffed(amount(solid), 3.2 * k, steep=2.4), hollow, sheen=0.9))
    c.onto(sheet)


def foot_wide(f):
    """Half the width of a foot, so far from its heel: round at the back, fanning out to
    the toes, and round across the front of them."""
    f = np.asarray(f, float)
    widest = FOOT_FAN * FOOT_LONG
    heel = FOOT_HEEL * np.sqrt(np.clip(1 - (f / FOOT_HEEL) ** 2, 0.0, 1.0))
    fan = FOOT_HEEL + (FOOT_HALF - FOOT_HEEL) * np.sin(0.5 * math.pi * np.clip(f / widest, 0.0, 1.0)) ** 1.25
    toes = FOOT_HALF * np.sqrt(np.clip(1 - np.clip((f - widest) / (FOOT_LONG - widest), 0.0, 1.0) ** 2, 0.0, 1.0))
    return np.where(f < 0, heel, np.where(f < widest, fan, toes))


def foot_high(f, out=0.0):
    """How thick it is there, `out` of the way from its middle to its edge: thick at the
    ankle and thin at the toes, with a top that is a low dome from side to side."""
    f = np.asarray(f, float)
    middle = FOOT_THIN + (FOOT_HIGH - FOOT_THIN) * np.clip(1 - f / (0.92 * FOOT_LONG), 0.0, 1.0) ** 1.2
    return (middle + ANKLE * np.clip(1 - np.maximum(f, 0.0) / 9.0, 0.0, 1.0)) * (1 - 0.45 * np.asarray(out, float) ** 2)


def _foot_at():
    """Places along a foot to work it out at: close together round the heel and the toes."""
    return np.concatenate([-FOOT_HEEL * np.cos(np.linspace(0, math.pi / 2, 5)), np.linspace(0, FOOT_FAN * FOOT_LONG, 8)[1:],
                           FOOT_LONG * (FOOT_FAN + (1 - FOOT_FAN) * np.sin(np.linspace(0, math.pi / 2, 10))[1:])])


FOOT_AT = _foot_at()


def foot(p, side):
    """A foot on the floor: a webbed fan, narrow and thick at the ankle, wide and thin at
    the toes. It is worked out as a solid thing, slice by slice from heel to toe, so it
    looks right from any side and tipped any way. Returns the shapes that make it up,
    those of them in shadow, and the two lines between its three toes."""
    along, lifted, more, tipped = p.pose["feet"][0 if side < 0 else 1]
    seated = p.pose["seated"]
    yaw = math.radians(p.body_yaw)
    lat, back = side * HIP * (1 - 0.1 * seated), HIP_BACK - 36.0 * seated
    hx = lat * math.cos(yaw) - back * math.sin(yaw)
    aim = yaw + math.radians(round_by(FEET_ROUND, p.body_yaw) + side * (SPLAY + more) * (1 - 0.3 * seated))
    tip = math.radians(tipped + 10.0 * seated)

    def place(f, s, up):
        f, s, up = np.broadcast_arrays(np.asarray(f, float), np.asarray(s, float), np.asarray(up, float))
        f, up = f * math.cos(tip) - up * math.sin(tip), f * math.sin(tip) + up * math.cos(tip)
        x = BODY_X + hx + along + f * math.sin(aim) + s * math.cos(aim)
        towards_us = f * math.cos(aim) - s * math.sin(aim)
        flat = np.stack([x, -lifted - up + towards_us * FOOT_SEEN - FLOOR], -1)
        return flat @ p.feet_whole[:, :2].T + p.feet_whole[:, 2]

    def across(f, lo, hi):
        """A slice across the foot at `f`, from `lo` to `hi` of the way out to its edges:
        points on its top, and on the floor under them."""
        out = np.linspace(lo, hi, 7)
        return np.concatenate([place(f, out * foot_wide(f), foot_high(f, out)), place(f, out * foot_wide(f), 0.0)])

    def solid(lo, hi, start, end):
        """The foot from `start` to `end` along it, and from `lo` to `hi` across it, which
        may each be a number or change along the foot."""
        at = np.unique(np.concatenate([[start, end], FOOT_AT[(FOOT_AT > start) & (FOOT_AT < end)]]))
        slices = [across(f, lo(f) if callable(lo) else lo, hi(f) if callable(hi) else hi) for f in at]
        return [hull(np.concatenate([a, b])) for a, b in zip(slices[:-1], slices[1:])]

    # The light comes from the left, so the body's shadow lies across the ankle and runs
    # on down the side of the foot away from the light.
    edge = lambda f: float(np.clip((f / FOOT_LONG - 0.12) / 0.27 - 1.0, -1.0, 1.0))        # the edge of the shadow, across the foot
    if math.cos(aim) >= 0:
        shade = solid(edge, 1.0, -FOOT_HEEL, 0.66 * FOOT_LONG)
    else:
        shade = solid(-1.0, lambda f: -edge(f), -FOOT_HEEL, 0.66 * FOOT_LONG)
    lines = []
    begin = FOOT_LONG * (0.16 + 0.30 * abs(math.sin(aim)))   # seen from the side, only the toes are marked
    for k in (-1, 1):                                     # the lines between the toes run to the front edge, spreading as they go
        f = np.linspace(begin, FOOT_LONG, 16)
        across_it = k * (2.6 + (FOOT_TOES * FOOT_HALF - 2.6) * (f / FOOT_LONG) ** 1.15)
        lines.append(place(f, across_it, foot_high(f, np.clip(np.abs(across_it) / np.maximum(foot_wide(f), 1e-6), 0.0, 1.0))))
    return dict(shapes=solid(-1.0, 1.0, -FOOT_HEEL, FOOT_LONG), shade=shade, lines=lines)


def draw_foot(sheet, p, f):
    """A foot, rounded off at its edges and with its top facing up into the light, soft
    creases between its three toes and, standing, the body's soft shadow across the ankle
    and down the side away from the light."""
    c = sheet.window(np.concatenate(f["shapes"]), ROOM)
    k = OUT * SS
    solid = c.mask(f["shapes"])
    coat = Coat(c)
    coat.fill(solid, ORANGE)
    hollow = 0.6 * blur(amount(c.strokes(f["lines"], 1.2)), 0.6 * k)
    if p.pose["seated"] < 0.5:                             # sat down, the feet are out in the light
        hollow = np.maximum(hollow, 0.5 * blur(amount(c.mask(f["shade"])), 1.8 * k))
    c.lay(solid, lit(coat, puffed(amount(solid), 2.6 * k, steep=2.2, tip=35.0), hollow))
    c.onto(sheet)


def draw_fx(sheet, fx):
    """Bubbles, sparkles, drops and lines of speed, soft and bright, with no line round them."""
    k = OUT * SS
    for kind, x, y, size, extra in fx:
        if size <= 0.3:
            continue
        c = sheet.window([(x - abs(extra) - 2.6 * size, y - 2.6 * size), (x + abs(extra) + 2.6 * size, y + 2.6 * size)]
                         if kind in ("dash", "pop") else [(x - 1.8 * size, y - 1.8 * size), (x + 1.8 * size, y + 1.8 * size)], ROOM / 2)
        if kind == "bubble":                              # see-through, more coloured towards its edge; extra: how solid, 0..1
            xs, ys = c.grid()
            edge = glide((np.hypot(xs - np.float32(x), ys - np.float32(y)) / np.float32(size) - 0.45) / 0.55)
            disc = amount(c.mask([oval(x, y, size)]))
            shine = np.maximum(amount(c.mask([oval(x - size * 0.36, y - size * 0.38, size * 0.26, size * 0.17, -40)])),
                               0.7 * amount(c.mask([oval(x + size * 0.40, y + size * 0.36, size * 0.09)]))) * disc
            colours = BUBBLE + (SHINE - BUBBLE) * (0.3 * edge)[..., None]
            colours = colours + (SHINE - colours) * shine[..., None]
            c.glaze(colours, np.maximum(disc * (0.2 + 0.6 * edge), shine) * extra)
        elif kind == "pop":                               # a bubble that has just burst: extra is how far the bits have flown
            lines = [np.array([(x + math.cos(a) * (size * 0.9 + extra), y + math.sin(a) * (size * 0.9 + extra)),
                               (x + math.cos(a) * (size * 1.3 + extra), y + math.sin(a) * (size * 1.3 + extra))])
                     for a in np.arange(6) * math.pi / 3 + 0.3]
            c.paint(c.strokes(lines, 2.2), BUBBLE)
        elif kind == "spark":                             # extra: turned, degrees
            c.paint(c.mask([star(x, y, size, extra)]), SPARK)
            c.paint(c.mask([star(x, y, size * 0.55, extra, thin=0.3)]), SPARK_LIGHT)
        elif kind == "drop":                              # extra: turned, degrees
            solid = c.mask([drop(x, y, size, extra)])
            edge = np.clip(2 * (1 - blur(amount(solid), 1.2 * k)), 0.0, 1.0)
            c.lay(solid, BUBBLE + (DROP_EDGE - BUBBLE) * (0.8 * edge)[..., None])
            c.paint(c.mask([oval(x - size * 0.3, y - size * 0.1, size * 0.22)]), SHINE)
        elif kind == "dash":                              # a line of speed: extra is its length
            c.paint(c.strokes([np.array([(x, y), (x + extra, y)])], size), DASH)
        c.onto(sheet)


def render(pose):
    """The pose, drawn, from the back of the picture to the front."""
    p = Piplup(pose)
    c = Canvas()
    draw_fx(c, [f for f in p.pose["fx"] if f[0] == "dash"])
    tail_behind = p.body.spin(globe(p.tail_at, TAIL[1]), limb=True)[2] < 0.25
    flippers = sorted((flipper_shape(p, side) for side in (-1, 1)), key=lambda f: f["depth"])
    behind, before = [f for f in flippers if f["depth"] < 0.08], [f for f in flippers if f["depth"] >= 0.08]
    seated = p.pose["seated"] > 0.5
    feet = sorted((foot(p, side) for side in (-1, 1)), key=lambda f: max(s[:, 1].max() for s in f["shapes"]))     # the nearer foot last
    if tail_behind:
        draw_tail(c, p)
    for f in behind:
        draw_flipper(c, p, f, near=False)
    if not seated:
        for f in feet:
            draw_foot(c, p, f)
    draw_body(c, p, shadows=[f["shape"] for f in before])
    if not tail_behind:
        draw_tail(c, p)
    if seated:
        for f in feet:
            draw_foot(c, p, f)
    for f in before:
        draw_flipper(c, p, f, near=True)
    draw_cape(c, p)
    draw_head(c, p)
    draw_fx(c, [f for f in p.pose["fx"] if f[0] != "dash"])
    return c.finish()


def _measure_floor():
    p = Piplup({})
    return max(float(shape[:, 1].max()) for side in (-1, 1) for shape in foot(p, side)["shapes"])


FLOOR = _measure_floor()                                  # so that the lowest toe stands on y = 0


def beak_tip(pose, beyond=0.10):
    """Where the tip of the beak is in a pose, in units: bubbles come from there."""
    h = Piplup(pose).head
    return h.flat(globe(*BEAK) + globe(BEAK[0], BEAK_POINTS) * (BEAK_OUT + beyond), wrap=False)[0][0]


def lowest(pose):
    """How far below the floor a pose would reach, in units."""
    p = Piplup(pose)
    parts = [p.body.outline(), p.head.outline()] + [flipper_shape(p, side)["shape"] for side in (-1, 1)]
    parts += [shape for side in (-1, 1) for shape in foot(p, side)["shapes"]]
    return max(float(part[:, 1].max()) for part in parts)


# ---------------------------------------------------------------- movement

FLIP_HZ, FLIP_DAMPING = 3.0, 0.45       # how fast a flipper swings back, and how soon it settles
FLIP_PUSH = 0.5                         # how hard the body's movement throws the flippers about


def animate(clip, seconds, fps, calm, loop=True, step=1 / 600):
    """Samples clip(t) through one turn of the loop, lets the flippers swing, and returns
    the frames as (pose, milliseconds). A frame is held for as long as nothing has moved;
    in a calm clip the flippers have to move a little further to count, so the tail end of
    one settling does not cost a frame every time."""
    n = int(round(seconds / step))
    poses = [{**DEFAULT, **clip(i * step)} for i in range(n)]
    lifts = np.array([p["flippers"] for p in poses], np.float64)
    omega = 2 * math.pi * FLIP_HZ
    blur = np.exp(-0.5 * (np.arange(-30, 31) * step / 0.012) ** 2)
    blur /= blur.sum()
    for a, side in enumerate((-1, 1)):
        root = np.array([whole(p) @ (BODY_X + side * BODY_RX + p["hips"][0], BODY_Y - 40.0 + p["hips"][1], 1.0) for p in poses])
        if loop:
            acc = (np.roll(root, -1, 0) - 2 * root + np.roll(root, 1, 0)) / step ** 2
            acc = np.stack([np.convolve(np.tile(acc[:, k], 3), blur, "same")[n:2 * n] for k in (0, 1)], 1)
        else:
            acc = np.gradient(np.gradient(root, step, axis=0), step, axis=0)
            acc = np.stack([np.convolve(np.pad(acc[:, k], 30, mode="edge"), blur, "valid") for k in (0, 1)], 1)
        target = np.radians(lifts[:, a].copy())
        angle, speed = target[0], 0.0
        for _ in range(3 if loop else 1):
            for i in range(n):
                lifting = (side * math.cos(angle), -math.sin(angle))
                push = -(acc[i, 0] * lifting[0] + acc[i, 1] * lifting[1]) / FLIPPER * FLIP_PUSH
                speed += (-omega * omega * (angle - target[i]) - 2 * FLIP_DAMPING * omega * speed + push) * step
                angle += speed * step
                lifts[i, a] = math.degrees(angle)

    frames, every, grain = [], int(round(1 / fps / step)), 1.0 if calm else 0.5
    for k, i in enumerate(range(0, n, every)):
        ms = round((k + 1) * 1000 / fps) - round(k * 1000 / fps)        # so that the whole clip is exactly as long as it should be
        pose = {**poses[i], "flippers": (q(float(lifts[i, 0]), grain), q(float(lifts[i, 1]), grain))}
        if frames and frames[-1][0] == pose:
            frames[-1] = (pose, frames[-1][1] + ms)
        else:
            frames.append((pose, ms))
    if loop and len(frames) > 1 and frames[0][0] == frames[-1][0]:
        frames[0] = (frames[0][0], frames[0][1] + frames.pop()[1])
    return frames


def smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def ease(t, a=0.0, b=1.0):
    """0 before a, 1 after b, gliding between."""
    return smooth((t - a) / (b - a))


def bump(t, start, rise, hold, fall):
    """0, gliding up to 1 over `rise`, staying for `hold`, gliding back over `fall`."""
    return ease(t, start, start + rise) * (1 - ease(t, start + rise + hold, start + rise + hold + fall))


def swing(t, start, length, past=1.1):
    """0 before `start`, then quickly to 1, a little past it, and back to rest on 1 by
    start + length: how something with weight arrives."""
    u = min(max((t - start) / length, 0.0), 1.0) - 1
    return 1 + (past + 1) * u ** 3 + past * u ** 2


def blink(t, at):
    """The eyes for a blink that starts at `at`: quick to shut, a little slower to open."""
    for until, lids in ((0.05, 0.55), (0.15, "closed"), (0.20, 0.6)):
        if at <= t < at + until:
            return (lids, lids)
    return None


def q(v, step):
    """Rounded to a step, so that tiny changes do not cost a frame."""
    return round(round(v / step) * step, 3)


def flap(near, far=None):
    """Both flippers lifted by so much from where they hang."""
    return (REST[0] + near, REST[1] + (near if far is None else far))


def sparkles(t, start, length, centre, spread, count=6, size=13.0, seed=0.0):
    """Sparkles that fly out from a point, swell and fade."""
    u = (t - start) / length
    if not 0.0 <= u < 1.0:
        return ()
    out = []
    for i in range(count):
        a = 2 * math.pi * (i / count + 0.13 * seed) + 0.5 * math.sin(7.0 * i + seed)
        far = spread * (0.72 + 0.28 * u) * (0.85 + 0.15 * math.sin(3.0 * i + seed))
        out.append(("spark", q(centre[0] + math.cos(a) * far, 1), q(centre[1] + math.sin(a) * far, 1),
                    q(size * math.sin(math.pi * u) ** 0.7 * (0.7 + 0.3 * math.cos(5.0 * i + seed)), 0.5), q(90 * u + 40 * i, 3)))
    return tuple(out)


# ---------------------------------------------------------------- the clips

def idle(t):
    """Stands about: blinks, looks round at us and back, shakes a flipper, wags its tail,
    and now and then puffs out its chest, very pleased with itself."""
    eyes = blink(t, 1.2) or blink(t, 4.3) or blink(t, 4.62) or blink(t, 7.9) or OPEN
    peek = bump(t, 1.9, 0.16, 1.75, 0.22)                 # its eyes go first, and its head follows
    glance = swing(t, 2.02, 0.5) * (1 - ease(t, 3.5, 3.95))
    flick = bump(t, 5.4, 0.10, 0.05, 0.16) + bump(t, 5.76, 0.10, 0.05, 0.2)
    wag = bump(t, 6.8, 0.1, 0.6, 0.15)
    proud = swing(t, 8.3, 0.45) * (1 - ease(t, 9.2, 9.6))
    if proud > 0.45:
        eyes = HAPPY
    return dict(eyes=eyes, look=(q(-3.0 * peek * (1 - 0.7 * min(glance, 1.0)), 1), 0.0), turn=q(-24 * glance, 1),
                tilt=q(6 * glance - 4 * proud, 0.5), nod=q(2 * glance - 9 * proud, 0.5),
                flippers=flap(32 * flick + 12 * proud, 9 * proud), tail=q(13 * math.sin(2 * math.pi * 5 * t) * wag, 1),
                puff=q(proud, 0.05), beak=q(0.4 * bump(t, 8.75, 0.08, 0.16, 0.14), 0.1))


STEP = 0.6                              # seconds it takes two steps in
STRIDE = 24.5                           # how far a foot goes forward and back. The app moves a walking mate 0.55 of its
                                        # height a second, 163 units, and a foot on the floor has to keep up with that.


def foot_step(turn_of_walk):
    """One foot through a turn of the walk, starting as it leaves the floor: how far along
    it is, how high, and how far its toes are tipped up."""
    turn_of_walk %= 1.0
    if turn_of_walk >= 0.5:                               # on the floor, carried back as the body goes forward over it
        return STRIDE * (3 - 4 * turn_of_walk), 0.0, 0.0
    s = turn_of_walk / 0.5                                # in the air: it leaves the floor still going back, swings past the other
    along = STRIDE * (-8 * s ** 3 + 12 * s ** 2 - 2 * s - 1)   # one, and is going back again as it comes down, so it never skids
    peel = math.sin(math.pi * min(s / 0.4, 1.0))          # the heel comes up first and the toes last,
    reach = math.sin(math.pi * min(max((s - 0.45) / 0.55, 0.0), 1.0))      # then the toes lift, reaching for the floor ahead
    return along, 7.0 * math.sin(math.pi * s) ** 0.9 + FOOT_LONG * math.sin(math.radians(11.0 * peel)), -11.0 * peel + 15.0 * reach


def walk(t):
    """A waddle, two steps to a turn: its weight rolls over the foot that is on the floor
    while the other swings past, its body rising over each step and settling as the foot
    comes down, flippers out for balance and its tail wagging after it."""
    u = 2 * math.pi * t / STEP
    side = math.sin(u)                                    # above 0, the near foot is in the air and the weight is on the far one
    near, far = foot_step(t / STEP), foot_step(t / STEP + 0.5)
    landed = (2 * t / STEP) % 1.0                         # how long ago a foot came down, in steps
    return dict(yaw=6.0, turn=-3.0, lean=2.5, hips=(q(1.8 * math.sin(u - 0.3), 0.25), q(-4.0 * abs(side) ** 0.9, 0.25)),
                sway=q(4.5 * math.sin(u - 0.3), 0.25), tilt=q(-2.0 * math.sin(u - 0.7), 0.25),
                bob=(0.0, q(1.5 * math.cos(2 * u - 0.6), 0.25)), squash=q(0.022 * math.exp(-7 * landed), 0.002),
                feet=((q(near[0], 0.25), q(near[1], 0.25), 0.0, q(near[2], 0.5)), (q(far[0], 0.25), q(far[1], 0.25), 0.0, q(far[2], 0.5))),
                flippers=flap(10 + 8 * math.sin(u - 0.5), 10 - 8 * math.sin(u - 0.5)),
                sweep=(q(-12 * math.cos(u - 0.3), 1), q(12 * math.cos(u - 0.3), 1)), tail=q(9 * math.sin(u + 0.9), 1))


def happy_flap(t):
    """Shown during every built-in dance move, which adds its own body motion on top:
    eyes shut in a smile, beak open in song, flippers flapping to the beat, its head
    tipping from side to side and its feet tapping."""
    u = 2 * math.pi * t / 1.0
    beat = (t % 0.5) / 0.5
    hit = math.exp(-5 * beat)
    lift = 60 + 46 * math.cos(2 * u)
    tap = math.sin(u)
    return dict(eyes=HAPPY, beak=q(0.25 + 0.6 * hit, 0.05), tilt=q(8 * math.sin(u), 0.5), turn=q(-5 + 4 * math.sin(u), 0.5),
                bob=(0.0, q(-3.5 * hit, 0.25)), flippers=(lift, lift), tail=q(12 * math.sin(2 * u), 1), puff=q(0.3 * hit, 0.05),
                feet=((0.0, q(5 * max(0.0, tap), 0.5), 0.0, q(14 * max(0.0, tap), 1)), (0.0, q(5 * max(0.0, -tap), 0.5), 0.0, q(14 * max(0.0, -tap), 1))))


BLOW = dict(turn=12.0, nod=-3.0, lean=4.0)               # how it stands to blow bubbles


def bubbles(t):
    """Four beats. A deep breath, chest out; then a stream of bubbles from its beak that
    drift up and away; then they burst, one after another, and it hops for joy."""
    fx = []
    start = beak_tip(BLOW)
    for i in range(6):
        born, burst = 0.50 + 0.14 * i, 1.50 + 0.065 * ((i * 5) % 6)
        size = 11 + 4.5 * ((i * 3) % 4)
        age = min(t, burst) - born
        if age <= 0:
            continue
        x = start[0] + 6 + (92 + 12 * (i % 3)) * age ** 0.8
        y = start[1] - (66 + 22 * ((i * 2) % 3)) * age ** 1.25 + 7 * math.sin(5 * age + i)
        if t < burst:
            fx.append(("bubble", q(x, 1), q(y, 1), q(size * ease(age, 0.0, 0.3), 0.5), 1.0))
        elif t < burst + 0.12:
            fx.append(("pop", q(x, 1), q(y, 1), q(size, 0.5), q(60 * (t - burst), 1)))
    if t < 0.45:                                          # the breath in
        e = ease(t, 0.0, 0.38)
        return dict(eyes=CLOSED, puff=q(e, 0.05), nod=q(-12 * e, 0.5), lean=q(-4 * e, 0.25), flippers=flap(22 * e))
    if t < 1.40:                                          # blowing
        e = ease(t, 0.45, 0.55)
        out = ease(t, 0.5, 1.35)
        wob = math.sin(2 * math.pi * 6 * t)
        return dict(eyes=HAPPY, beak=0.3, puff=q(1 - out, 0.05), turn=q(BLOW["turn"] * e, 0.5), nod=q(-12 + 9 * e, 0.5),
                    lean=q(-4 + 8 * e, 0.25), flippers=flap(22 - 8 * e + 5 * wob, 22 - 8 * e - 5 * wob), tail=q(8 * wob, 2), fx=tuple(fx))
    back = 1 - ease(t, 1.78, 1.98)                        # watching them go, and a hop
    hop = math.sin(math.pi * min(max((t - 1.52) / 0.3, 0.0), 1.0))
    return dict(eyes=WIDE if t < 1.6 else (HAPPY if t < 1.9 else OPEN), look=(q(2 * back, 1), q(-3 * back, 1)) if t < 1.6 else (0.0, 0.0),
                beak=q(0.6 * hop, 0.1), turn=q(BLOW["turn"] * back, 0.5), nod=q(-3 * back - 6 * hop, 0.5), lean=q(4 * back, 0.25),
                dy=q(-16 * hop, 0.5), squash=q(-0.05 * hop + 0.06 * bump(t, 1.80, 0.04, 0.0, 0.1), 0.005),
                flippers=flap(14 * back + 80 * hop), fx=tuple(fx))


def pirouette(t):
    """Four beats. It winds itself up, spins twice round on one foot with its flippers flung
    out, and lands with them in the air in a shower of sparkles."""
    if t < 0.4:                                           # the wind-up, turning away
        e = ease(t, 0.0, 0.34)
        return dict(yaw=q(-36 * e, 1), squash=q(0.07 * e, 0.005), flippers=flap(18 * e), look=(q(2 * e, 1), 0.0), lean=q(-3 * e, 0.25))
    if t < 1.4:                                           # the spin
        u = (t - 0.4) / 1.0
        turned = -36 + (720 + 36) * (u - 0.35 * math.sin(2 * math.pi * u) / (2 * math.pi))
        up = math.sin(math.pi * u)
        return dict(eyes=HAPPY, beak=0.5, yaw=q(turned, 1), dy=q(-12 * up, 0.5), squash=q(-0.05 * up, 0.005), flippers=(88.0, 88.0),
                    feet=((0.0, 0.0, 0.0, 0.0), (0.0, q(16 * up ** 0.5, 0.5), 0.0, q(-20 * up ** 0.5, 1))),
                    fx=sparkles(t, 0.5, 0.85, (0, -172), 185, count=7, size=15, seed=0.4))
    u = (t - 1.4) / 0.6                                   # ta-da
    land = math.sin(math.pi * min(u / 0.3, 1.0))
    down = ease(u, 0.55, 0.97)
    return dict(eyes=HAPPY if u < 0.8 else OPEN, beak=q(0.7 * (1 - ease(u, 0.5, 0.8)), 0.1), squash=q(0.09 * land, 0.005),
                flippers=(140 + (REST[0] - 140) * down, 140 + (REST[1] - 140) * down), puff=q(0.6 * (1 - ease(u, 0.5, 0.9)), 0.05),
                nod=q(-6 * (1 - ease(u, 0.5, 0.9)), 0.5), fx=sparkles(t, 1.42, 0.45, (0, -175), 200, count=8, size=18, seed=0.9))


def belly_slide(t):
    """Four beats. A little jump, down on its belly, and off it slides, one way and back,
    flippers trailing and feet in the air, as penguins do; then it pushes itself upright."""
    down = ease(t, 0.22, 0.5) * (1 - ease(t, 1.5, 1.84))  # 0 standing, 1 flat out
    jump = math.sin(math.pi * min(t / 0.34, 1.0)) + 0.45 * math.sin(math.pi * min(max((t - 1.5) / 0.34, 0.0), 1.0))
    slide = math.sin(2 * math.pi * min(max((t - 0.5) / 1.0, 0.0), 1.0))
    going = math.cos(2 * math.pi * min(max((t - 0.5) / 1.0, 0.0), 1.0)) if 0.5 < t < 1.5 else 0.0
    kick = math.sin(2 * math.pi * 5 * t) * down
    pose = dict(lean=q(76 * down, 0.5), tilt=q(-62 * down, 0.5), turn=q(-12 * down, 0.5), nod=q(-6 * down, 0.5),
                bob=(q(-4 * down, 0.25), q(8 * down, 0.25)),
                eyes=HAPPY if 0.3 < t < 1.7 else OPEN, beak=q(0.6 * down, 0.05),
                flippers=flap(26 * down + 55 * jump * (1 - down) + 12 * kick, -10 * down + 55 * jump * (1 - down)),
                sweep=(q(-20 * down, 1), q(-10 * down, 1)),
                feet=((0.0, 0.0, 0.0, q(25 * down + 22 * kick, 1)), (0.0, 0.0, 0.0, q(25 * down - 22 * kick, 1))),
                tail=q(12 * kick, 2), squash=q(0.07 * bump(t, 0.46, 0.05, 0.0, 0.14) + 0.07 * bump(t, 1.84, 0.04, 0.0, 0.08), 0.005),
                dx=q(-140 * down + 30 * slide * down, 0.5))
    pose["dy"] = q(-max(0.0, lowest({**DEFAULT, **pose, "fx": ()})) - 26 * jump * (1 - down), 0.5)
    if abs(going) > 0.25:                                 # lines of speed behind it
        way = 1 if going > 0 else -1
        x = pose["dx"] + (-60 if way > 0 else 300)        # just clear of its feet, or of its head
        pose["fx"] = tuple(("dash", q(x - way * (6 + 12 * k), 1), -30.0 - 40 * k, 3.6, q(-way * (18 + 8 * abs(going) - 4 * k), 1)) for k in range(2))
    return pose


def carried(t):
    """Picked up: eyes wide, beak open, flippers beating, feet pedalling in the air."""
    u = 2 * math.pi * t / 0.4
    return dict(eyes=WIDE, beak=0.55, squash=-0.04, sway=q(2.0 * math.sin(u), 0.25), nod=-4.0,
                flippers=(104 + 30 * math.sin(2 * u), 104 - 30 * math.sin(2 * u)),
                feet=((0.0, q(3 + 4 * math.sin(u), 0.5), 0.0, q(-22 + 16 * math.sin(u), 1)),
                      (0.0, q(3 - 4 * math.sin(u), 0.5), 0.0, q(-22 - 16 * math.sin(u), 1))),
                tail=q(10 * math.sin(u), 1), fx=(("drop", -108.0, -270.0, 8.0, -28.0),))


def falling(t):
    """Dropped: flippers up, eyes screwed shut, feet trailing."""
    u = 2 * math.pi * t / FALL
    return dict(eyes=SQUINT, beak=0.8, squash=-0.06, nod=-8.0, flippers=(140 + 8 * math.sin(u), 140 + 8 * math.sin(u + 1.6)),
                feet=((0.0, 5.0, 0.0, q(-26 + 5 * math.sin(u), 1)), (0.0, 5.0, 0.0, q(-26 + 5 * math.sin(u + 2.0), 1))))


FALL = 8 / 30                                             # how long one turn of the falling clip is: eight frames
SITTING = dict(seated=1.0, flippers=flap(-4.0, 3.0))


def sitting(t):
    """Sat down with its feet out in front. Blinks, looks about, and waggles its toes."""
    eyes = blink(t, 1.4) or blink(t, 4.9) or blink(t, 5.25) or OPEN
    peek = bump(t, 2.1, 0.16, 1.4, 0.22)
    glance = swing(t, 2.2, 0.5) * (1 - ease(t, 3.3, 3.7))
    waggle = math.sin(2 * math.pi * (t - 4.3) / 0.4) * bump(t, 4.3, 0.1, 0.65, 0.12)
    return dict(SITTING, eyes=eyes, look=(q(-3.0 * peek * (1 - 0.7 * min(glance, 1.0)), 1), 0.0), turn=q(-22 * glance, 1), tilt=q(6 * glance, 0.5),
                feet=((0.0, 0.0, 0.0, q(12 * waggle, 1)), (0.0, 0.0, 0.0, q(-12 * waggle, 1))),
                tail=q(10 * math.sin(2 * math.pi * 4 * t) * bump(t, 6.0, 0.1, 0.5, 0.12), 1))


def asleep(t):
    """Dozing where it sits, head nodding, with a bubble at its beak that swells as it
    breathes out and shrinks as it breathes in. The app adds the breathing and the Zs."""
    breath = 0.5 - 0.5 * math.cos(2 * math.pi * t / 4.0)
    pose = dict(SITTING, eyes=CLOSED, nod=q(15 + 4 * breath, 0.5), tilt=9.0, turn=-6.0, flippers=flap(-8.0, 0.0))
    size = q(4 + 15 * breath, 0.5)
    tip = beak_tip({**DEFAULT, **pose}, beyond=0.07)
    return dict(pose, fx=(("bubble", q(tip[0] + size * 0.9, 0.5), q(tip[1] + size * 0.25, 0.5), size, 1.0),))


def take_a_bow(t):
    """An action, played once: it puffs out its chest, beak in the air, as proud as can be,
    then sweeps one flipper across itself and bows low, and straightens up with a hop."""
    proud = swing(t, 0.15, 0.45) * (1 - ease(t, 1.2, 1.5))
    bow = ease(t, 1.5, 1.95) * (1 - swing(t, 2.7, 0.5))
    hop = math.sin(math.pi * min(max((t - 3.0) / 0.32, 0.0), 1.0))
    eyes = blink(t, 3.5) or (HAPPY if proud > 0.3 else (CLOSED if bow > 0.3 else OPEN))
    return dict(eyes=eyes, puff=q(proud, 0.05), nod=q(-13 * proud + 34 * bow - 5 * hop, 0.5), turn=q(-10 * bow, 0.5),
                lean=q(-3 * proud + 15 * bow, 0.25), bob=(q(6 * bow, 0.5), q(10 * bow, 0.5)),
                flippers=flap(14 * proud + 26 * bow + 80 * hop, 14 * proud + 40 * bow + 80 * hop),
                sweep=(q(55 * bow, 1), q(-45 * bow, 1)), beak=q(0.4 * bump(t, 0.6, 0.1, 0.3, 0.15) + 0.6 * hop, 0.05),
                dy=q(-14 * hop, 0.5), squash=q(0.05 * bump(t, 3.30, 0.03, 0.0, 0.1), 0.005), tail=q(10 * math.sin(2 * math.pi * 5 * t) * hop, 1),
                fx=sparkles(t, 0.55, 0.6, (112, -262), 34, count=3, size=14, seed=0.2))


CLIPS = {
    # key: file, name in the menu, the clip, its length, frames a second, calm
    "idle": ("idle.webp", None, idle, 10.0, 20, True),
    "walk": ("walk.webp", None, walk, STEP, 30, False),
    "sit": ("sit.webp", None, sitting, 7.0, 20, True),
    "sleep": ("sleep.webp", None, asleep, 4.0, 12, True),
    "dance": ("dance.webp", "Happy Flap", happy_flap, 1.0, 30, False),
    "dance_bubbles": ("dance_bubbles.webp", "Bubbles", bubbles, 2.0, 30, False),
    "dance_pirouette": ("dance_pirouette.webp", "Pirouette", pirouette, 2.0, 30, False),
    "dance_belly_slide": ("dance_belly_slide.webp", "Belly Slide", belly_slide, 2.0, 30, False),
    "action_take_a_bow": ("action_take_a_bow.webp", "Take a Bow", take_a_bow, 4.0, 30, True),
    "drag": ("drag.webp", None, carried, 0.40, 30, False),
    "fall": ("fall.webp", None, falling, FALL, 30, False),
}

HEIGHT = 150                             # how tall Piplup stands on screen at 100%, in pixels


def build(key, pool):
    """Renders one clip: its frames cropped to what they use, their timings, and where the
    feet are in the cropped frames."""
    _, _, clip, seconds, fps, calm = CLIPS[key]
    timeline = animate(clip, seconds, fps, calm, loop=not key.startswith("action"))
    images = pool.map(render, [pose for pose, _ in timeline], chunksize=4)
    used = np.max([im[..., 3] for im in images], axis=0) > 0
    ys, xs = np.nonzero(used.any(axis=1))[0], np.nonzero(used.any(axis=0))[0]
    assert xs[0] > 0 and ys[0] > 0 and xs[-1] < W - 1 and ys[-1] < H - 1, f"{key} runs off the canvas"
    x0, y0, x1, y1 = max(xs[0] - 2, 0), max(ys[0] - 2, 0), xs[-1] + 3, ys[-1] + 3
    anchor = [round(-X0 * OUT - x0, 1), round(-Y0 * OUT - y0, 1)]
    return [Image.fromarray(im[y0:y1, x0:x1], "RGBA") for im in images], [ms for _, ms in timeline], anchor


def main():
    import multiprocessing
    manifest = {"name": "Piplup", "height": HEIGHT, "facing": "right", "removeBackground": False, "clips": {}}
    standing = render({})[..., 3].any(axis=1).sum()            # how tall the mate is standing still, in saved pixels
    rows, pixels = [], 0
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    old = json.loads((PACK / "character.json").read_text()).get("clips", {}) if (PACK / "character.json").exists() else {}
    with multiprocessing.get_context("fork").Pool() as pool:
        for key, (file, name, *_) in CLIPS.items():
            if only and key not in only:
                if key in old:
                    manifest["clips"][key] = old[key]
                continue
            images, durations, anchor = build(key, pool)
            images[0].save(PACK / file, save_all=True, append_images=images[1:], duration=durations, loop=0,
                           lossless=True, quality=100, method=4)
            manifest["clips"][key] = {"file": file, "anchor": anchor, **({"name": name} if name else {})}
            if key == "idle":
                # The app makes the idle clip, at its tallest, `height` pixels high. Should idle
                # ever reach above its head, that would shrink it, so allow for it.
                manifest["height"] = round(HEIGHT * (images[0].height - 4) / standing)
            rows.append(images)
            if not key.startswith("action"):                   # the app reads an action as it shows it, and keeps none of it
                pixels += len(images) * images[0].width * images[0].height
            print(f"{file}: {len(images)} frames of {images[0].width}x{images[0].height}, {sum(durations) / 1000:.2f}s, "
                  f"{(PACK / file).stat().st_size // 1024} KB", flush=True)
    print(f"these clips: {sum(len(r) for r in rows)} frames, {pixels * 4 / 2 ** 20:.0f} MB if the app unpacked all but the actions at once")

    if only and "idle" not in only and (PACK / "character.json").exists():
        manifest["height"] = json.loads((PACK / "character.json").read_text())["height"]
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
