#!/usr/bin/env python3
"""Draws Ember, the fireball, and builds every animation in the pack.

    python3 make_frames.py            # writes the clips and character.json into the pack
    python3 make_frames.py --sheet    # also saves sheet.png, every frame on one page
    python3 make_frames.py idle       # only rebuilds the clips named

Nothing here starts from a picture. Ember is drawn by this script: a round, glowing ball of
fire on two stubby legs, with stubby arms, bead eyes, cheeks and a mouth, and a crown of
flame on top of its head. The ball is lit from a hot yellow core out to a deep orange rim,
with slow swirls of heat turning inside it and a warm glow around it. The flame is three
tongues of fire in layers, red outside and white-hot in the middle, and it never keeps
still: each tongue flickers, sways and stretches on its own, it leans back when Ember moves
and stays upright when Ember leans, and it can shrink to a sleepy flicker or roar up into
a column.

Each clip is a small function of time that returns a pose. The arms are not posed by hand
beyond that: a spring carries them, pushed about by how the shoulders move, so they lag
behind a hop and flop when Ember lands. The flame's flicker is made of waves that fit a
whole number of times into each clip, so every clip loops without a jump.

Needs numpy and pillow. This folder starts with "_", so the app does not load anything
from it.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
PACK = HERE.parent

# ---------------------------------------------------------------- sizes
# Positions are in units. x = 0 runs up Ember's middle and y = 0 is the floor, with y
# growing downwards as it does on screen. Standing, Ember is about 330 units tall, flame
# and all.

OUT = 1.0                                 # saved pixels per unit
SS = 4                                    # drawn this many times larger and averaged down, for smooth edges
X0, Y0, X1, Y1 = -240, -580, 240, 60      # the canvas: room for the flame to roar up and fireworks to burst
W, H = round((X1 - X0) * OUT), round((Y1 - Y0) * OUT)

R = 92.0                                  # the ball's radius
LEGS = 30.0                               # how far the ball stands above the floor
SEAT = 6.0                                # and how far, sitting
FLAME_BASE = 18.0                         # how far below the top of the ball the flame starts
FLAME_H = 118.0                           # how tall the middle tongue of the flame is

EYES = (32.0, -6.0)                       # the right eye, from the middle of the ball; the left mirrors it
EYE_RX, EYE_RY = 11.5, 14.5
MOUTH = (0.0, 30.0)
CHEEKS = (57.0, 22.0)
CHEEK_RX, CHEEK_RY = 14.0, 8.0

SHOULDER = (R * 0.86, 4.0)                # the right one, from the middle of the ball
ARM, ARM_R, HAND_R = 34.0, 11.0, 13.5     # shoulder to hand, how thick, and the round hand
HIP = 38.0
LEG_W = 17.0

# ---------------------------------------------------------------- colours

INK = (118, 30, 12)                       # the outline: a deep ember red rather than black
BODY_CORE = (255, 243, 160)
BODY_MID = (255, 172, 52)
BODY_RIM = (234, 82, 26)
FLAME_OUT = (238, 66, 22)
FLAME_MID = (255, 138, 30)
FLAME_IN = (255, 208, 64)
FLAME_CORE = (255, 249, 214)
LIMB = (246, 124, 42)
FOOT = (206, 74, 30)
EYE = (48, 14, 8)
MOUTH_IN = (122, 26, 16)
TONGUE = (255, 122, 112)
CHEEK = (255, 92, 70)
SPARK = (255, 246, 190)
SPARK_EDGE = (232, 96, 24)
SMOKE = (126, 116, 116)
GLOW = (255, 150, 40)

LINE = 3.2                                # the edge round each part, in units
FINE = 2.0


# ---------------------------------------------------------------- shapes
# A shape is a closed run of points, close enough together to pass for a curve.

def oval(cx, cy, rx, ry=None, tilt=0.0, n=56):
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    pts = np.stack([rx * np.cos(a), (rx if ry is None else ry) * np.sin(a)], 1)
    return move(turn(tilt), pts) + (cx, cy)


def soften(corners, cuts, n=10):
    """A shape with straight sides, with each corner rounded off over `cut` units of the
    two sides that meet there (never more than just under half of either side)."""
    corners = np.asarray(corners, float)
    out = []
    if np.isscalar(cuts):
        cuts = [cuts] * len(corners)
    for i, cut in enumerate(cuts):
        here, before, after = corners[i], corners[i - 1], corners[(i + 1) % len(corners)]
        lb, la = np.hypot(*(before - here)), np.hypot(*(after - here))
        cut = min(cut, 0.48 * lb, 0.48 * la)
        if cut < 0.05:
            out.append(here[None])
            continue
        a = here + (before - here) / lb * cut
        b = here + (after - here) / la * cut
        t = np.linspace(0, 1, n)[:, None]
        out.append((1 - t) ** 2 * a + 2 * (1 - t) * t * here + t ** 2 * b)
    return np.concatenate(out)


def ribbon(points, widths):
    """A line that swells and thins along its length, as a shape."""
    p = np.asarray(points, float)
    half = np.broadcast_to(np.asarray(widths, float), (len(p),))[:, None] / 2
    along = np.gradient(p, axis=0)
    across = np.stack([-along[:, 1], along[:, 0]], 1) / np.maximum(np.hypot(along[:, 0], along[:, 1]), 1e-9)[:, None]
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


def dense(points, step=6.0, closed=True):
    """The same shape with extra points along its straight sides, so it can bend."""
    p = np.asarray(points, float)
    nxt = np.roll(p, -1, 0) if closed else p[1:]
    cur = p if closed else p[:-1]
    out = []
    for a, b in zip(cur, nxt):
        n = max(1, int(math.ceil(np.hypot(*(b - a)) / step)))
        out.append(a + (b - a) * np.linspace(0, 1, n, endpoint=False)[:, None])
    if not closed:
        out.append(p[-1:])
    return np.concatenate(out)


def star(cx, cy, size, angle=0.0, thin=0.2):
    """A four-pointed sparkle."""
    pts = []
    for i in range(16):
        r = size if i % 4 == 0 else (size * thin if i % 2 == 0 else size * thin * 0.75)
        a = math.radians(angle) + i * math.pi / 8
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return np.array(pts)


# Moving shapes about: a move is a 3x3 matrix, and `a @ b` does b first, then a.

def shift(dx, dy):
    return np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], float)


def turn(degrees, about=(0.0, 0.0)):
    """Clockwise on screen, so a positive turn about the feet tips the top to the right."""
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return shift(*about) @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float) @ shift(-about[0], -about[1])


def stretch(sx, sy):
    return np.diag([sx, sy, 1.0])


def move(m, points):
    return np.asarray(points, float) @ m[:2, :2].T + m[:2, 2]


def mix(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


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

    def part(self, shapes, colour, line=LINE):
        """Shapes that belong together, drawn as one: a dark edge round the lot and none
        where they overlap. `colour` can also be a function, see `shaded`."""
        shapes = [self.px(s) for s in shapes]
        for s in shapes:
            self._fill(self.pen, s, INK)
        inner = [inset(s, line * OUT * SS) for s in shapes]
        if callable(colour):
            for s in inner:
                self._shaded(s, colour)
        else:
            for s in inner:
                self._fill(self.pen, s, colour)

    def shaded(self, points, colour_at):
        self._shaded(self.px(points), colour_at)

    def _shaded(self, px, colour_at):
        """A shape filled with colour that changes across it: colour_at(x, y) gets arrays of
        positions in units and gives back an array of colours."""
        x0, y0 = np.floor(px.min(0)).astype(int)
        x1, y1 = np.ceil(px.max(0)).astype(int) + 1
        if x1 <= x0 or y1 <= y0:
            return
        mask = Image.new("L", (x1 - x0, y1 - y0), 0)
        self._fill(ImageDraw.Draw(mask), px - (x0, y0), 255)
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        rgb = colour_at(xx / (OUT * SS) + X0, yy / (OUT * SS) + Y0)
        tile = Image.fromarray(np.dstack([np.clip(rgb, 0, 255), np.full(xx.shape, 255, np.float32)]).astype(np.uint8), "RGBA")
        tile.putalpha(mask)
        self.img.alpha_composite(tile, (int(x0), int(y0)))

    def stroke(self, points, width, colour=INK):
        """A line of even width with round ends."""
        px = [tuple(p) for p in np.rint(self.px(points)).astype(int).tolist()]
        w = max(1, round(width * OUT * SS))
        self.pen.line(px, fill=colour, width=w, joint="curve")
        for x, y in (px[0], px[-1]):
            self.pen.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=colour)

    def inside(self, shape, paint, opacity=1.0):
        """Runs paint(layer) and keeps only what falls inside the shape (all of it, with
        no shape), at the given opacity."""
        layer = Canvas()
        paint(layer)
        if shape is None:
            mask = Image.new("L", self.img.size, int(255 * opacity))
            box = layer.img.getbbox()
        else:
            mask = Image.new("L", self.img.size, 0)
            self._fill(ImageDraw.Draw(mask), self.px(shape), int(255 * opacity))
            box = mask.getbbox()
        if box is None:
            return
        cut = layer.img.crop(box)
        cut.putalpha(ImageChops.multiply(cut.getchannel("A"), mask.crop(box)))
        self.img.alpha_composite(cut, box[:2])

    def haze(self, shape, colour, blur, opacity):
        """A soft light: the shape blurred `blur` units all round its edge. Blurred at the
        saved size and scaled up, which is plenty for something with no edges."""
        small = Image.new("L", (W, H), 0)
        self._fill(ImageDraw.Draw(small), self.px(shape) / SS, int(255 * opacity))
        small = small.filter(ImageFilter.GaussianBlur(blur * OUT))
        # The blur's faint far edge would make every frame bigger for nothing: it goes.
        small = small.point(lambda v: 0 if v < 12 else round((v - 12) * 255 / 243))
        mask = small.resize(self.img.size, Image.BILINEAR)
        light = Image.new("RGBA", self.img.size, colour + (255,))
        light.putalpha(mask)
        self.img.alpha_composite(light)

    def finish(self):
        """The drawing at its saved size."""
        # Averaged with each colour weighted by how solid it is, so that the empty space
        # round the edge does not darken it.
        return np.asarray(self.img.convert("RGBa").reduce(SS).convert("RGBA"))


def ramp(stops, t):
    """Colours along a run of (position, colour) stops, for an array of positions."""
    t = np.clip(t, stops[0][0], stops[-1][0])
    out = np.zeros(t.shape + (3,), np.float32)
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        u = np.clip((t - a) / max(b - a, 1e-6), 0, 1)[..., None]
        here = ((t >= a) & (t <= b))[..., None]
        out = np.where(here, np.array(ca, np.float32) + (np.array(cb, np.float32) - np.array(ca, np.float32)) * u, out)
    return out


# ---------------------------------------------------------------- the rig

DEFAULT = dict(eyes=("open", "open"),                        # each: "open", "wide", "happy", "closed", "squint", "dizzy", or 0..1 shut
               look=(0.0, 0.0),                              # the face moved right and down, in units
               mouth="smile",                                # "smile", "open", "grin", "o", "cat", "flat", "wobble"
               arms=(26.0, 26.0), bend=(0.0, 0.0),           # degrees each arm is lifted from hanging straight down
               legs=((0.0, 0.0), (0.0, 0.0)),                # each leg: degrees swung outwards, units lifted
               seated=False,
               flame=1.0,                                    # how big the flame is: about 0.35 asleep, 2 roaring
               wild=0.0,                                     # how wildly it flickers, on top of its usual flicker
               wind=0.0,                                     # how far the flame's tips are blown sideways (set by `animate`)
               glow=1.0,                                     # how strongly the air round Ember glows
               tick=0.0, loop=1.0,                           # time in the clip and the clip's length, for the flicker
               fx=(),                                        # ("spark", x, y, size, angle), ("ember", x, y, r, alpha),
                                                             # ("smoke", x, y, r, alpha), ("trail", x0, y0, x1, y1, alpha)
               squash=0.0, lean=0.0, dx=0.0, dy=0.0)         # the whole mate; dy < 0 is up


def whole(pose):
    """How the whole mate is squashed, leant and moved, about the point between its feet."""
    return (shift(pose["dx"], pose["dy"]) @ turn(pose["lean"])
            @ stretch(1 + 0.7 * pose["squash"], 1 - pose["squash"]))


def centre(pose):
    """The middle of the ball, before the whole mate is moved."""
    return 0.0, -((SEAT if pose["seated"] else LEGS) + R)


def wave(pose, hz, phase):
    """A flicker that fits a whole number of times into the clip, so the clip loops."""
    loop = max(pose["loop"], 1e-6)
    n = max(1, round(hz * loop))
    return math.sin(2 * math.pi * n * pose["tick"] / loop + phase)


def tongue(x0, y0, width, height, sway, wiggle, phase):
    """One tongue of flame, standing on (x0, y0): wide low down, pointed at the tip, with a
    lick of a curve running up it."""
    us = np.linspace(0, 1, 30)
    half = width * (1 - us) ** 0.6 * (0.72 + 0.4 * np.sin(math.pi * us * 0.85))
    cx = x0 + sway * us ** 1.7 + wiggle * np.sin(2 * math.pi * (1.1 * us - phase)) * us * (1 - us) * 2.2
    cy = y0 - height * us
    left = np.stack([cx - half, cy], 1)
    right = np.stack([cx + half, cy], 1)
    return np.concatenate([left, right[::-1][1:]])


def flame_layers(pose):
    """The flame on Ember's head as layers of shapes, outermost first, in body units (before
    the whole mate is moved)."""
    cx, cy = centre(pose)
    base_y = cy - R + FLAME_BASE
    size, wild = pose["flame"], pose["wild"]
    # Fire rises: the flame stays upright when Ember leans, and its tips trail behind a move.
    upright = turn(-0.85 * pose["lean"], (cx, base_y))
    tongues = []
    for i, (x, w, h, lean_out) in enumerate(((0, 34, 1.0, 0), (-31, 24, 0.62, -18), (31, 24, 0.6, 16))):
        flick = 0.10 * wave(pose, 2.3 + i * 0.7, i * 1.7) + 0.05 * wave(pose, 5.1 + i, i * 0.9)
        flick *= 1 + 1.6 * wild
        height = FLAME_H * h * size * (1 + flick)
        sway = lean_out * size ** 0.5 + (6 + 14 * wild) * wave(pose, 1.6 + 0.5 * i, 2.1 * i) + pose["wind"] * (0.6 + 0.4 * h)
        wiggle = (7 + 10 * wild) * size ** 0.5
        phase = (pose["tick"] / max(pose["loop"], 1e-6)) * max(1, round((2.4 + 0.4 * i) * pose["loop"])) + i * 0.33
        tongues.append((cx + x * size ** 0.3, base_y + abs(x) * 0.25, w * size ** 0.4, height, sway, wiggle, phase))
    layers = []
    for scale_w, scale_h, drop in ((1.0, 1.0, 0.0), (0.66, 0.76, 6.0), (0.42, 0.52, 10.0), (0.22, 0.3, 12.0)):
        shapes = []
        for j, (x, y, w, h, sway, wiggle, phase) in enumerate(tongues):
            if scale_w < 0.5 and j > 0:
                continue                                   # the hottest middle only in the big tongue
            shapes.append(move(upright, tongue(x, y + drop, w * scale_w, h * scale_h, sway * scale_h, wiggle * scale_w, phase)))
        layers.append(shapes)
    return layers, base_y


def draw_glow(c, pose, m):
    """A warm haze round Ember, strongest close to its ball and its flame."""
    if pose["glow"] <= 0:
        return
    cx, cy = centre(pose)
    top = cy - R - FLAME_H * pose["flame"] * 0.55
    mid, half = (cy + top) / 2 + 8, (cy - top + 2 * R) / 2
    c.haze(move(m, oval(cx, mid, R * 1.12, half * 1.02)), GLOW, 22, 0.42 * pose["glow"])


def draw_flame(c, pose, m):
    layers, base_y = flame_layers(pose)
    outer = [move(m, s) for s in layers[0]]
    tip = min(float(s[:, 1].min()) for s in outer)
    base = float(move(m, [(0, base_y)])[0][1])
    span = max(base - tip, 1.0)

    def colours(a, b):
        return lambda x, y: ramp([(0.0, a), (1.0, b)], (base - y) / span)
    c.part(outer, colours(FLAME_MID, FLAME_OUT))
    for shapes, (a, b) in zip(layers[1:], ((FLAME_IN, FLAME_MID), (FLAME_CORE, FLAME_IN), (FLAME_CORE, FLAME_CORE))):
        for s in shapes:
            c.shaded(move(m, s), colours(a, b))


def draw_body(c, pose, m):
    cx, cy = centre(pose)
    ball = oval(cx, cy, R, n=96)
    hot = (cx - R * 0.28, cy - R * 0.32)
    m_inv = np.linalg.inv(m)

    def colours(x, y):
        # Back into the ball's own units, so the light stays put as Ember moves.
        bx = x * m_inv[0, 0] + y * m_inv[0, 1] + m_inv[0, 2]
        by = x * m_inv[1, 0] + y * m_inv[1, 1] + m_inv[1, 2]
        d = np.hypot(bx - hot[0], by - hot[1]) / (R * 1.25)
        return ramp([(0.0, BODY_CORE), (0.42, BODY_MID), (0.86, BODY_RIM), (1.2, mix(BODY_RIM, INK, 0.2))], d)
    c.part([move(m, ball)], colours)
    inner = move(m, inset(ball, LINE))

    def detail(layer):
        # Swirls of heat, turning slowly.
        spin = 360 * pose["tick"] / max(pose["loop"], 1e-6) * max(1, round(0.25 * pose["loop"]))
        for k, (r, start, length, width) in enumerate(((R * 0.62, 200, 70, 6), (R * 0.45, 20, 60, 5), (R * 0.78, 80, 45, 4))):
            a = np.radians(np.linspace(start, start + length, 20) + spin * (1 if k % 2 == 0 else -0.7))
            arc = np.stack([cx + r * np.cos(a), cy + 6 + r * 0.9 * np.sin(a)], 1)
            layer.fill(move(m, ribbon(arc, width * np.sin(np.linspace(0.2, math.pi - 0.2, 20)))), (255, 228, 120))
        # A shine at the top left.
        layer.fill(move(m, oval(cx - R * 0.42, cy - R * 0.52, R * 0.2, R * 0.11, tilt=-35)), (255, 255, 230))
    c.inside(inner, detail, 0.45)


def draw_face(c, pose, m):
    cx, cy = centre(pose)
    face = m @ shift(cx + pose["look"][0], cy + pose["look"][1])
    inner = move(m, inset(oval(cx, cy, R, n=96), LINE))

    def local(pts):
        return move(face, pts)

    def cheeks(layer):
        for side in (-1, 1):
            layer.fill(local(oval(side * CHEEKS[0], CHEEKS[1], CHEEK_RX, CHEEK_RY)), CHEEK)
    c.inside(inner, cheeks, 0.5)

    def features(layer):
        for side, state in zip((-1, 1), pose["eyes"]):
            draw_eye(layer, local, side * EYES[0], EYES[1], state)
        draw_mouth(layer, local, pose["mouth"])
    c.inside(inner, features)


def draw_eye(c, local, cx, cy, state):
    rx, ry = EYE_RX, EYE_RY
    us = np.linspace(-1, 1, 25)
    if state == "closed":                                   # asleep: a line curving down
        line = [(cx + u * rx * 1.15, cy + ry * (0.05 + 0.4 * (1 - u * u))) for u in us]
        c.fill(local(ribbon(line, [1.6 + 2.6 * math.sqrt(1 - u * u) for u in us])), INK)
        return
    if state == "happy":                                    # ^ ^
        line = [(cx + u * rx * 1.15, cy + ry * (0.45 - 0.9 * (1 - u * u) ** 0.85)) for u in us]
        c.fill(local(ribbon(line, [2.0 + 3.0 * math.sqrt(1 - u * u) for u in us])), INK)
        return
    if state == "dizzy":                                    # a swirl
        t = np.linspace(0, 3.2 * math.pi, 60)
        r = rx * 0.95 * t / t[-1]
        line = np.stack([cx + r * np.cos(t), cy + r * np.sin(t) * 1.1], 1)
        c.fill(local(ribbon(line, 2.6)), INK)
        return
    if state == "squint":                                   # > <
        side = 1 if cx < 0 else -1
        line = [(cx - side * rx, cy - ry * 0.6), (cx + side * rx * 0.8, cy), (cx - side * rx, cy + ry * 0.6)]
        c.fill(local(ribbon(dense(line, 1.0, closed=False), 4.2)), INK)
        return
    shut = state if isinstance(state, float) else 0.0
    if state == "wide":
        rx, ry = rx * 1.2, ry * 1.2
    c.fill(local(oval(cx, cy, rx * (1 + 0.08 * shut), max(ry * (1 - shut), 1.4))), EYE)
    if shut < 0.4:                                          # two shines
        c.fill(local(oval(cx - rx * 0.28, cy - ry * 0.38, rx * 0.36, ry * 0.3 * (1 - shut))), (255, 255, 255))
        c.fill(local(oval(cx + rx * 0.3, cy + ry * 0.35, rx * 0.15, ry * 0.12 * (1 - shut))), (255, 255, 255))


def draw_mouth(c, local, mouth):
    cx, cy = MOUTH
    us = np.linspace(-1, 1, 25)
    if mouth == "smile":
        line = [(cx + u * 13, cy + 7 * (1 - u * u)) for u in us]
        c.fill(local(ribbon(line, [1.6 + 2.2 * math.sqrt(1 - u * u) for u in us])), INK)
        return
    if mouth == "cat":                                      # :3, a w
        line = [(cx + u * 14, cy + 4 * abs(math.sin(math.pi * u)) + 1.5 * (1 - u * u)) for u in us]
        c.fill(local(ribbon(line, 2.6)), INK)
        return
    if mouth == "flat":
        c.fill(local(ribbon([(cx - 9, cy + 3), (cx + 9, cy + 3)], 2.8)), INK)
        return
    if mouth == "wobble":                                   # "ow ow ow": a wavy line
        pts = [(cx + u * 15, cy + 3 + 2.6 * math.sin(3 * math.pi * u)) for u in np.linspace(-1, 1, 25)]
        c.fill(local(ribbon(pts, 2.6)), INK)
        return
    if mouth == "o":
        c.fill(local(oval(cx, cy + 6, 6.5, 8.0)), INK)
        c.fill(local(oval(cx, cy + 6, 4.2, 5.6)), MOUTH_IN)
        return
    # Open: a D, flat along the top, with a tongue; "grin" is wider.
    hw, depth = (14.0, 16.0) if mouth == "open" else (19.0, 19.0)
    top = [(cx + u * hw, cy - 1 + 1.5 * (1 - u * u)) for u in us]
    bottom = [(cx + u * hw * 0.98, cy - 1 + depth * (1 - u * u) ** 0.65) for u in us[::-1]]
    lip = np.array(top + bottom[1:-1])
    c.fill(local(lip), INK)
    c.fill(local(inset(lip, 1.8)), MOUTH_IN)
    c.fill(local(oval(cx + 1, cy + depth * 0.68, hw * 0.55, depth * 0.28)), TONGUE)
    c.fill(local(ribbon(dense([(cx - hw * 0.92, cy - 0.5), (cx + hw * 0.92, cy - 0.5)], 1.0, closed=False), 2.4)), INK)


def shoulder(pose, side):
    cx, cy = centre(pose)
    return cx + side * SHOULDER[0], cy + SHOULDER[1]


def arm_shapes(side, lift, bend, start):
    """The arm on one side (-1 left, 1 right): a stubby tube with a round hand."""
    n = 12
    theta = np.radians(lift + bend * np.linspace(0, 1, n))
    heading = np.stack([side * np.sin(theta), np.cos(theta)], 1)
    steps = (heading[:-1] + heading[1:]) / 2 * ARM / (n - 1)
    line = np.array(start, float) + np.concatenate([[(0.0, 0.0)], np.cumsum(steps, 0)])
    across = np.stack([heading[:, 1], -heading[:, 0]], 1) * side
    tube = np.concatenate([line + across * ARM_R, (line - across * ARM_R)[::-1]])
    return [tube, oval(*line[0], ARM_R), oval(*(line[-1] + heading[-1] * 3), HAND_R)]


def draw_legs(c, pose, m):
    if pose["seated"]:
        return
    cx, cy = centre(pose)
    hip_y = -LEGS - 14
    for side, (swing, lift) in zip((-1, 1), pose["legs"]):
        length = LEGS + 14 - lift
        shape = soften([(-LEG_W, -4), (LEG_W, -4), (LEG_W + 2, length), (-LEG_W - 2, length)], [0, 0, 14, 14])
        c.part([move(m @ shift(side * HIP, hip_y) @ turn(-side * swing), shape)], FOOT)


def draw_seated_feet(c, pose, m):
    for side, (swing, lift) in zip((-1, 1), pose["legs"]):
        x, y = side * (HIP + 8), -6 - lift
        c.part([move(m, oval(x, y, 18, 13, tilt=side * (12 + swing)))], FOOT)
        c.stroke(move(m, oval(x, y, 9, 5.5, tilt=side * (12 + swing))), 1.2, mix(FOOT, INK, 0.3))


def draw_fx(c, fx):
    for kind, *args in fx:
        if kind == "spark":
            x, y, size, angle = args
            if size < 1:
                continue
            c.fill(star(x, y, size + 2.2, angle, 0.3), SPARK_EDGE)
            c.fill(star(x, y, size, angle, 0.22), SPARK)
        elif kind == "colour-spark":                        # fireworks: a sparkle in a colour of its own
            x, y, size, angle, colour = args
            if size < 1:
                continue
            c.fill(star(x, y, size + 2.2, angle, 0.3), mix(colour, INK, 0.45))
            c.fill(star(x, y, size, angle, 0.22), mix(colour, (255, 255, 255), 0.35))
        elif kind == "ember":
            x, y, r, alpha = args
            if r < 0.8 or alpha <= 0.02:
                continue

            def paint(layer, x=x, y=y, r=r):
                layer.fill(oval(x, y, r + 1.6), SPARK_EDGE)
                layer.fill(oval(x, y, r), SPARK)
            c.inside(None, paint, alpha)
        elif kind == "smoke":
            x, y, r, alpha = args
            if r < 1 or alpha <= 0.02:
                continue

            def paint(layer, x=x, y=y, r=r):
                for dx_, dy_, rr in ((0, 0, 1.0), (-0.75, 0.25, 0.7), (0.75, 0.2, 0.72), (0.1, -0.5, 0.66)):
                    layer.fill(oval(x + dx_ * r, y + dy_ * r, r * rr * 1.08), mix(SMOKE, INK, 0.3))
                for dx_, dy_, rr in ((0, 0, 1.0), (-0.75, 0.25, 0.7), (0.75, 0.2, 0.72), (0.1, -0.5, 0.66)):
                    layer.fill(oval(x + dx_ * r, y + dy_ * r, r * rr), SMOKE)
            c.inside(None, paint, alpha)
        elif kind == "trail":                                # the streak a rising spark leaves
            x0, y0, x1, y1, alpha = args
            if alpha <= 0.02:
                continue
            line = dense([(x0, y0), (x1, y1)], 3.0, closed=False)
            streak = ribbon(line, np.linspace(1.0, 7.0, len(line)))
            c.inside(None, lambda layer, streak=streak: layer.fill(streak, FLAME_IN), alpha)


def render(pose):
    """The pose, drawn."""
    pose = {**DEFAULT, **pose}
    c = Canvas()
    m = whole(pose)
    draw_glow(c, pose, m)
    draw_flame(c, pose, m)
    draw_legs(c, pose, m)
    for side, lift, bend in ((-1, pose["arms"][0], pose["bend"][0]), (1, pose["arms"][1], pose["bend"][1])):
        c.part([move(m, s) for s in arm_shapes(side, lift, bend, shoulder(pose, side))], LIMB)
    draw_body(c, pose, m)
    draw_face(c, pose, m)
    if pose["seated"]:
        draw_seated_feet(c, pose, m)
    draw_fx(c, pose["fx"])
    return c.finish()


# ---------------------------------------------------------------- movement

ARM_HZ, ARM_DAMPING = 3.6, 0.45         # how fast an arm swings back, and how soon it settles
ARM_PUSH = 0.6                          # how hard the body's movement throws the arms about
WIND = 0.05                             # how far the flame's tips trail, in units per unit/second of the head's speed


def animate(clip, seconds, fps, step=1 / 500):
    """Samples clip(t) through one turn of the loop, lets the arms swing and the flame trail
    behind the head, and returns the frames as (pose, milliseconds). The flame never keeps
    still, so every frame is a frame of its own."""
    n = int(round(seconds / step))
    poses = [{**DEFAULT, **clip(i * step), "tick": i * step, "loop": seconds} for i in range(n)]
    lifts = np.array([p["arms"] for p in poses], np.float64)
    omega = 2 * math.pi * ARM_HZ
    blur = np.exp(-0.5 * (np.arange(-24, 25) * step / 0.012) ** 2)
    blur /= blur.sum()

    def smoothed(a):
        return np.stack([np.convolve(np.tile(a[:, k], 3), blur, "same")[n:2 * n] for k in range(a.shape[1])], 1)

    for a, side in enumerate((-1, 1)):
        root = np.array([move(whole(p), [shoulder(p, side)])[0] for p in poses])
        acc = smoothed((np.roll(root, -1, 0) - 2 * root + np.roll(root, 1, 0)) / step ** 2)
        target = np.radians(lifts[:, a].copy())
        angle, speed = target[0], 0.0
        for _ in range(3):
            for i in range(n):
                lifting = (side * math.cos(angle), -math.sin(angle))
                push = -(acc[i, 0] * lifting[0] + acc[i, 1] * lifting[1]) / ARM * ARM_PUSH
                speed += (-omega * omega * (angle - target[i]) - 2 * ARM_DAMPING * omega * speed + push) * step
                angle += speed * step
                lifts[i, a] = math.degrees(angle)
    # The flame's tips are left behind by the head as it moves.
    head = np.array([move(whole(p), [(centre(p)[0], centre(p)[1] - R)])[0] for p in poses])
    speed = smoothed((np.roll(head, -1, 0) - np.roll(head, 1, 0)) / (2 * step))
    wind = np.clip(-speed[:, 0] * WIND, -45, 45)

    every = int(round(1 / fps / step))
    assert abs(every * step - 1 / fps) < 1e-9, "the frame rate has to divide the sampling rate, or the loop drifts"
    frames, ms = [], round(1000 / fps)
    for i in range(0, n, every):
        frames.append(({**poses[i], "arms": (round(float(lifts[i, 0]), 1), round(float(lifts[i, 1]), 1)),
                        "wind": round(float(wind[i]) + poses[i]["wind"], 1)}, ms))
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


def blink(t, at):
    """The eyes for a blink that starts at `at`: quick to shut, a little slower to open."""
    for until, lids in ((0.05, 0.6), (0.15, 1.0), (0.20, 0.65)):
        if at <= t < at + until:
            return (lids, lids)
    return None


OPEN, WIDE, HAPPY, CLOSED, SQUINT = ("open", "open"), ("wide", "wide"), ("happy", "happy"), ("closed", "closed"), \
    ("squint", "squint")
FLAME_TOP = -(LEGS + 2 * R - FLAME_BASE)  # where the flame starts, standing


def embers(t, loop, count, x=0.0, y=FLAME_TOP - 40, rise=150, spread=24, size=4.0, seed=0.0):
    """Little embers drifting up off the flame and going out, `count` of them in each loop."""
    out = []
    for k in range(count):
        u = ((t / loop) * 1 + k / count + seed) % 1
        drift = spread * math.sin(2 * math.pi * (u * 1.3 + k * 0.37 + seed))
        out.append(("ember", round(x + drift + 8 * (k % 3 - 1), 1), round(y - rise * u, 1),
                    round(size * (1 - u ** 1.5), 2), round(1 - u ** 2, 2)))
    return tuple(out)


def burst(t, start, length, centre_, spread, count=8, size=12.0, seed=0.0, colours=None):
    """A burst of sparkles thrown out from a point, growing and fading."""
    u = (t - start) / length
    if not 0 <= u <= 1:
        return ()
    out = []
    for i in range(count):
        a = 2 * math.pi * (i / count) + seed
        r = spread * (0.3 + 0.7 * u ** 0.55) * (0.8 + 0.2 * math.sin(3.1 * i + seed))
        s = size * math.sin(math.pi * min(1.0, u * 1.25)) * (0.7 + 0.3 * math.cos(2.3 * i))
        x, y = centre_[0] + r * math.cos(a), centre_[1] + r * math.sin(a) + 30 * u * u
        if colours:
            out.append(("colour-spark", round(x, 1), round(y, 1), round(s, 1), round(30 * u + 15 * i), colours[i % len(colours)]))
        else:
            out.append(("spark", round(x, 1), round(y, 1), round(s, 1), round(30 * u + 15 * i)))
    return tuple(out)


# ---------------------------------------------------------------- the clips

def idle(t):
    """Stands about, its flame flickering: blinks, glances to one side, lets embers drift up,
    and now and then flares up happily."""
    eyes = blink(t, 1.2) or blink(t, 4.2) or OPEN
    glance = bump(t, 2.3, 0.3, 1.0, 0.3)
    flare = bump(t, 4.7, 0.18, 0.4, 0.35)
    if flare > 0.4:
        eyes = HAPPY
    return dict(eyes=eyes, mouth="grin" if flare > 0.4 else "smile", look=(round(8 * glance, 1), 0.0),
                flame=1.0 + 0.35 * flare, wild=0.4 * flare, lean=1.2 * glance, squash=-0.03 * flare,
                arms=(26 + 30 * flare, 26 + 30 * flare), fx=embers(t, 6.0, 3))


def walk(t):
    """A waddle on stubby legs: rocks from foot to foot, lifting the free one, arms swinging
    the other way, the flame trailing behind."""
    u = 2 * math.pi * t / 0.5
    side = math.sin(u)
    left, right = max(0.0, side), max(0.0, -side)
    return dict(look=(6.0, 0.0), lean=1.5 + 4.0 * side, dy=-5.0 * abs(side), dx=2.0 * side,
                squash=0.025 * math.cos(u) ** 2, wind=-10.0,
                legs=((4 * left, 12 * left ** 0.8), (4 * right, 12 * right ** 0.8)),
                arms=(30 + 16 * side, 30 - 16 * side))


def happy_flames(t):
    """Shown during every built-in dance move, which adds its own body motion on top: both
    arms up and waving, a big grin, and the flame leaping on every beat with a spark off its tip."""
    u = 2 * math.pi * t / 1.0
    beat = (t % 0.5) / 0.5
    leap = math.exp(-beat * 5)
    return dict(eyes=HAPPY, mouth="grin", arms=(132 + 24 * math.sin(u), 132 - 24 * math.sin(u)),
                flame=1.15 + 0.35 * leap, wild=0.3,
                fx=burst(beat, 0.0, 0.6, (0, FLAME_TOP - 150), 40, count=3, size=11, seed=1.0 if t % 1 < 0.5 else 2.3))


def flare_up(t):
    """Four beats. Ember crouches and its flame sinks low while it gathers itself, then it
    springs up and the flame roars into a tall column with a burst of sparks, blazes there
    for two beats, and settles back down with a bounce."""
    if t < 0.5:                                          # gather
        g = ease(t, 0, 0.45)
        return dict(eyes=SQUINT if g > 0.4 else OPEN, mouth="flat", squash=0.1 * g, flame=1.0 - 0.45 * g,
                    wild=0.2 * g, arms=(26 - 16 * g, 26 - 16 * g), dx=1.5 * math.sin(2 * math.pi * 14 * t) * g)
    if t < 0.72:                                         # spring up, flame roars
        u = (t - 0.5) / 0.22
        return dict(eyes=WIDE, mouth="grin", squash=-0.1 * math.sin(math.pi * u), dy=-26 * math.sin(math.pi * u),
                    flame=0.55 + 1.3 * ease(u, 0, 0.7), wild=1.0, arms=(150, 150),
                    fx=burst(t, 0.56, 0.6, (0, FLAME_TOP - 140), 150, count=10, size=14, seed=0.4))
    if t < 1.5:                                          # blazing
        return dict(eyes=HAPPY, mouth="grin", flame=1.85 + 0.08 * math.sin(2 * math.pi * 4 * t), wild=1.0,
                    arms=(150 - 10 * math.sin(2 * math.pi * 2 * t), 150 + 10 * math.sin(2 * math.pi * 2 * t)),
                    fx=burst(t, 0.56, 0.6, (0, FLAME_TOP - 140), 150, count=10, size=14, seed=0.4)
                    + embers(t, 2.0, 6, y=FLAME_TOP - 150, rise=170, spread=50, size=5))
    u = (t - 1.5) / 0.5                                  # settle
    bounce = 0.1 * math.sin(math.pi * 2.5 * u) * (1 - u) ** 1.5
    return dict(eyes=HAPPY if u < 0.6 else OPEN, mouth="smile", squash=bounce, flame=1.85 - 0.85 * ease(u, 0, 0.7),
                wild=1.0 - ease(u, 0, 0.8), arms=(150 - 124 * ease(u, 0.1, 0.8), 150 - 124 * ease(u, 0.1, 0.8)))


def hot_potato(t):
    """Two beats. Hopping from foot to foot as if the floor were too hot, squeezing its eyes
    shut and going "ow ow ow", with a puff of smoke from each foot as it lands."""
    beat, side = (t % 0.5) / 0.5, 1 if t % 1.0 < 0.5 else -1
    hop = math.sin(math.pi * min(beat / 0.6, 1)) if beat < 0.6 else 0.0
    landing = beat - 0.6 if beat >= 0.6 else None
    lifted = (0.0, 0.0) if hop < 0.05 else ((6 * hop, 22 * hop) if side > 0 else (0, 0))
    lifted_other = (0.0, 0.0) if hop < 0.05 else ((6 * hop, 22 * hop) if side < 0 else (0, 0))
    fx = ()
    if landing is not None:
        u = landing / 0.4
        foot = -side * HIP
        fx = (("smoke", round(foot - 14 * u * side, 1), round(-10 - 34 * u, 1), round(12 + 18 * u, 1), round(0.9 * (1 - u) ** 0.7, 2)),
              ("smoke", round(foot + 14 * u * side, 1), round(-6 - 22 * u, 1), round(8 + 12 * u, 1), round(0.8 * (1 - u), 2)))
    return dict(eyes=SQUINT, mouth="wobble" if beat < 0.6 else "o", dy=-22 * hop, lean=side * 5 * hop,
                squash=0.08 * (1 - hop) if landing is not None else -0.05 * hop, flame=1.1 + 0.3 * hop, wild=0.6,
                legs=(lifted, lifted_other), arms=(70 + 50 * hop, 70 + 50 * hop), bend=(-20, -20), fx=fx)


FIREWORK_COLOURS = [(255, 214, 64), (255, 96, 64), (255, 170, 230), (120, 200, 255), (255, 250, 220), (160, 255, 140)]


def fireworks(t):
    """Four beats. Ember winds up with its arms back, flings them up and a spark shoots out of
    its flame and up into the sky, where it bursts into a ring of coloured sparkles. Ember
    watches it with an "ooh", then a smaller one goes up and it cheers."""
    rocket_top = FLAME_TOP - 250
    fx = ()
    if t < 0.4:                                          # wind up
        g = ease(t, 0, 0.35)
        pose = dict(eyes=OPEN, mouth="flat", squash=0.08 * g, arms=(26 - 20 * g, 26 - 20 * g), flame=1.0 - 0.2 * g)
    elif t < 0.6:                                        # fling
        u = (t - 0.4) / 0.2
        pose = dict(eyes=WIDE, mouth="open", squash=-0.06 * math.sin(math.pi * u), dy=-10 * math.sin(math.pi * u),
                    arms=(26 + 130 * ease(u, 0, 0.6), 26 + 130 * ease(u, 0, 0.6)), flame=0.8 + 0.6 * u, wild=0.6)
    else:
        pose = dict(eyes=WIDE if t < 1.25 else HAPPY, mouth="o" if t < 1.25 else "grin",
                    arms=(150 - 20 * ease(t, 1.6, 2.0), 150 - 20 * ease(t, 1.6, 2.0)), flame=1.3 - 0.3 * ease(t, 1.5, 2.0),
                    look=(0.0, -6.0 * (1 - ease(t, 1.6, 2.0))), wild=0.3)
        pose["arms"] = (150 - 124 * ease(t, 1.7, 2.0), 150 - 124 * ease(t, 1.7, 2.0))
    # The rocket: up from the flame tip, then the burst.
    if 0.5 <= t < 0.88:
        u = ease(t, 0.5, 0.88)
        y = FLAME_TOP - 100 + (rocket_top - FLAME_TOP + 100) * u
        fx += (("trail", 0.0, round(y + 70, 1), 0.0, round(y, 1), 0.8), ("spark", 0.0, round(y, 1), 9.0, round(90 * u)))
    fx += burst(t, 0.88, 0.8, (0, rocket_top), 150, count=14, size=19, seed=0.2, colours=FIREWORK_COLOURS)
    fx += burst(t, 0.92, 0.7, (0, rocket_top), 80, count=8, size=12, seed=0.6, colours=FIREWORK_COLOURS[2:] + FIREWORK_COLOURS[:2])
    if 1.1 <= t < 1.35:
        u = ease(t, 1.1, 1.35)
        y = FLAME_TOP - 100 + (rocket_top + 60 - FLAME_TOP + 100) * u
        fx += (("trail", -70.0, round(y + 50, 1), -70.0, round(y, 1), 0.7), ("spark", -70.0, round(y, 1), 7.0, round(90 * u)))
    fx += burst(t, 1.35, 0.6, (-70, rocket_top + 60), 95, count=10, size=15, seed=1.1, colours=FIREWORK_COLOURS[::-1])
    pose["fx"] = fx
    return pose


def carried(t):
    """Picked up: eyes wide, a little "o", arms flailing, legs pedalling, the flame streaming."""
    u = 2 * math.pi * t / 0.4
    return dict(eyes=WIDE, mouth="o", squash=-0.04, lean=1.5 * math.sin(u), wild=0.8,
                arms=(100 + 30 * math.sin(u), 100 - 30 * math.sin(u)),
                legs=((6 + 8 * math.sin(u + 1.0), 4 + 4 * math.sin(u + 1.0)), (6 - 8 * math.sin(u + 1.0), 4 - 4 * math.sin(u + 1.0))))


def falling(t):
    """Dropped: arms up, legs trailing, mouth open in alarm, the flame stretched out above."""
    u = 2 * math.pi * t / 0.24
    return dict(eyes=WIDE, mouth="open", squash=-0.06, flame=1.35, wild=1.0,
                arms=(140 + 8 * math.sin(u), 140 + 8 * math.sin(u + 1.6)),
                legs=((10 + 4 * math.sin(u), 6), (10 + 4 * math.sin(u + 2.0), 6)))


SITTING = dict(seated=True, arms=(38.0, 38.0))


def sitting(t):
    """Sat down with its feet out in front, flame calm. Blinks, waggles its feet, and lets an
    ember drift up now and then."""
    eyes = blink(t, 1.4) or blink(t, 3.6) or OPEN
    waggle = 9 * math.sin(2 * math.pi * (t - 2.0) / 0.45) * bump(t, 2.0, 0.12, 0.66, 0.12)
    return dict(SITTING, eyes=eyes, flame=0.9, legs=((round(waggle, 1), 0.0), (round(-waggle, 1), 0.0)),
                mouth="cat" if 2.0 < t < 3.0 else "smile",
                fx=embers(t, 5.0, 2, y=FLAME_TOP + LEGS - SEAT - 40, rise=110))


def asleep(t):
    """Dozing where it sits, eyes shut, its flame burnt down to a little flicker with a wisp of
    smoke rising off it. The app adds the breathing and the Zs."""
    smoke = []
    for k in range(2):
        u = ((t / 4.0) + k / 2) % 1
        smoke.append(("smoke", round(6 * math.sin(2 * math.pi * u + k), 1), round(FLAME_TOP + LEGS - SEAT - 40 - 120 * u, 1),
                      round(6 + 12 * u, 1), round(0.55 * math.sin(math.pi * u), 2)))
    return dict(SITTING, eyes=CLOSED, mouth="o" if math.sin(2 * math.pi * t / 4.0) > 0.3 else "smile",
                flame=0.36, glow=0.5, lean=2.0, arms=(30.0, 30.0), look=(0.0, 3.0), fx=tuple(smoke))


CLIPS = {
    # key: file, name in the Dance move menu, the clip, its length, frames a second (one that
    # divides 500, the rate the clips are sampled at, so a loop is exactly as long as it should be)
    "idle": ("idle.webp", None, idle, 6.0, 10),
    "walk": ("walk.webp", None, walk, 0.5, 20),
    "sit": ("sit.webp", None, sitting, 5.0, 10),
    "sleep": ("sleep.webp", None, asleep, 4.0, 10),
    "dance": ("dance.webp", "Happy Flames", happy_flames, 1.0, 20),
    "dance_flare_up": ("dance_flare_up.webp", "Flare Up", flare_up, 2.0, 20),
    "dance_hot_potato": ("dance_hot_potato.webp", "Hot Potato", hot_potato, 1.0, 20),
    "dance_fireworks": ("dance_fireworks.webp", "Fireworks", fireworks, 2.0, 20),
    "drag": ("drag.webp", None, carried, 0.40, 20),
    "fall": ("fall.webp", None, falling, 0.24, 25),
}


def build(key):
    """Renders one clip: its frames cropped to what they use, their timings, and where the
    feet are in the cropped frames."""
    _, _, clip, seconds, fps = CLIPS[key]
    timeline = animate(clip, seconds, fps)
    images = [render(pose) for pose, _ in timeline]
    used = np.max([im[..., 3] for im in images], axis=0) > 0
    ys, xs = np.nonzero(used.any(axis=1))[0], np.nonzero(used.any(axis=0))[0]
    assert xs[0] > 0 and ys[0] > 0 and xs[-1] < W - 1 and ys[-1] < H - 1, f"{key} runs off the canvas"
    x0, y0, x1, y1 = max(xs[0] - 2, 0), max(ys[0] - 2, 0), xs[-1] + 3, ys[-1] + 3
    anchor = [round(-X0 * OUT - x0, 1), round(-Y0 * OUT - y0, 1)]
    return [Image.fromarray(im[y0:y1, x0:x1], "RGBA") for im in images], [ms for _, ms in timeline], anchor


def main():
    manifest = {"name": "Ember", "height": 150, "facing": "right", "removeBackground": False, "clips": {}}
    standing = render({})[..., 3].any(axis=1).sum()            # how tall the mate is standing still, in saved pixels
    rows, pixels = [], 0
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    old = json.loads((PACK / "character.json").read_text()) if (PACK / "character.json").exists() else {"clips": {}}
    for key, (file, name, *_) in CLIPS.items():
        if only and key not in only:
            if key in old["clips"]:
                manifest["clips"][key] = old["clips"][key]
            continue
        images, durations, anchor = build(key)
        if len(images) == 1:
            file = file.rsplit(".", 1)[0] + ".png"
            images[0].save(PACK / file, optimize=True)
        else:
            images[0].save(PACK / file, save_all=True, append_images=images[1:], duration=durations, loop=0,
                           lossless=False, quality=88, alpha_quality=100, method=4)
        manifest["clips"][key] = {"file": file, "anchor": anchor, **({"name": name} if name else {})}
        if key == "idle":
            # The app makes the idle clip, at its tallest, `height` pixels high. The flame
            # reaches above where it stands still, so allow for it.
            manifest["height"] = round(150 * (images[0].height - 4) / standing)
        rows.append(images)
        pixels += len(images) * images[0].width * images[0].height
        print(f"{file}: {len(images)} frames of {images[0].width}x{images[0].height}, {sum(durations) / 1000:.2f}s, "
              f"{(PACK / file).stat().st_size // 1024} KB")
    print(f"these clips: {sum(len(r) for r in rows)} frames, {pixels * 4 / 2 ** 20:.0f} MB once the app has unpacked them")

    if only and "idle" not in only:
        manifest["height"] = old.get("height", manifest["height"])
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
