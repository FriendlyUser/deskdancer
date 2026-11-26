#!/usr/bin/env python3
"""Draws Aspen, the leaf, and builds every animation in the pack.

    python3 make_frames.py            # writes the clips and character.json into the pack
    python3 make_frames.py --sheet    # also saves sheet.png, every frame on one page
    python3 make_frames.py idle       # only rebuilds the clips named

Nothing here starts from a picture. Aspen is drawn by this script: a broad green leaf with a
pointed tip that curls over, standing on two stubby legs, with stubby arms, bead eyes,
cheeks and a mouth, and its stalk sticking out behind like a tail. A leaf is thin and it
bends, and that is what the script is built round. The blade is drawn along a spine that can
bow to either side and curl over at the tip, so it sways in a breeze, trails behind when
Aspen moves and flops when it lands. It is also a sheet folded a little along its midrib and
turned in three dimensions, so when Aspen spins the two halves narrow one after the other,
catch the light differently, and show the pale underside with all its veins. And it can turn
with the seasons, from green through gold and orange to red, from its edge inwards.

Each clip is a small function of time that returns a pose. The arms, the bend of the blade,
the curl of its tip and the stalk are not posed by hand beyond that: springs carry them,
pushed about by how the leaf moves. The breeze is made of waves that fit a whole number of
times into each clip, so every clip loops without a jump.

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
# Positions are in units. x = 0 runs up Aspen's middle and y = 0 is the floor, with y
# growing downwards as it does on screen. Standing, Aspen is about 280 units tall.

OUT = 1.0                                 # saved pixels per unit
SS = 4                                    # drawn this many times larger and averaged down, for smooth edges
X0, Y0, X1, Y1 = -250, -560, 250, 60      # the canvas: room to be blown up into the air and drift down
W, H = round((X1 - X0) * OUT), round((Y1 - Y0) * OUT)

BLADE = 250.0                             # the blade from its base to its tip, along the midrib
HALF = 104.0                              # half its width where it is widest, a third of the way up
LEGS = 28.0                               # how far the base of the blade stands above the floor
SEAT = 4.0                                # and how far, sitting
FOLD = 13.0                               # degrees each half is folded back from flat, along the midrib
TIP = 22.0                                # degrees the tip is curled over at rest

FACE = 94.0                               # how far up the blade the middle of the face is
EYES = (33.0, -8.0)                       # the right eye, from the middle of the face; the left mirrors it
EYE_RX, EYE_RY = 12.0, 15.0
MOUTH = (0.0, 22.0)
CHEEKS = (60.0, 15.0)
CHEEK_RX, CHEEK_RY = 13.0, 7.5

SHOULDER = (0.9, 70.0)                    # where an arm starts: how far out to the edge, and how far up the blade
ARM, ARM_R, HAND_R = 34.0, 9.5, 12.0      # shoulder to hand, how thick, and the round hand
HIP = 30.0
LEG_W = 15.0
TAIL = 128.0                              # how long the stalk is
TOOTH, TOOTH_EVERY = 2.3, 25.0            # the teeth along the blade's edge: how far each sticks out, and how far apart they are

# ---------------------------------------------------------------- colours

INK = (26, 84, 46)                        # the outline: a deep green rather than black
INK_AUTUMN = (112, 34, 28)                # and what it turns to when the leaf turns red
# The blade through the seasons, 0 green to 1 red.
SEASONS = [(0.0, (100, 190, 66)), (0.25, (170, 206, 58)), (0.45, (246, 204, 52)), (0.72, (242, 140, 44)), (1.0, (214, 66, 48))]
LIMBS = [(0.0, (128, 184, 64)), (0.45, (222, 184, 60)), (0.72, (220, 132, 50)), (1.0, (190, 70, 52))]
UNDERSIDE = (226, 238, 204)               # mixed into the blade's colour for its back
VEIN = (246, 255, 206)                    # mixed in for the veins
KNOB = (140, 106, 64)                     # the woody end of the stalk
EYE = (20, 44, 30)
MOUTH_IN = (88, 36, 40)
TONGUE = (255, 132, 128)
CHEEK = (255, 150, 146)
SPARK = (255, 255, 224)
SPARK_EDGE = (120, 190, 80)
WATER = (160, 220, 255)
WATER_EDGE = (58, 132, 204)
WIND = (240, 250, 255)
LADYBIRD = (228, 52, 44)
LADYBIRD_DARK = (36, 28, 32)

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
        self.ink = INK                                       # the colour of the outlines: it turns with the leaf

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
            self._fill(self.pen, s, self.ink)
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
               arms=(30.0, 30.0), elbow=(0.0, 0.0),          # degrees each arm is lifted from hanging straight down, and bent
               legs=((0.0, 0.0), (0.0, 0.0)),                # each leg: degrees swung outwards, units lifted
               seated=False,
               bend=0.0,                                     # degrees the blade bows over to the right by the time it reaches its tip
               curl=TIP,                                     # degrees the tip curls over on top of that
               turn=0.0,                                     # degrees the leaf is turned about its midrib: 90 is edge on, 180 its back
               season=0.0,                                   # 0 green, through gold and orange to 1, red
               breeze=1.0,                                   # how much the breeze stirs the blade
               tail=0.0,                                     # degrees the stalk droops (below 0, it perks up)
               tick=0.0, loop=1.0,                           # time in the clip and the clip's length, for the breeze
               fx=(),                                        # see draw_fx
               squash=0.0, lean=0.0, dx=0.0, dy=0.0)         # the whole mate; dy < 0 is up


def whole(pose):
    """How the whole mate is squashed, leant and moved, about the point between its feet."""
    return (shift(pose["dx"], pose["dy"]) @ turn(pose["lean"])
            @ stretch(1 + 0.7 * pose["squash"], 1 - pose["squash"]))


def wave(pose, hz, phase):
    """A stir of the breeze that fits a whole number of times into the clip, so the clip loops."""
    loop = max(pose["loop"], 1e-6)
    n = max(1, round(hz * loop))
    return math.sin(2 * math.pi * n * pose["tick"] / loop + phase)


PEAK = (1 / 3) ** 0.6 * (2 / 3) ** 1.2


def profile(s):
    """Half the blade's width, as a part of its widest, from s = 0 at the base to 1 at the
    tip: round at the bottom, widest a third of the way up, drawn out to a point."""
    s = np.clip(s, 0.0, 1.0)
    return s ** 0.6 * (1 - s) ** 1.2 / PEAK


def season_colour(q, stops=SEASONS):
    return tuple(int(round(float(v))) for v in ramp(stops, np.array(float(q), np.float32)))


EDGE_FIRST = 0.9                          # how far ahead of the middle the edge and the tip are in turning colour
LIGHT = (-0.45, 0.89)                     # where the light comes from: the left, and in front


class Blade:
    """The blade of the leaf in one pose: its midrib as a line that bows and curls, how wide
    it is all the way up, and how far each half is turned away from us."""

    N = 200

    def __init__(self, pose):
        k = np.linspace(0, 1, self.N)
        self.s = (1 - np.cos(math.pi * k)) / 2               # closer together at the base and the tip, where the edge turns fastest
        self.v = self.s * BLADE
        stir = pose["breeze"]
        bend = pose["bend"] + stir * (2.2 * wave(pose, 0.45, 0.0) + 0.9 * wave(pose, 1.15, 1.3))
        curl = pose["curl"] + stir * (3.0 * wave(pose, 0.7, 2.0) + 1.4 * wave(pose, 1.9, 0.5))
        self.angle = bend * self.s ** 1.5 + curl * np.clip((self.s - 0.58) / 0.42, 0, 1) ** 2
        a = np.radians(self.angle)
        along = np.stack([np.sin(a), -np.cos(a)], 1)
        self.across = np.stack([np.cos(a), np.sin(a)], 1)
        steps = (along[:-1] + along[1:]) / 2 * np.diff(self.v)[:, None]
        self.spine = np.array([0.0, -(SEAT if pose["seated"] else LEGS)]) + np.concatenate([[(0.0, 0.0)], np.cumsum(steps, 0)])
        # Along its edge the blade has little teeth, evenly spaced, that die away towards
        # the base and the tip.
        smooth_edge = HALF * profile(self.s)
        run = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(smooth_edge), np.diff(self.v)))])
        phase = 2 * math.pi * run / TOOTH_EVERY
        self.w = smooth_edge + TOOTH * np.sin(phase + 0.5 * np.sin(phase)) * np.clip((self.s - 0.05) / 0.1, 0, 1) * np.clip((0.97 - self.s) / 0.1, 0, 1)
        # A sheet folded back along its midrib and turned about it: seen from in front,
        # each half is as wide as the cosine of how far it is turned from facing us. Below
        # zero it has gone past edge on, and it is its back we see.
        spin, fold = math.radians(pose["turn"]), math.radians(FOLD)
        self.f = {1: math.cos(spin + fold) / math.cos(fold), -1: math.cos(spin - fold) / math.cos(fold)}
        self.depth = {1: -math.sin(spin + fold), -1: math.sin(spin - fold)}        # how near us its outer edge is
        self.facing = math.cos(spin)
        self.tone = {}
        for side, t in ((1, spin + fold), (-1, spin - fold)):
            nx, nz = (math.sin(t), math.cos(t)) if math.cos(t) >= 0 else (-math.sin(t), -math.cos(t))
            self.tone[side] = 0.6 + 0.47 * max(0.0, nx * LIGHT[0] + nz * LIGHT[1])

    def points(self, u, v):
        """Places on the blade: u units to the right of the midrib as the leaf lies flat,
        and v up it from the base."""
        u, v = np.asarray(u, float), np.asarray(v, float)
        p = np.stack([np.interp(v, self.v, self.spine[:, 0]), np.interp(v, self.v, self.spine[:, 1])], -1)
        across = np.stack([np.interp(v, self.v, self.across[:, 0]), np.interp(v, self.v, self.across[:, 1])], -1)
        return p + across * (u * np.where(u >= 0, self.f[1], self.f[-1]))[..., None]

    def edge(self, side):
        """The edge of one half (-1 left, 1 right), from the base to the tip."""
        return self.spine + self.across * (side * self.w * self.f[side])[:, None]

    def half(self, side):
        """One half as a shape: up its edge, and back down the midrib."""
        return np.concatenate([self.edge(side), self.spine[-2:0:-1]])

    def front(self):
        """The whole blade as a shape, when it faces us."""
        return np.concatenate([self.edge(1), self.edge(-1)[-2:0:-1]])

    def frame(self, v):
        """The move that puts something drawn flat (x across the blade, y down it) on the
        blade, with its middle on the midrib v up from the base."""
        return shift(float(np.interp(v, self.v, self.spine[:, 0])), float(np.interp(v, self.v, self.spine[:, 1]))) \
            @ turn(float(np.interp(v, self.v, self.angle)))

    def flat(self, side, season, back=False):
        """One colour for a half, for what is painted on it."""
        rgb = season_colour(season)
        if back:
            rgb = mix(rgb, UNDERSIDE, 0.5)
        return tuple(min(255, int(round(v * self.tone[side]))) for v in rgb)

    def colours(self, side, m, season, back):
        """The colour of one half at every point, for `Canvas.shaded`: lighter towards the
        tip, deeper at the edge, and turning with the seasons from the edge and the tip
        inwards."""
        m_inv = np.linalg.inv(m)
        up = np.maximum.accumulate(-self.spine[:, 1]) + np.arange(self.N) * 1e-4
        f, tone = max(abs(self.f[side]), 0.05), self.tone[side]

        def colour_at(x, y):
            # Back to where on the blade this is. Near enough, for a blade that is not bent double.
            bx = x * m_inv[0, 0] + y * m_inv[0, 1] + m_inv[0, 2]
            by = x * m_inv[1, 0] + y * m_inv[1, 1] + m_inv[1, 2]
            s = np.interp(-by, up, self.s)
            reach = np.interp(s, self.s, self.w) * f
            edge = np.clip(np.abs(bx - np.interp(s, self.s, self.spine[:, 0])) / np.maximum(reach, 2.0), 0, 1)
            q = np.clip(season * (1 + EDGE_FIRST) - EDGE_FIRST * (1 - np.maximum(edge, s) ** 1.5), 0, 1)
            rgb = ramp(SEASONS, q)
            if back:
                rgb = rgb + (np.array(UNDERSIDE, np.float32) - rgb) * 0.5
            return rgb * (tone * (0.93 + 0.13 * s) * (1 - 0.13 * edge ** 3))[..., None]
        return colour_at


def band(curve, towards, width=LINE):
    """The strip `width` wide along a line, on the side of it that `towards` is on: the dark
    edge of something whose outline that line is."""
    along = np.gradient(curve, axis=0)
    across = np.stack([-along[:, 1], along[:, 0]], 1)
    across /= np.maximum(np.hypot(across[:, 0], across[:, 1]), 1e-9)[:, None]
    if np.sum((towards - curve) * across) < 0:
        across = -across
    return np.concatenate([curve, (curve + across * width)[::-1]])


FRONT_VEINS = ((150, 36), (178, 30), (202, 22))              # each: how far up the midrib it starts, and how far it climbs
BACK_VEINS = ((28, 34), (62, 42), (98, 44), (134, 40), (166, 32), (196, 24), (220, 14))


def vein(blade, side, start, climb):
    t = np.linspace(0, 1, 14)
    v = start + climb * (0.5 * t + 0.5 * t * t)
    u = side * 0.8 * HALF * profile((start + climb) / BLADE) * t
    return ribbon(blade.points(u, v), np.linspace(3.4, 1.2, len(t)))


def draw_blade(c, pose, m, blade):
    season = pose["season"]
    look = shift(*pose["look"])
    overlap = blade.f[1] * blade.f[-1] < 0                   # turned so far that one half is seen behind the other
    for side in sorted((1, -1), key=lambda s: blade.depth[s]):
        front = blade.f[side] > 0
        shape = move(m, blade.half(side))
        c.shaded(shape, blade.colours(side, m, season, not front))
        if abs(blade.f[side]) > 0.12:
            colour = blade.flat(side, season, not front)
            face = m @ blade.frame(FACE) @ stretch(blade.f[side], 1) @ look

            def detail(layer, side=side, front=front, colour=colour, face=face):
                paint = mix(colour, VEIN, 0.42) if front else mix(colour, c.ink, 0.3)
                for start, climb in (FRONT_VEINS if front else BACK_VEINS):
                    layer.fill(move(m, vein(blade, side, start, climb)), paint)
                if front:
                    layer.fill(move(face, oval(side * CHEEKS[0], CHEEKS[1], CHEEK_RX, CHEEK_RY)), mix(colour, CHEEK, 0.8))
                    draw_eye(layer, lambda pts: move(face, pts), side * EYES[0], EYES[1], pose["eyes"][0 if side < 0 else 1])
            c.inside(shape, detail)
            if front and side == -1 and blade.f[side] > 0.45:
                s = np.linspace(0.42, 0.68, 16)
                shine = ribbon(blade.points(-0.66 * HALF * profile(s), s * BLADE), 15 * np.sin(np.linspace(0.08, math.pi - 0.08, 16)) ** 0.8)
                dot = blade.points(np.array([-0.7 * HALF * profile(0.35)]), np.array([0.35 * BLADE]))[0]

                def gloss(layer, shine=shine, dot=dot):
                    layer.fill(move(m, shine), (255, 255, 236))
                    layer.fill(move(m, oval(dot[0], dot[1], 4.5, 5.5)), (255, 255, 236))
                c.inside(shape, gloss, 0.3)
        # The dark edge, on the inside of the outline. None along the midrib, where the
        # halves meet, unless one half is behind the other and the fold is the outline.
        c.fill(band(move(m, blade.edge(side)), move(m, blade.spine)), c.ink)
        if overlap:
            c.fill(band(move(m, blade.spine), move(m, blade.edge(side))), c.ink)

    if blade.facing > 0.25:
        # The midrib, from above the face to the tip, and the mouth, which sits across it.
        v = np.linspace(124, BLADE - 3, 30)
        widths = 5.2 * np.clip((v - 124) / 30, 0, 1) ** 0.8 * (1 - 0.72 * (v - 124) / (BLADE - 127)) + 0.3
        rib = move(m, ribbon(blade.points(np.zeros_like(v), v), widths))
        lit = max(blade.tone.values())
        c.fill(rib, mix(tuple(min(255, int(x * lit)) for x in season_colour(season)), VEIN, 0.5))
        face = m @ blade.frame(FACE) @ stretch(blade.facing, 1) @ look
        c.inside(move(m, blade.front()), lambda layer: draw_mouth(layer, lambda pts: move(face, pts), pose["mouth"]))
    elif blade.facing < -0.25:
        # From behind, the midrib stands out all the way up.
        v = np.linspace(4, BLADE - 3, 40)
        rib = move(m, ribbon(blade.points(np.zeros_like(v), v), np.linspace(6.0, 1.4, len(v))))
        c.fill(rib, mix(blade.flat(1, season, True), c.ink, 0.42))


def draw_eye(c, local, cx, cy, state):
    rx, ry = EYE_RX, EYE_RY
    us = np.linspace(-1, 1, 25)
    if state == "closed":                                   # asleep: a line curving down
        line = [(cx + u * rx * 1.15, cy + ry * (0.05 + 0.4 * (1 - u * u))) for u in us]
        c.fill(local(ribbon(line, [1.6 + 2.6 * math.sqrt(1 - u * u) for u in us])), EYE)
        return
    if state == "happy":                                    # ^ ^
        line = [(cx + u * rx * 1.15, cy + ry * (0.45 - 0.9 * (1 - u * u) ** 0.85)) for u in us]
        c.fill(local(ribbon(line, [2.0 + 3.0 * math.sqrt(1 - u * u) for u in us])), EYE)
        return
    if state == "dizzy":                                    # a swirl
        t = np.linspace(0, 3.2 * math.pi, 60)
        r = rx * 0.95 * t / t[-1]
        line = np.stack([cx + r * np.cos(t), cy + r * np.sin(t) * 1.1], 1)
        c.fill(local(ribbon(line, 2.6)), EYE)
        return
    if state == "squint":                                   # > <
        side = 1 if cx < 0 else -1
        line = [(cx - side * rx, cy - ry * 0.6), (cx + side * rx * 0.8, cy), (cx - side * rx, cy + ry * 0.6)]
        c.fill(local(ribbon(dense(line, 1.0, closed=False), 4.2)), EYE)
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
        c.fill(local(ribbon(line, [1.6 + 2.2 * math.sqrt(1 - u * u) for u in us])), EYE)
        return
    if mouth == "cat":                                      # :3, a w
        line = [(cx + u * 14, cy + 4 * abs(math.sin(math.pi * u)) + 1.5 * (1 - u * u)) for u in us]
        c.fill(local(ribbon(line, 2.6)), EYE)
        return
    if mouth == "flat":
        c.fill(local(ribbon([(cx - 9, cy + 3), (cx + 9, cy + 3)], 2.8)), EYE)
        return
    if mouth == "wobble":                                   # "whoa": a wavy line
        pts = [(cx + u * 15, cy + 3 + 2.6 * math.sin(3 * math.pi * u)) for u in np.linspace(-1, 1, 25)]
        c.fill(local(ribbon(pts, 2.6)), EYE)
        return
    if mouth == "o":
        c.fill(local(oval(cx, cy + 6, 6.5, 8.0)), EYE)
        c.fill(local(oval(cx, cy + 6, 4.2, 5.6)), MOUTH_IN)
        return
    # Open: a D, flat along the top, with a tongue; "grin" is wider.
    hw, depth = (14.0, 16.0) if mouth == "open" else (19.0, 19.0)
    top = [(cx + u * hw, cy - 1 + 1.5 * (1 - u * u)) for u in us]
    bottom = [(cx + u * hw * 0.98, cy - 1 + depth * (1 - u * u) ** 0.65) for u in us[::-1]]
    lip = np.array(top + bottom[1:-1])
    c.fill(local(lip), EYE)
    c.fill(local(inset(lip, 1.8)), MOUTH_IN)
    c.fill(local(oval(cx + 1, cy + depth * 0.68, hw * 0.55, depth * 0.28)), TONGUE)
    c.fill(local(ribbon(dense([(cx - hw * 0.92, cy - 0.5), (cx + hw * 0.92, cy - 0.5)], 1.0, closed=False), 2.4)), EYE)


def shoulder(blade, side):
    v = SHOULDER[1]
    return blade.points(np.array(side * SHOULDER[0] * HALF * profile(v / BLADE)), np.array(v))


def arm_shapes(side, lift, bend, start, narrow=1.0):
    """The arm on one side (-1 left, 1 right): a stubby tube with a round hand. `narrow`
    squeezes it sideways, for an arm that points towards us or away as the leaf turns."""
    n = 12
    theta = np.radians(lift + bend * np.linspace(0, 1, n))
    heading = np.stack([side * np.sin(theta), np.cos(theta)], 1)
    steps = (heading[:-1] + heading[1:]) / 2 * ARM / (n - 1)
    line = np.concatenate([[(0.0, 0.0)], np.cumsum(steps, 0)])
    across = np.stack([heading[:, 1], -heading[:, 0]], 1) * side
    tube = np.concatenate([line + across * ARM_R, (line - across * ARM_R)[::-1]])
    place = shift(*start) @ stretch(narrow, 1)
    return [move(place, tube), move(place, oval(*line[0], ARM_R)), move(shift(*start), oval(*(line[-1] + heading[-1] * 3) * (narrow, 1), HAND_R))]


def draw_arms(c, pose, m, blade, limb):
    for side, lift, bend in ((-1, pose["arms"][0], pose["elbow"][0]), (1, pose["arms"][1], pose["elbow"][1])):
        f = blade.f[side]
        out = side if f >= 0 else -side
        c.part([move(m, s) for s in arm_shapes(out, lift, bend, shoulder(blade, side), max(abs(f), 0.35))], limb)


def narrowed(blade, least=0.3):
    """How much narrower the legs and the stalk are set, the leaf being turned."""
    f = blade.facing
    return f if abs(f) > least else (least if f >= 0 else -least)


def draw_legs(c, pose, m, blade, foot):
    if pose["seated"]:
        return
    hip_y = -LEGS - 12
    for side, (swing, lift) in zip((-1, 1), pose["legs"]):
        length = LEGS + 12 - lift
        shape = soften([(-LEG_W, -4), (LEG_W, -4), (LEG_W + 2, length), (-LEG_W - 2, length)], [0, 0, 13, 13])
        c.part([move(m @ shift(side * HIP * narrowed(blade), hip_y) @ turn(-side * swing), shape)], foot)


def draw_seated_feet(c, pose, m, foot):
    for side, (swing, lift) in zip((-1, 1), pose["legs"]):
        x, y = side * (HIP + 10), -7 - lift
        c.part([move(m, oval(x, y, 17, 12.5, tilt=side * (12 + swing)))], foot)
        c.stroke(move(m, oval(x, y, 8.5, 5.2, tilt=side * (12 + swing))), 1.2, mix(foot, c.ink, 0.3))


def draw_tail(c, pose, m, blade, stalk):
    """The stalk, sticking out behind (to the left: Aspen faces right) with a curl up at the
    end, where a woody knob shows where it came off its twig."""
    n = 18
    u = np.linspace(0, 1, n)
    start = -2.0 if pose["seated"] else 11.0                 # degrees below level it sets off at
    heading = np.radians(start + (-68.0 - start) * u ** 3.2 + pose["tail"] * u ** 1.5)
    steps = np.stack([-np.cos(heading), np.sin(heading)], 1)
    line = np.concatenate([[(0.0, 0.0)], np.cumsum((steps[:-1] + steps[1:]) / 2 * TAIL / (n - 1), 0)])
    place = m @ shift(0.0, blade.spine[0, 1] - 8) @ stretch(narrowed(blade, 0.15), 1)
    c.part([move(place, ribbon(line, np.linspace(11.5, 8.0, n)))], stalk, FINE)
    c.part([move(m @ shift(0.0, blade.spine[0, 1] - 8), oval(*(line[-1] * (narrowed(blade, 0.15), 1)), 7.4))], KNOB, FINE)


# ---------------------------------------------------------------- things round it

def leaflet(x, y, size, angle):
    """A little leaf, `size` long, with (x, y) at its middle."""
    s = (1 - np.cos(math.pi * np.linspace(0, 1, 16))) / 2
    half = size * 0.36 * profile(s)
    edge = np.concatenate([np.stack([half, size * (0.5 - s)], 1), np.stack([-half, size * (0.5 - s)], 1)[-2:0:-1]])
    return move(shift(x, y) @ turn(angle), edge)


def drop(x, y, r, tall=1.0):
    """A drop of water, pointed at the top, with (x, y) at its middle."""
    t = np.linspace(0, 2 * math.pi, 44, endpoint=False)
    return np.stack([x + 1.18 * r * np.sin(t) * np.sin(t / 2) ** 1.4, y + (0.2 - 1.2 * np.cos(t)) * r * tall], 1)


def gust(x, y, length, way):
    """A streak of wind with its head at (x, y), blowing right (way 1) or left (-1), that
    ends in a curl."""
    s = np.linspace(0, 1, 24)
    line = np.stack([x - way * length * (1 - s), y + 5 * np.sin(2.2 * math.pi * s) * (1 - s)], 1)
    a = np.linspace(0, 1.55 * math.pi, 20)[1:]
    r = 9.0 * (1 - 0.5 * a / a[-1])
    curl = np.stack([x + way * r * np.sin(a), y - 9.0 + r * np.cos(a)], 1)
    widths = np.concatenate([np.linspace(0.8, 3.6, len(s)), np.linspace(3.6, 1.2, len(a))])
    return ribbon(np.concatenate([line, curl]), widths)


def draw_ladybird(c, x, y, angle, size, wings=0.0):
    """A ladybird heading the way `angle` turns it from straight up. With its `wings` out
    (degrees), it is flying."""
    at = shift(x, y) @ turn(angle)
    if size < 1.5:
        return
    if wings > 1:
        for side in (-1, 1):
            c.fill(move(at @ turn(side * (wings + 28), (0, -size * 0.5)), oval(0, size * 0.35, size * 0.55, size * 1.25)), (250, 252, 255))
    c.fill(move(at, oval(0, -size * 0.72, size * 0.56, size * 0.5)), LADYBIRD_DARK)
    if wings > 1:
        c.fill(move(at, oval(0, 0, size * 0.5, size * 0.9)), LADYBIRD_DARK)
    for side in (-1, 1):
        case = at @ turn(side * wings, (0, -size * 0.55)) if wings > 1 else at
        half = [(side * size * 0.82 * math.sin(a), -size * math.cos(a)) for a in np.linspace(0, math.pi, 18)]
        c.fill(move(case, half), LADYBIRD_DARK)
        c.fill(move(case, [(side * max(size * 0.82 * math.sin(a) - 1.4, 0.7), -(size - 1.4) * math.cos(a))
                           for a in np.linspace(0, math.pi, 18)]), LADYBIRD)
        for dx_, dy_, r in ((0.4, -0.22, 0.2), (0.36, 0.42, 0.22)):
            c.fill(move(case, oval(side * size * dx_, size * dy_, size * r)), LADYBIRD_DARK)


def draw_fx(c, fx, m, blade):
    for kind, *args in fx:
        if kind == "spark":
            x, y, size, angle = args
            if size < 1:
                continue
            c.fill(star(x, y, size + 2.2, angle, 0.3), SPARK_EDGE)
            c.fill(star(x, y, size, angle, 0.22), SPARK)
        elif kind == "leaflet":                              # a little leaf in the air: where, how long, turned, its season, how solid
            x, y, size, angle, season, alpha = args
            if size < 3 or alpha <= 0.02:
                continue
            shape = leaflet(x, y, size, angle)
            vein_ = move(shift(x, y) @ turn(angle), ribbon([(0, size * 0.42), (0, -size * 0.3)], 1.3))

            def paint(layer, shape=shape, vein_=vein_, season=season):
                layer.fill(shape, mix(INK, INK_AUTUMN, min(1.0, season * 1.4)))
                layer.fill(inset(shape, FINE), season_colour(season))
                layer.fill(vein_, mix(season_colour(season), VEIN, 0.5))
            c.inside(None, paint, alpha)
        elif kind in ("drop", "drop-on"):
            if kind == "drop":                               # falling: where, how big, how drawn out
                x, y, r, tall = args
                shape = drop(x, y, r, tall)
            else:                                            # sitting on the midrib: how far up it, how big
                v, r = args
                x, y = move(m, blade.points(np.array([0.0]), np.array([v])))[0]
                shape = move(shift(x, y) @ turn(float(np.interp(v, blade.v, blade.angle))), oval(0, -r * 0.55, r * 1.12, r * 0.9))
                y -= r * 0.55
            if r < 1:
                continue
            c.fill(shape, WATER_EDGE)
            c.fill(inset(shape, min(FINE, r * 0.3)), WATER)
            c.fill(oval(x - r * 0.3, y - r * 0.15, r * 0.24, r * 0.34, tilt=20), (255, 255, 255))
        elif kind == "drop-tip":                             # hanging off the tip of the blade: how big
            r, = args
            if r < 1:
                continue
            x, y = move(m, blade.spine[-1:])[0]
            shape = drop(x, y + r * 1.05, r)
            c.fill(shape, WATER_EDGE)
            c.fill(inset(shape, min(FINE, r * 0.3)), WATER)
            c.fill(oval(x - r * 0.3, y + r * 0.95, r * 0.24, r * 0.34, tilt=20), (255, 255, 255))
        elif kind == "gust":                                 # wind: where its head is, how long, which way, how solid
            x, y, length, way, alpha = args
            if alpha <= 0.02:
                continue
            c.inside(None, lambda layer, shape=gust(x, y, length, way): layer.fill(shape, WIND), alpha)
        elif kind == "ladybird":                             # in the air
            draw_ladybird(c, *args)
        elif kind == "ladybird-on":                          # walking on the blade: how far out and up it, heading, size
            u, v, heading, size = args
            x, y = move(m, blade.points(np.array([u]), np.array([v])))[0]
            draw_ladybird(c, x, y, heading + float(np.interp(v, blade.v, blade.angle)), size)


def render(pose):
    """The pose, drawn."""
    pose = {**DEFAULT, **pose}
    c = Canvas()
    c.ink = mix(INK, INK_AUTUMN, smooth((pose["season"] - 0.15) / 0.55))
    m = whole(pose)
    blade = Blade(pose)
    limb = season_colour(pose["season"], LIMBS)
    foot = mix(limb, c.ink, 0.3)
    draw_tail(c, pose, m, blade, mix(limb, KNOB, 0.25))
    draw_legs(c, pose, m, blade, foot)
    draw_arms(c, pose, m, blade, limb)
    draw_blade(c, pose, m, blade)
    if pose["seated"]:
        draw_seated_feet(c, pose, m, foot)
    draw_fx(c, pose["fx"], m, blade)
    return c.finish()


def smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- movement

ARM_HZ, ARM_DAMPING = 3.6, 0.45         # how fast an arm swings back, and how soon it settles
ARM_PUSH = 0.6                          # how hard the body's movement throws the arms about
BEND_HZ, BEND_DAMPING, BEND_PUSH = 2.4, 0.32, 0.5        # the same for the bow of the blade,
CURL_HZ, CURL_DAMPING, CURL_PUSH = 3.0, 0.30, 0.75       # the curl of its tip,
TAIL_HZ, TAIL_DAMPING, TAIL_PUSH = 3.2, 0.30, 0.9        # and the stalk


def spring(target, push, hz, damping, step, reach):
    """Something on a spring: it follows `target`, is pushed about by `push`, and is run
    round the loop until it comes back to where it started. Never more than `reach` from
    where it is meant to be."""
    omega, out = 2 * math.pi * hz, np.empty(len(target))
    at, speed = target[0], 0.0
    for _ in range(3):
        for i in range(len(target)):
            speed += (-omega * omega * (at - target[i]) - 2 * damping * omega * speed + push[i]) * step
            at += speed * step
            out[i] = at
    return np.clip(out, target - reach, target + reach)


def animate(clip, seconds, fps, step=1 / 500):
    """Samples clip(t) through one turn of the loop, lets the arms swing, the blade bow, its
    tip flop and the stalk bob as the leaf moves, and returns the frames as (pose,
    milliseconds). The breeze never lets the blade keep quite still, so every frame is a
    frame of its own."""
    n = int(round(seconds / step))
    poses = [{**DEFAULT, **clip(i * step), "tick": i * step, "loop": seconds} for i in range(n)]
    blur = np.exp(-0.5 * (np.arange(-24, 25) * step / 0.012) ** 2)
    blur /= blur.sum()

    def pushed(points):
        """How hard each of these places is being pushed, as the clip goes round."""
        a = (np.roll(points, -1, 0) - 2 * points + np.roll(points, 1, 0)) / step ** 2
        return np.stack([np.convolve(np.tile(a[:, k], 3), blur, "same")[n:2 * n] for k in range(a.shape[1])], 1)

    def stands(p):
        return SEAT if p["seated"] else LEGS

    lifts = np.array([p["arms"] for p in poses], np.float64)
    omega = 2 * math.pi * ARM_HZ
    for a, side in enumerate((-1, 1)):
        reach = side * SHOULDER[0] * HALF * profile(SHOULDER[1] / BLADE)
        acc = pushed(np.array([move(whole(p), [(reach * math.cos(math.radians(p["turn"])), -stands(p) - SHOULDER[1])])[0] for p in poses]))
        target = np.radians(lifts[:, a].copy())
        angle, speed = target[0], 0.0
        for _ in range(3):
            for i in range(n):
                lifting = (side * math.cos(angle), -math.sin(angle))
                push = -(acc[i, 0] * lifting[0] + acc[i, 1] * lifting[1]) / ARM * ARM_PUSH
                speed += (-omega * omega * (angle - target[i]) - 2 * ARM_DAMPING * omega * speed + push) * step
                angle += speed * step
                lifts[i, a] = math.degrees(angle)

    # The blade is left behind by its own middle: sideways it bows, and up and down its
    # tip flops. The stalk bobs with the base.
    lean = np.radians([p["lean"] for p in poses])
    across, along = np.stack([np.cos(lean), np.sin(lean)], 1), np.stack([np.sin(lean), -np.cos(lean)], 1)
    facing = np.abs(np.cos(np.radians([p["turn"] for p in poses])))
    middle = pushed(np.array([move(whole(p), [(0.0, -stands(p) - 0.6 * BLADE)])[0] for p in poses]))
    base = pushed(np.array([move(whole(p), [(0.0, -stands(p))])[0] for p in poses]))
    bend = spring(np.array([p["bend"] for p in poses]), -np.sum(middle * across, 1) * BEND_PUSH * facing, BEND_HZ, BEND_DAMPING, step, 45)
    curl = spring(np.array([p["curl"] for p in poses]), np.sum(middle * along, 1) * CURL_PUSH, CURL_HZ, CURL_DAMPING, step, 50)
    tail = spring(np.array([p["tail"] for p in poses]), np.sum(base * along, 1) * TAIL_PUSH, TAIL_HZ, TAIL_DAMPING, step, 40)

    every = int(round(1 / fps / step))
    assert abs(every * step - 1 / fps) < 1e-9, "the frame rate has to divide the sampling rate, or the loop drifts"
    frames, ms = [], round(1000 / fps)
    for i in range(0, n, every):
        frames.append(({**poses[i], "arms": (round(float(lifts[i, 0]), 1), round(float(lifts[i, 1]), 1)),
                        "bend": round(float(bend[i]), 1), "curl": round(float(curl[i]), 1), "tail": round(float(tail[i]), 1)}, ms))
    return frames


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
TOP = -(LEGS + BLADE)                     # how high the tip is, standing


def gusts(t, start, length, way=1, rows=((-232, 0.0), (-150, 0.14), (-78, 0.05)), across=(-150.0, 200.0), long=80.0):
    """Streaks of wind blowing past, one for each (height, how late it is). `across` is where
    the head of each starts and ends, for wind blowing right, and `long` how long they are."""
    out = []
    for y, late in rows:
        u = (t - start - late) / length
        if 0 < u < 1:
            out.append(("gust", round(way * (across[0] + (across[1] - across[0]) * u), 1), round(y + 8 * math.sin(2 * math.pi * u), 1), long, way,
                        round(0.85 * math.sin(math.pi * u) ** 0.7, 2)))
    return tuple(out)


def burst(t, start, length, centre, spread, count=8, size=12.0, seed=0.0):
    """A burst of sparkles thrown out from a point, growing and fading."""
    u = (t - start) / length
    if not 0 <= u <= 1:
        return ()
    out = []
    for i in range(count):
        a = 2 * math.pi * (i / count) + seed
        r = spread * (0.3 + 0.7 * u ** 0.55) * (0.8 + 0.2 * math.sin(3.1 * i + seed))
        s = size * math.sin(math.pi * min(1.0, u * 1.25)) * (0.7 + 0.3 * math.cos(2.3 * i))
        out.append(("spark", round(centre[0] + r * math.cos(a), 1), round(centre[1] + r * math.sin(a) + 30 * u * u, 1),
                    round(s, 1), round(30 * u + 15 * i)))
    return tuple(out)


def shed(t, start, length, centre, spread, count, season, size=24.0, seed=0.0):
    """Little leaves flung out from a point, tumbling, and sinking as they fade."""
    u = (t - start) / length
    if not 0 <= u <= 1:
        return ()
    out = []
    for i in range(count):
        a = 2 * math.pi * (i / count) + seed
        r = spread * (0.5 + 0.5 * u ** 0.6) * (0.8 + 0.2 * math.sin(2.3 * i + seed))
        # They come to rest on the floor, and do not sink through it.
        out.append(("leaflet", round(centre[0] + r * math.cos(a), 1), round(min(centre[1] + r * math.sin(a) * 0.8 + 70 * u * u, -8.0), 1),
                    round(size * (0.8 + 0.2 * math.cos(1.7 * i)), 1), round(math.degrees(a) + 90 + 300 * u * (1 if i % 2 else -1)),
                    season[i % len(season)] if isinstance(season, (tuple, list)) else season, round(1 - u ** 2.5, 2)))
    return tuple(out)


# ---------------------------------------------------------------- the clips

def idle(t):
    """Stands about, stirring in the breeze: blinks, glances to one side, and is caught by a
    gust that bows it right over, which it rather enjoys."""
    eyes = blink(t, 1.3) or blink(t, 5.35) or OPEN
    glance = bump(t, 1.8, 0.3, 0.8, 0.3)
    blown = bump(t, 3.22, 0.2, 0.28, 0.55)
    glad = bump(t, 4.15, 0.15, 0.45, 0.3)
    if blown > 0.35:
        eyes = SQUINT
    elif glad > 0.4:
        eyes = HAPPY
    wag = math.sin(2 * math.pi * 4 * t)
    return dict(eyes=eyes, mouth="wobble" if blown > 0.35 else ("grin" if glad > 0.4 else "smile"),
                look=(round(7 * glance, 1), 0.0), bend=24 * blown, curl=TIP + 16 * blown, lean=1.2 * glance + 3.5 * blown,
                tail=-20 * blown + 12 * glad * wag, arms=(30 + 45 * blown + 28 * glad, 30 + 45 * blown + 28 * glad),
                fx=gusts(t, 2.95, 1.05, across=(-100.0, 152.0), long=56.0))


def walk(t):
    """A waddle on stubby legs: rocks from foot to foot, lifting the free one, arms swinging
    the other way, the blade bowing back and the stalk bobbing behind."""
    u = 2 * math.pi * t / 0.5
    side = math.sin(u)
    left, right = max(0.0, side), max(0.0, -side)
    return dict(look=(6.0, 0.0), lean=1.5 + 4.0 * side, dy=-5.0 * abs(side), dx=2.0 * side,
                squash=0.025 * math.cos(u) ** 2, bend=-8.0, curl=TIP - 2, breeze=0.4,
                legs=((4 * left, 12 * left ** 0.8), (4 * right, 12 * right ** 0.8)),
                arms=(30 + 16 * side, 30 - 16 * side))


def rustle(t):
    """Shown during every built-in dance move, which adds its own body motion on top: both
    arms up and waving, a big grin, the blade swishing from side to side, and a little leaf
    flicked off its tip on every beat."""
    u = 2 * math.pi * t / 1.0
    beat, odd = (t % 0.5) / 0.5, t % 1.0 >= 0.5
    kick = math.exp(-beat * 5)
    way = -1 if odd else 1
    fleck = ("leaflet", round(way * (26 + 74 * beat ** 0.7), 1), round(TOP - 6 - 56 * math.sin(math.pi * min(1.0, beat * 0.9)) ** 0.8, 1),
             round(30 * (1 - 0.25 * beat), 1), round(way * (40 + 260 * beat)), 0.0, round(1 - beat ** 2.2, 2))
    return dict(eyes=HAPPY, mouth="grin", arms=(132 + 24 * math.sin(u), 132 - 24 * math.sin(u)),
                bend=13 * math.sin(u), curl=TIP + 8 * kick, tail=-16 * kick, breeze=0.5, fx=(fleck,))


def whirl(t):
    """Eight beats. The wind gets up and Aspen crouches, then lets it take it: up it goes,
    spinning round twice like a leaf off a tree, showing its pale back, and then it drifts
    down the way leaves do, swinging from side to side, to land with a bounce."""
    up, down, landed = 0.45, 1.35, 3.5
    fx = gusts(t, 0.0, 0.7, 1, ((-34, 0.0),)) + gusts(t, 0.12, 0.7, -1, ((-70, 0.0),))
    if t < up:                                           # gathers itself
        g = ease(t, 0, 0.38)
        return dict(eyes=SQUINT if g > 0.5 else OPEN, mouth="flat", squash=0.13 * g, curl=TIP + 8 * g,
                    arms=(30 - 18 * g, 30 - 18 * g), tail=-12 * g, fx=fx)
    swing = math.sin(2 * math.pi * (t - 1.45) / 1.6) * ease(t, 1.45, 1.6) * (1 - ease(t, 2.7, landed))
    if t < landed:
        if t < down:
            height = 172 * (1 - (1 - (t - up) / (down - up)) ** 2.2)
        else:
            height = 172 * (1 - ((t - down) / (landed - down)) ** 1.2) + 12 * swing * swing
        spin = 720 * (1 - (1 - min(1.0, (t - up) / 1.15)) ** 2.4)
        spinning = t < up + 1.15
        # A couple of leaves the wind has picked up with it, going round.
        for k in range(3):
            a = 2 * math.pi * (1.4 * (t - up) + k / 3)
            fade = ease(t, up, up + 0.25) * (1 - ease(t, 1.5, 2.0)) * smooth((abs(math.cos(a)) - 0.62) / 0.2)
            fx += (("leaflet", round(150 * math.cos(a), 1), round(-height - 150 + 46 * math.sin(a) + 30 * k, 1), 26.0,
                    round(math.degrees(a) * 1.5), 0.0, round(fade, 2)),)
        return dict(eyes=WIDE if spinning else HAPPY, mouth="o" if spinning else "open",
                    turn=spin if spinning else 0.0, dy=-height, dx=74 * swing, lean=-20 * swing,
                    squash=-0.08 * (1 - ease(t, up, up + 0.3)), arms=(104, 104), legs=((9, 6), (9, 6)),
                    curl=TIP - 6, tail=-10, fx=fx)
    u = (t - landed) / (4.0 - landed)                    # lands
    bounce = 0.13 * math.sin(math.pi * 2.5 * u) * (1 - u) ** 1.5
    return dict(eyes=HAPPY if u < 0.6 else OPEN, mouth="grin" if u < 0.6 else "smile", squash=bounce,
                arms=(104 - 74 * ease(u, 0.1, 0.8), 104 - 74 * ease(u, 0.1, 0.8)), fx=fx)


def autumn(t):
    """Eight beats. A cold gust makes Aspen shiver, and it turns: gold creeps in from its edge
    and its tip, then orange, then red, while it watches itself go. It shows off its autumn
    colours with two hops in a shower of falling leaves, then shakes itself and is green
    again, the red flying off it in a ring of little leaves."""
    fx = gusts(t, 0.0, 0.62, -1, ((-212, 0.0), (-120, 0.08)))
    chill = bump(t, 0.06, 0.12, 0.3, 0.2)
    season = ease(t, 0.5, 1.85) - ease(t, 3.46, 3.62)
    pose = dict(season=round(season, 3), dx=2.4 * math.sin(2 * math.pi * 16 * t) * chill)
    if t < 0.5:                                          # brr
        pose.update(eyes=SQUINT if chill > 0.3 else OPEN, mouth="wobble" if chill > 0.3 else "smile", arms=(30 - 16 * chill, 30 - 16 * chill),
                    squash=0.04 * chill, bend=-10 * chill)
    elif t < 1.9:                                        # watches itself turn
        u = (t - 0.5) / 1.4
        pose.update(eyes=WIDE, mouth="o", look=(round(7 * math.sin(2 * math.pi * u), 1), round(-3 + 5 * u, 1)),
                    arms=(30 + 50 * ease(u, 0.0, 0.4), 30 + 50 * ease(u, 0.0, 0.4)), elbow=(-25 * ease(u, 0, 0.4),) * 2)
    elif t < 3.0:                                        # ta-da
        beat = ((t - 2.0) % 0.5) / 0.5 if t >= 2.0 else 1.0
        hop = math.sin(math.pi * min(beat / 0.7, 1.0))
        pose.update(eyes=HAPPY, mouth="grin", arms=(140, 140), dy=-24 * hop, squash=0.07 * (1 - hop) * (beat > 0.7) - 0.05 * hop,
                    legs=((6 * hop, 5 * hop), (6 * hop, 5 * hop)), tail=-14)
    elif t < 3.46:                                       # shakes itself
        g = ease(t, 3.0, 3.2)
        pose.update(eyes=SQUINT, mouth="flat", squash=0.12 * g, lean=7 * math.sin(2 * math.pi * 9 * (t - 3.0)) * g,
                    arms=(140 - 110 * g, 140 - 110 * g))
    else:                                                # and is green again
        u = (t - 3.46) / 0.54
        pose.update(eyes=WIDE if u < 0.35 else HAPPY, mouth="open" if u < 0.7 else "smile",
                    squash=-0.1 * math.sin(math.pi * min(1.0, u * 2.2)) + 0.06 * math.sin(math.pi * 3 * u) * (1 - u) ** 2 * (u > 0.45),
                    dy=-18 * math.sin(math.pi * min(1.0, u * 2.2)), arms=(30 + 110 * math.sin(math.pi * min(1.0, u * 1.25)) ** 0.7,) * 2)
    # The leaves that come down while it shows off: each drifts from side to side as it falls.
    for k in range(7):
        begins = 1.75 + 0.16 * k
        u = (t - begins) / 1.5
        if 0 < u < 1:
            x0 = (-196, 150, -120, 200, -60, 96, -168)[k]
            fx += (("leaflet", round(x0 + 26 * math.sin(2 * math.pi * 1.3 * u + k), 1), round(-470 + 452 * u ** 1.1, 1), 30.0,
                    round(40 * math.sin(2 * math.pi * 1.3 * u + k + 1.2) + 50 * k), (1.0, 0.72, 0.5, 0.9, 0.62, 1.0, 0.45)[k],
                    round(min(1.0, 6 * u) * (1 - ease(u, 0.8, 1.0)), 2)),)
    fx += shed(t, 3.5, 0.5, (0, TOP + 150), 215, 9, (1.0, 0.72, 0.9, 0.5), size=28.0, seed=0.3)
    fx += burst(t, 3.48, 0.5, (0, TOP + 150), 150, count=7, size=13, seed=1.0)
    pose["fx"] = fx
    return pose


def raindrops(t):
    """Eight beats. It starts to rain. Three drops land on the tip of the leaf, plink, plink,
    plink, each bobbing it, and then a great big one that sits there and bows the whole blade
    over. Aspen wobbles under it, takes aim, and flicks it off into the air."""
    tip_x, tip_y = REST_TIP
    fx, pose = (), dict(look=(0.0, -5.0), mouth="o", eyes=OPEN)
    dip = 0.0
    for lands, r in ((0.5, 10.0), (1.0, 10.0), (1.5, 10.0), (2.0, 16.0)):
        u = (t - lands + 0.42) / 0.42                    # falling
        if 0 <= u < 1:
            fx += (("drop", round(tip_x, 1), round(-480 + (tip_y - r - 4 + 480) * u ** 1.6, 1), r, 1.25),)
        since = t - lands
        if since >= 0 and r < 12:                        # plink
            dip += math.exp(-since * 6.5)
            if since < 0.14:
                pose["eyes"] = CLOSED
            for k in range(4):                           # and what splashes off
                v = since / 0.38
                if v < 1:
                    a = math.radians((-150, -115, -65, -30)[k])
                    fx += (("drop", round(tip_x + 62 * v * math.cos(a), 1), round(tip_y - 8 + 62 * v * math.sin(a) + 52 * v * v, 1),
                            round(4.6 * (1 - 0.5 * v), 1), 1.0),)
    pose.update(curl=TIP + 34 * dip, squash=0.07 * dip, tail=12 * dip)
    if 0.64 < t < 0.95 or 1.14 < t < 1.45:
        pose.update(eyes=HAPPY, mouth="open")
    carrying, wind_up, flick = 2.0, 2.84, 3.04
    if carrying <= t < flick:                            # the big one
        g = ease(t, carrying, carrying + 0.22)
        aim = ease(t, wind_up, flick)
        wobble = math.sin(2 * math.pi * 2.5 * (t - carrying)) * (1 - aim)
        pose.update(eyes=SQUINT if aim > 0.3 else WIDE, mouth="flat" if aim > 0.3 else "wobble", look=(4.0, -6.0),
                    bend=(32 + 4 * wobble) * g + 12 * aim, curl=TIP + 30 * g + 8 * aim, lean=3 * g + 1.5 * wobble * g,
                    squash=0.04 * g + 0.07 * aim, arms=(30 + 55 * g + 8 * wobble, 30 + 55 * g - 8 * wobble),
                    tail=-10 * g, fx=fx + (("drop-on", BLADE - 26.0, 16.0),))
        return pose
    if t >= flick:                                       # flicks it off
        u = (t - flick) / (4.0 - flick)
        pose.update(eyes=HAPPY if 0.12 < u < 0.8 else OPEN, mouth="grin" if 0.12 < u < 0.8 else "smile", look=(0.0, 0.0),
                    bend=-34 * (1 - ease(u, 0.0, 0.3)) * ease(u, 0.0, 0.06), curl=TIP,
                    arms=(30 + 100 * math.sin(math.pi * u) ** 0.6, 30 + 100 * math.sin(math.pi * u) ** 0.6),
                    squash=-0.05 * math.sin(math.pi * min(1.0, u * 3)))
        fly = (t - flick - 0.06) / 0.38                  # the drop, up and away, and bursting
        if 0 <= fly < 1:
            fx += (("drop", round(80 - 190 * fly, 1), round(-272 - 300 * fly + 200 * fly * fly, 1), round(16 - 3 * fly, 1), 1.0),)
        apex = (-110.0, -372.0)
        spray = (t - flick - 0.44) / 0.48
        if 0 <= spray < 1:
            for k in range(8):
                a = 2 * math.pi * k / 8 + 0.3
                fx += (("drop", round(apex[0] + 78 * spray ** 0.7 * math.cos(a), 1),
                        round(apex[1] + 78 * spray ** 0.7 * math.sin(a) + 90 * spray * spray, 1), round(5.5 * (1 - 0.6 * spray), 1), 1.0),)
        fx += burst(t, flick + 0.44, 0.45, apex, 60, count=5, size=12, seed=0.8)
    pose["fx"] = fx
    return pose


def carried(t):
    """Picked up: eyes wide, a little "o", arms flailing, legs pedalling, the blade flapping."""
    u = 2 * math.pi * t / 0.4
    return dict(eyes=WIDE, mouth="o", squash=-0.04, lean=1.5 * math.sin(u), bend=12 * math.sin(u), curl=TIP + 8,
                tail=16 * math.sin(u + 1.0), breeze=0.3, arms=(100 + 30 * math.sin(u), 100 - 30 * math.sin(u)),
                legs=((6 + 8 * math.sin(u + 1.0), 4 + 4 * math.sin(u + 1.0)), (6 - 8 * math.sin(u + 1.0), 4 - 4 * math.sin(u + 1.0))))


def falling(t):
    """Dropped: arms up, legs trailing, mouth open in alarm, the tip and the stalk streaming up
    behind and fluttering."""
    u = 2 * math.pi * t / 0.24
    return dict(eyes=WIDE, mouth="open", squash=-0.06, bend=7 * math.sin(u), curl=-10 + 8 * math.sin(u + 1.2), tail=-44 + 8 * math.sin(u),
                breeze=0.0, arms=(140 + 8 * math.sin(u), 140 + 8 * math.sin(u + 1.6)),
                legs=((10 + 4 * math.sin(u), 6), (10 + 4 * math.sin(u + 2.0), 6)))


SITTING = dict(seated=True, arms=(38.0, 38.0))


def sitting(t):
    """Sat down with its feet out in front. A ladybird climbs up the edge of the leaf while
    Aspen watches it, opens its wings at the top and flies off; Aspen waggles its feet."""
    eyes = blink(t, 0.5) or blink(t, 5.5) or OPEN
    waggle = 9 * math.sin(2 * math.pi * (t - 4.6) / 0.45) * bump(t, 4.6, 0.12, 0.66, 0.12)
    look, mouth, fx = (0.0, 0.0), "smile", ()
    climbs, leaves, gone = 0.8, 3.5, 4.5
    if climbs <= t < leaves:
        u = (t - climbs) / (leaves - climbs)
        v = 34 + 150 * u
        out = 0.7 * HALF * float(profile(v / BLADE))
        ahead = 0.7 * HALF * float(profile((v + 4) / BLADE))
        fx = (("ladybird-on", round(out, 1), round(v, 1), round(math.degrees(math.atan2(ahead - out, 4.0)) + 5 * math.sin(2 * math.pi * 5 * t)), 12.0),)
        look, mouth = (round(7 * ease(u, 0.0, 0.2), 1), round(4 - 9 * u, 1)), "o" if u > 0.15 else "smile"
    elif leaves <= t < gone:
        u = (t - leaves) / (gone - leaves)
        fx = (("ladybird", round(SIT_PERCH[0] + (205 - SIT_PERCH[0]) * u ** 1.3, 1),
               round(SIT_PERCH[1] - 150 * u + 12 * math.sin(2 * math.pi * 3 * u), 1), 38.0, round(12.0 * (1 - 0.75 * ease(u, 0.3, 1.0)), 1),
               46.0 + 12 * math.sin(2 * math.pi * 10 * t)),)
        look, mouth = (round(7 + 2 * u, 1), round(-5 - 3 * u, 1)), "open"
        eyes = WIDE if u < 0.5 else eyes
    elif gone <= t < gone + 0.9:
        eyes, mouth = HAPPY, "grin"
    return dict(SITTING, eyes=eyes, look=look, mouth=mouth, legs=((round(waggle, 1), 0.0), (round(-waggle, 1), 0.0)), fx=fx)


SLEEPING = dict(SITTING, eyes=CLOSED, bend=22.0, curl=104.0, lean=2.0, arms=(30.0, 30.0), look=(0.0, 3.0), tail=12.0, breeze=0.35)


def asleep(t):
    """Dozing where it sits, eyes shut, its tip drooped right over, with a drop of dew
    swelling on the end of it until it falls. The app adds the breathing and the Zs."""
    fx = ()
    if t < 2.7:
        fx = (("drop-tip", round(9.0 * ease(t, 0.3, 2.5) ** 0.7, 1)),)
    elif t < 3.3:
        u = (t - 2.7) / 0.6
        fx = (("drop", round(SLEEP_TIP[0], 1), round(SLEEP_TIP[1] + 9 + (-SLEEP_TIP[1] - 21) * u ** 1.8, 1), 9.0, 1.0 + 0.3 * u),)
    elif t < 3.6:
        u = (t - 3.3) / 0.3
        fx = tuple(("drop", round(SLEEP_TIP[0] + way * 20 * u, 1), round(-8 - 22 * u + 26 * u * u, 1), round(4.0 * (1 - 0.6 * u), 1), 1.0)
                   for way in (-1, 1))
    return dict(SLEEPING, mouth="o" if math.sin(2 * math.pi * t / 4.0) > 0.3 else "smile", fx=fx)


def tip_of(pose):
    """Where the tip of the blade is in a pose, with no breeze."""
    return tuple(float(x) for x in move(whole({**DEFAULT, **pose}), Blade({**DEFAULT, **pose, "breeze": 0.0}).spine[-1:])[0])


REST_TIP = tip_of({})
SLEEP_TIP = tip_of(SLEEPING)
SIT_PERCH = tuple(float(x) for x in Blade({**DEFAULT, **SITTING, "breeze": 0.0}).points(
    np.array([0.7 * HALF * float(profile(184 / BLADE))]), np.array([184.0]))[0])

CLIPS = {
    # key: file, name in the Dance move menu, the clip, its length, frames a second (one that
    # divides 500, the rate the clips are sampled at, so a loop is exactly as long as it should be)
    "idle": ("idle.webp", None, idle, 6.0, 10),
    "walk": ("walk.webp", None, walk, 0.5, 20),
    "sit": ("sit.webp", None, sitting, 6.0, 10),
    "sleep": ("sleep.webp", None, asleep, 4.0, 10),
    "dance": ("dance.webp", "Rustle", rustle, 1.0, 20),
    "dance_whirl": ("dance_whirl.webp", "Whirl", whirl, 4.0, 20),
    "dance_autumn": ("dance_autumn.webp", "Autumn", autumn, 4.0, 20),
    "dance_raindrops": ("dance_raindrops.webp", "Raindrops", raindrops, 4.0, 20),
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
    manifest = {"name": "Aspen", "height": 150, "facing": "right", "removeBackground": False, "clips": {}}
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
            # The app makes the idle clip, at its tallest, `height` pixels high. A gust of
            # wind passes above where the leaf stands, so allow for it.
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
