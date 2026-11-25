#!/usr/bin/env python3
"""Draws Kori, the ice cube, and builds every animation in the pack.

    python3 make_frames.py            # writes the clips and character.json into the pack
    python3 make_frames.py --sheet    # also saves sheet.png, every frame on one page

Nothing here starts from a picture. Kori is a cube of ice drawn by this script: a box with
rounded edges, seen from a little above, so the top shows as well as the front, with two
bead eyes, pink cheeks, a mouth, stubby arms and legs, and the glints, cracks and trapped
bubbles that make it ice. Because it is a real box turned in three dimensions, it can turn
round on the spot and every face is lit by where it is pointing. And because every point
of it is drawn fresh for each frame, it can also melt: the cube sinks and spreads into a
puddle, and freezes back up again.

Each clip is a small function of time that returns a pose. The arms are not posed by
hand beyond that: a spring carries them, pushed about by how the shoulders move, so they
lag behind a hop and flop when Kori lands.

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
# Positions are in units. x = 0 runs up Kori's middle and y = 0 is the floor, with y
# growing downwards as it does on screen. Standing, Kori is about 280 units tall.

OUT = 1.1                                # saved pixels per unit
SS = 4                                   # drawn this many times larger and averaged down, for smooth edges
X0, Y0, X1, Y1 = -260, -400, 260, 40     # the canvas: room to turn, hop, wave, melt and spread a puddle
W, H = round((X1 - X0) * OUT), round((Y1 - Y0) * OUT)

# The cube. It is S either side of its middle, front to back and side to side, and 2 * HH
# tall, standing LEGS above the floor. It is seen from PITCH degrees above, and turned
# YAW degrees when it stands facing us, so a little of one side shows. Sat down, its
# bottom is SEAT above the floor, which puts its front edge on the floor line.
S, HH = 92.0, 90.0
LEGS = 34.0
PITCH = 12.0
FEET_Z = 0.5 * S                          # the feet are under the front half, and the floor line runs under them
YAW = -13.0
ROUND = 20.0                              # how far round each corner of the outline is rounded

# The face, on the front of the cube: positions from the middle of the front, in units,
# y down.
EYES = (37.0, -10.0)                      # the right eye; the left is its mirror image
EYE_RX, EYE_RY = 11.5, 14.5
MOUTH = (0.0, 26.0)
CHEEKS = (60.0, 18.0)
CHEEK_RX, CHEEK_RY = 15.0, 8.5

# Arms and legs, from the cube's sides and bottom.
SHOULDER_UP = 0.85                       # how far up the side the arms come out, from the bottom, in HH
ARM, ARM_R, HAND_R = 40.0, 11.5, 14.5    # shoulder to hand, how thick, and the round hand
HIP = 42.0                                # either side of the middle
LEG_W = 19.0                              # half the width of a leg

# ---------------------------------------------------------------- colours

INK = (34, 70, 122)                       # the outline: a deep ice blue rather than black
ICE_LIT = (226, 248, 255)                 # a face of the cube turned to the light
ICE_DARK = (112, 178, 228)                # and one turned away
LIMB = (168, 222, 250)
SHINE = (255, 255, 255)
EYE = (22, 38, 72)
MOUTH_IN = (58, 86, 150)
TONGUE = (250, 140, 170)
CHEEK = (255, 128, 172)
WATER = (120, 196, 245)
FROST = (235, 250, 255)
SPARK_EDGE = (80, 160, 236)                # round a sparkle: blue, which shows on light and dark

LINE = 3.2                                # the edge round each part, in units
FINE = 2.0

LIGHT = np.array([-0.45, 0.75, 0.55])     # where the light comes from: up, to the left, in front
LIGHT = LIGHT / np.linalg.norm(LIGHT)


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


def hull(points):
    """The convex outline round a set of points, anticlockwise on screen."""
    pts = sorted(map(tuple, np.asarray(points, float)))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def star(cx, cy, size, angle=0.0, thin=0.2):
    """A four-pointed sparkle."""
    pts = []
    for i in range(16):
        r = size if i % 4 == 0 else (size * thin if i % 2 == 0 else size * thin * 0.75)
        a = math.radians(angle) + i * math.pi / 8
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return np.array(pts)


def drop(cx, cy, r):
    """A drop of water, pointed at the top and round at the bottom, its middle at (cx, cy)."""
    t = np.linspace(0, 2 * math.pi, 40, endpoint=False)
    return np.stack([cx + r * np.sin(t) * np.sin(t / 2) ** 0.9, cy - r * 1.35 * np.cos(t)], 1)


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


# ---------------------------------------------------------------- the cube in three dimensions
# Model space: x right, y up from the floor, z towards us. The camera looks down at
# PITCH degrees, straight along, with no perspective.

CORNERS = np.array([(x, y, z) for x in (-S, S) for y in (LEGS, LEGS + 2 * HH) for z in (-S, S)], float)
FACES = {
    # name: corner indices round the face, and its outward normal
    "front": ([1, 3, 7, 5], (0, 0, 1)),
    "back": ([0, 4, 6, 2], (0, 0, -1)),
    "left": ([0, 2, 3, 1], (-1, 0, 0)),
    "right": ([4, 5, 7, 6], (1, 0, 0)),
    "top": ([2, 6, 7, 3], (0, 1, 0)),
}


def rotate(points, yaw):
    """Turns model points about the upright axis through the middle of the cube."""
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    p = np.asarray(points, float)
    return np.stack([p[..., 0] * c + p[..., 2] * s, p[..., 1], -p[..., 0] * s + p[..., 2] * c], -1)


def project(points):
    """Model points, already turned, to the screen (before the whole mate is moved)."""
    c, s = math.cos(math.radians(PITCH)), math.sin(math.radians(PITCH))
    p = np.asarray(points, float)
    up = p[..., 1] * c - (p[..., 2] - FEET_Z) * s
    return np.stack([p[..., 0], -up], -1)


VIEW = np.array([0.0, math.sin(math.radians(PITCH)), math.cos(math.radians(PITCH))])


def face_frame(yaw, name="front", legs=LEGS):
    """A move from face-local units (x right, y down, from the middle of a face) to the
    screen. A face of the cube is flat, so under this camera it is just a move."""
    idx, normal = FACES[name]
    corners = CORNERS.copy()
    corners[:, 1] += legs - LEGS
    mid = corners[idx].mean(0)
    if name == "top":
        right, down = np.array([1.0, 0, 0]), np.array([0, 0, 1.0])
    else:
        right, down = np.cross([0, 1.0, 0], normal), np.array([0, -1.0, 0])
    o, rx, dy = project(rotate(np.array([mid, mid + right, mid + down]), yaw))
    return np.array([[rx[0] - o[0], dy[0] - o[0], o[0]], [rx[1] - o[1], dy[1] - o[1], o[1]], [0, 0, 1]])


def shade(normal):
    """How brightly a face pointing this way is lit, 0 to 1."""
    return 0.25 + 0.75 * max(0.0, float(np.dot(normal, LIGHT)))


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

    def gradient(self, points, top, bottom, angle=30.0):
        """A shape filled with colour running from `top` to `bottom`, the way `angle`
        (degrees from straight down, positive leaning right) points."""
        px = self.px(points)
        x0, y0 = np.floor(px.min(0)).astype(int)
        x1, y1 = np.ceil(px.max(0)).astype(int) + 1
        if x1 <= x0 or y1 <= y0:
            return
        mask = Image.new("L", (x1 - x0, y1 - y0), 0)
        self._fill(ImageDraw.Draw(mask), px - (x0, y0), 255)
        yy, xx = np.mgrid[0:y1 - y0, 0:x1 - x0].astype(np.float32)
        a = math.radians(angle)
        d = xx * math.sin(a) + yy * math.cos(a)
        t = (d - d.min()) / max(1e-6, d.max() - d.min())
        rgb = np.array(top, np.float32) + (np.array(bottom, np.float32) - np.array(top, np.float32)) * t[..., None]
        tile = Image.fromarray(np.dstack([rgb, np.full(t.shape, 255, np.float32)]).astype(np.uint8), "RGBA")
        tile.putalpha(mask)
        self.img.alpha_composite(tile, (int(x0), int(y0)))

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

    def finish(self):
        """The drawing at its saved size."""
        # Averaged with each colour weighted by how solid it is, so that the empty space
        # round the edge does not darken it.
        return np.asarray(self.img.convert("RGBa").reduce(SS).convert("RGBA"))


# ---------------------------------------------------------------- the rig

DEFAULT = dict(eyes=("open", "open"),                        # each: "open", "wide", "happy", "closed", "dizzy", or 0..1 for how far shut
               look=(0.0, 0.0),                              # the face moved right and down, in units
               mouth="smile",                                # "smile", "open", "grin", "o", "flat", "chatter", "cat"
               arms=(28.0, 28.0), bend=(0.0, 0.0),           # degrees each arm is lifted from hanging straight down
               legs=((0.0, 0.0), (0.0, 0.0)),                # each leg: degrees swung outwards, units lifted
               seated=False,
               yaw=0.0,                                      # degrees turned round, on top of YAW
               melt=0.0,                                     # 0 a cube; 1 a puddle with a face
               shine=-1.0,                                   # where the glint sweeping across the front has got to; off below -0.9
               drips=(),                                     # each (which bottom corner, -1 or 1, how far through its fall, 0..1)
               puddle=0.0,                                   # how big the puddle under it is, 0..1
               fx=(),                                        # lights and flakes: ("spark", x, y, size, angle), ("flake", ...), ("puff", x, y, r)
               squash=0.0, lean=0.0, dx=0.0, dy=0.0)         # the whole mate; dy < 0 is up


def whole(pose):
    """How the whole mate is squashed, leant and moved, about the point between its feet."""
    return (shift(pose["dx"], pose["dy"]) @ turn(pose["lean"])
            @ stretch(1 + 0.7 * pose["squash"], 1 - pose["squash"]))


SEAT = (S - FEET_Z) * math.tan(math.radians(PITCH))


def legs_height(pose):
    """How far above the floor the bottom of the cube is: on its legs, or sat down.
    Melting, it comes down to the floor."""
    return (SEAT if pose["seated"] else LEGS) * (1 - pose["melt"]) + SEAT * pose["melt"]


def melt_warp(points, m, top):
    """Melting: the cube sinks towards the floor and spreads out at the bottom, more the
    lower down a point is, and its sides bulge. `top` is how high the cube's top is."""
    p = np.asarray(points, float)
    if m <= 0:
        return p
    h = np.clip(-p[..., 1] / max(top, 1e-6), 0, 1)        # 0 at the floor, 1 at the top
    y = p[..., 1] * (1 - 0.8 * m)
    spread = 1 + m * (0.25 + 1.1 * (1 - h) ** 2) + 0.35 * m * np.sin(math.pi * h) ** 2
    x = p[..., 0] * spread
    return np.stack([x, y], -1)


class Kori:
    """One pose of the cube, worked out: where everything goes on the screen."""

    def __init__(self, pose):
        self.pose = pose = {**DEFAULT, **pose}
        self.yaw = YAW + pose["yaw"]
        self.legs = legs_height(pose)
        corners = CORNERS.copy()
        corners[:, 1] += self.legs - LEGS
        self.corners3 = rotate(corners, self.yaw)
        self.corners = project(self.corners3)
        self.top = -self.corners[:, 1].min()
        self.m = whole(pose)

    def to_screen(self, points):
        """Points on the upright, unmelted cube to where they are drawn."""
        return move(self.m, melt_warp(points, self.pose["melt"], self.top))

    def visible(self):
        out = []
        for name, (idx, normal) in FACES.items():
            n = rotate(np.array(normal, float), self.yaw)
            if float(np.dot(n, VIEW)) > 1e-3:
                out.append((name, idx, n))
        return out

    def outline(self):
        cut = ROUND * (1 + 1.5 * self.pose["melt"])
        return self.to_screen(dense(soften(hull(self.corners), cut), 5.0))

    def face_move(self, name="front"):
        return face_frame(self.yaw, name, self.legs)


def draw_cube(c, k):
    """The cube itself: its outline, each face lit by where it points, white light along
    the edges where two faces meet, and the ice inside: glints, a crack, bubbles."""
    pose = k.pose
    outline = k.outline()
    c.fill(outline, INK)
    inner = inset(outline, LINE)
    faces = k.visible()

    def paint(layer):
        for name, idx, n in faces:
            lit = shade(n)
            colour = mix(ICE_DARK, ICE_LIT, lit)
            top = mix(colour, (255, 255, 255), 0.25)
            bottom = mix(colour, ICE_DARK, 0.25)
            quad = k.to_screen(dense(k.corners[idx], 5.0))
            # A little bigger than the face, so neighbouring faces leave no gap.
            mid = quad.mean(0)
            layer.gradient(mid + (quad - mid) * 1.02, top, bottom, angle=-25)
        # White light along the edges between faces that both show.
        names = {name: idx for name, idx, _ in faces}
        for a, b in (("front", "top"), ("front", "left"), ("front", "right"), ("top", "left"), ("top", "right"),
                     ("back", "top"), ("back", "left"), ("back", "right")):
            if a in names and b in names:
                shared = [i for i in names[a] if i in names[b]]
                if len(shared) == 2:
                    edge = k.to_screen(dense(k.corners[shared], 4.0, closed=False))
                    layer.stroke(edge, 3.2, (250, 254, 255))
        # Ice inside the front: glints, a crack and bubbles, if the front shows.
        if "front" in names:
            front = k.to_screen(dense(k.corners[names["front"]], 5.0))
            fm = k.face_move("front")

            def ice(l2):
                local = lambda pts: k.to_screen(move(fm, pts))
                # The fixed glints: two slanting streaks at the top left.
                for off, w in ((-58, 14), (-34, 6)):
                    l2.fill(local([(off - 30, -HH), (off - 30 + w, -HH), (off + 40 + w, HH * 0.1), (off + 40, HH * 0.1)]),
                            (255, 255, 255))
                # A crack, low on the right.
                crack = [(30, 70), (46, 52), (44, 40), (62, 26), (70, 30)]
                l2.stroke(local(crack), 1.6, (250, 254, 255))
                l2.stroke(local([(46, 52), (58, 58)]), 1.2, (250, 254, 255))
                # Bubbles.
                for bx, by, r in ((-60, 58, 5.0), (-48, 70, 3.2), (-68, 74, 2.4), (66, -62, 3.5)):
                    l2.fill(local(oval(bx, by, r)), (255, 255, 255))
                    l2.fill(local(oval(bx + 0.4, by + 0.6, r * 0.55)), mix(ICE_LIT, ICE_DARK, 0.25))
            layer.inside(front, ice, 0.55)

            # The glint that sweeps across now and then.
            s = pose["shine"]
            if s > -0.9:
                def sweep(l2):
                    x = -S * 1.6 + s * S * 3.2
                    l2.fill(k.to_screen(move(fm, [(x - 34, -HH * 1.2), (x - 8, -HH * 1.2), (x + 52, HH * 1.2), (x + 26, HH * 1.2)])),
                            (255, 255, 255))
                    l2.fill(k.to_screen(move(fm, [(x + 4, -HH * 1.2), (x + 12, -HH * 1.2), (x + 72, HH * 1.2), (x + 64, HH * 1.2)])),
                            (255, 255, 255))
                layer.inside(front, sweep, 0.7)
        # A glint on the top.
        if "top" in names:
            tm = k.face_move("top")
            layer.stroke(k.to_screen(move(tm, [(-50, -30), (-20, -30)])), 4.0, (255, 255, 255))

    c.inside(inner, paint)
    # A frosted rim just inside the outline.
    c.inside(None, lambda layer: layer.stroke(np.vstack([inset(outline, LINE + 2.2), inset(outline, LINE + 2.2)[:1]]), 2.0,
                                              (255, 255, 255)), 0.45)


def draw_face(c, k):
    """Eyes, cheeks and mouth on the front of the cube, turned with it."""
    pose = k.pose
    names = [name for name, _, _ in k.visible()]
    if "front" not in names:
        return
    fm = k.face_move("front") @ shift(*pose["look"])
    front = k.to_screen(dense(k.corners[FACES["front"][0]], 5.0))
    # Squashed by melting, the face would squash too; keep it its own shape, a little lower.
    m = pose["melt"]
    # Melting squashes the cube flat; the features only shrink a little and slide down.
    keep = shift(0, 10 * m) @ stretch(1 + 0.2 * m, (1 - 0.45 * m) / (1 - 0.8 * m))

    def local(pts):
        return k.to_screen(move(fm @ keep, pts))

    def face(layer):
        for side in (-1, 1):
            layer.fill(local(oval(side * CHEEKS[0], CHEEKS[1], CHEEK_RX, CHEEK_RY)), CHEEK)
    c.inside(inset(front if m < 0.3 else k.outline(), LINE), face, 0.6)

    def features(layer):
        for side, state in zip((-1, 1), pose["eyes"]):
            draw_eye(layer, local, side * EYES[0], EYES[1], state)
        draw_mouth(layer, local, pose["mouth"])
    c.inside(None, features)


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
    if mouth == "chatter":                                  # teeth chattering: a zigzag
        pts = [(cx + u * 15, cy + 3 + (2.6 if i % 2 else -2.6)) for i, u in enumerate(np.linspace(-1, 1, 7))]
        c.fill(local(ribbon(dense(pts, 1.0, closed=False), 2.6)), INK)
        return
    if mouth == "o":
        lip = oval(cx, cy + 6, 6.5, 8.0)
        c.fill(local(lip), INK)
        c.fill(local(oval(cx, cy + 6, 4.2, 5.6)), MOUTH_IN)
        return
    # Open: a D, flat along the top, with a tongue; "grin" is wider.
    hw, depth = (14.0, 16.0) if mouth == "open" else (19.0, 19.0)
    top = [(cx + u * hw, cy - 1 + 1.5 * (1 - u * u)) for u in us]
    bottom = [(cx + u * hw * 0.98, cy - 1 + depth * (1 - u * u) ** 0.65) for u in us[::-1]]
    lip = np.array(top + bottom[1:-1])
    c.fill(local(lip), INK)
    inner = inset(lip, 1.8)
    c.fill(local(inner), MOUTH_IN)
    c.fill(local(oval(cx + 1, cy + depth * 0.68, hw * 0.55, depth * 0.28)), TONGUE)
    c.fill(local(ribbon(dense([(cx - hw * 0.92, cy - 0.5), (cx + hw * 0.92, cy - 0.5)], 1.0, closed=False), 2.4)), INK)


def shoulder(k, side):
    """Where an arm comes out of the middle of a side of the cube, on the screen before
    melting and moving."""
    p = np.array([side * S, k.legs + 2 * HH * SHOULDER_UP * 0.55, 0.0])
    return project(rotate(p, k.yaw))


def arm_line(k, side, lift, bend, length):
    """The middle line of an arm, from the shoulder to the hand, and how far towards us its
    hand is. Lifted `lift` degrees from hanging straight down, out from its side of the
    cube, so when that side turns towards us the arm points at us and looks shorter."""
    n = 12
    theta = np.radians(lift + bend * np.linspace(0, 1, n))
    heading = rotate(np.stack([side * np.sin(theta), -np.cos(theta), np.zeros(n)], 1), k.yaw)
    c, s_ = math.cos(math.radians(PITCH)), math.sin(math.radians(PITCH))
    screen = np.stack([heading[:, 0], -(heading[:, 1] * c - heading[:, 2] * s_)], 1)
    steps = (screen[:-1] + screen[1:]) / 2 * length / (n - 1)
    line = shoulder(k, side) + np.concatenate([[(0.0, 0.0)], np.cumsum(steps, 0)])
    root = rotate(np.array([side * S, 0.0, 0.0]), k.yaw)[2]
    return line, root + float(heading[:, 2].mean()) * length


def arm_shapes(line):
    """A stubby tube along the line, with a round hand at its end."""
    along = np.gradient(line, axis=0)
    norm = np.hypot(along[:, 0], along[:, 1])
    shapes = [oval(*line[0], ARM_R)]
    if norm.max() > 1e-6:
        along = along / np.maximum(norm, 1e-6)[:, None]
        across = np.stack([-along[:, 1], along[:, 0]], 1)
        shapes.append(np.concatenate([line + across * ARM_R, (line - across * ARM_R)[::-1]]))
    shapes.append(oval(*line[-1], HAND_R))
    return shapes


def draw_arm(c, k, line):
    # The melt carries the shoulder along with the cube, but the arm keeps its own shape.
    root = melt_warp(line[:1], k.pose["melt"], k.top)[0] - line[0]
    c.part([move(k.m, s + root) for s in arm_shapes(line)], LIMB)


def draw_legs(c, k):
    pose = k.pose
    if pose["seated"] or pose["melt"] > 0.6:
        return
    for side, (swing, lift) in zip((-1, 1), pose["legs"]):
        hip3 = rotate(np.array([side * HIP, k.legs + 14, FEET_Z]), k.yaw)
        hip = project(hip3)
        length = max((k.legs + 14) * math.cos(math.radians(PITCH)) - lift, 8)
        shape = soften([(-LEG_W, -4), (LEG_W, -4), (LEG_W + 2, length), (-LEG_W - 2, length)], [0, 0, 15, 15])
        place = shift(hip[0], hip[1]) @ turn(-side * swing)
        c.part([k.to_screen(move(place, shape))], LIMB)


def draw_seated_feet(c, k):
    """Sitting, the feet stick out in front: two round soles at the bottom of the cube."""
    for side, (swing, lift) in zip((-1, 1), k.pose["legs"]):
        p = project(rotate(np.array([side * (HIP + 6), 4.0, S * 0.95]), k.yaw))
        sole = oval(p[0], p[1] - lift - 4, 17, 13, tilt=side * (12 + swing))
        c.part([k.to_screen(sole)], LIMB)
        c.stroke(k.to_screen(oval(p[0], p[1] - lift - 4, 8, 5.5, tilt=side * (12 + swing))), 1.2, mix(LIMB, INK, 0.25))


def draw_puddle(c, k):
    pose = k.pose
    size = max(pose["puddle"], pose["melt"])
    if size <= 0:
        return
    rx = S * (1.05 + 1.15 * size)
    ry = rx * 0.2

    def paint(layer):
        layer.fill(move(whole(dict(pose, lean=0, squash=0, dy=0)), oval(0, -2, rx, ry)), WATER)
        layer.fill(move(whole(dict(pose, lean=0, squash=0, dy=0)), oval(-rx * 0.35, -ry * 0.45 - 2, rx * 0.25, ry * 0.18)),
                   (255, 255, 255))
    c.inside(None, paint, 0.55 + 0.2 * min(size, 1))


def draw_drips(c, k):
    """Drops of meltwater: one swells at a bottom corner, lets go and falls."""
    for side, t in k.pose["drips"]:
        corner = project(rotate(np.array([side * S * 0.82, k.legs + 6, S]), k.yaw))
        corner = k.to_screen(corner[None])[0]
        if t < 0.55:                                      # swelling where it hangs
            r = 2 + 6 * t / 0.55
            p = corner + (0, r * 1.4)
        else:                                             # falling, faster and faster
            f = (t - 0.55) / 0.45
            r = 8
            p = corner + (0, r * 1.4 + (0 - corner[1]) * f * f)
        if t >= 0.98:
            continue
        c.part([drop(p[0], p[1], r)], WATER, line=1.6)
        c.fill(oval(p[0] - r * 0.3, p[1] - r * 0.1, r * 0.22, r * 0.35), (255, 255, 255))


def draw_fx(c, fx):
    for kind, *args in fx:
        if kind == "spark":
            x, y, size, angle = args
            if size < 1:
                continue
            c.fill(star(x, y, size + 2.2, angle, 0.3), SPARK_EDGE)
            c.fill(star(x, y, size, angle, 0.22), (255, 255, 255))
        elif kind == "flake":
            x, y, size, angle = args
            if size < 2:
                continue
            for i in range(3):
                a = math.radians(angle + 60 * i)
                d = np.array([math.cos(a), math.sin(a)]) * size
                c.stroke([(x - d[0], y - d[1]), (x + d[0], y + d[1])], 3.8, INK)
            for i in range(3):
                a = math.radians(angle + 60 * i)
                d = np.array([math.cos(a), math.sin(a)]) * size
                c.stroke([(x - d[0], y - d[1]), (x + d[0], y + d[1])], 1.8, FROST)
        elif kind == "puff":
            x, y, r, alpha = args
            if r < 1 or alpha <= 0.02:
                continue

            def paint(layer, x=x, y=y, r=r):
                for dx_, dy_, rr in ((0, 0, 1.0), (-0.8, 0.25, 0.7), (0.8, 0.2, 0.75), (0.1, -0.55, 0.65)):
                    layer.fill(oval(x + dx_ * r, y + dy_ * r, r * rr * 1.08), INK)
                for dx_, dy_, rr in ((0, 0, 1.0), (-0.8, 0.25, 0.7), (0.8, 0.2, 0.75), (0.1, -0.55, 0.65)):
                    layer.fill(oval(x + dx_ * r, y + dy_ * r, r * rr), FROST)
            c.inside(None, paint, alpha)


def render(pose):
    """The pose, drawn."""
    k = Kori(pose)
    pose = k.pose
    c = Canvas()
    draw_puddle(c, k)
    behind, front = [], []
    for side, lift, bend in ((-1, pose["arms"][0], pose["bend"][0]), (1, pose["arms"][1], pose["bend"][1])):
        if pose["melt"] > 0.5:                            # melted right in
            continue
        line, depth = arm_line(k, side, lift, bend, ARM * (1 - 0.6 * pose["melt"]))
        # An arm on a side that has turned to face us, or pointing nearly straight at us,
        # would lie across the cube like something stuck on, so it goes behind instead.
        # It is only ever like that for a moment, mid-turn.
        reach = np.hypot(*(line[-1] - line[0])) / max(ARM * (1 - 0.6 * pose["melt"]), 1e-6)
        facing_us = rotate(np.array([side, 0.0, 0.0]), k.yaw)[2]
        (front if depth > 0 and reach > 0.55 and facing_us < 0.5 else behind).append(line)
    draw_legs(c, k)
    for line in behind:
        draw_arm(c, k, line)
    draw_cube(c, k)
    draw_face(c, k)
    if pose["seated"] and pose["melt"] < 0.5:
        draw_seated_feet(c, k)
    for line in front:
        draw_arm(c, k, line)
    draw_drips(c, k)
    draw_fx(c, pose["fx"])
    return c.finish()


# ---------------------------------------------------------------- movement

ARM_HZ, ARM_DAMPING = 3.6, 0.45         # how fast an arm swings back, and how soon it settles
ARM_PUSH = 0.6                          # how hard the body's movement throws the arms about


def animate(clip, seconds, fps, calm, step=1 / 500):
    """Samples clip(t) through one turn of the loop, lets the arms swing, and returns the
    frames as (pose, milliseconds). A frame is held for as long as nothing has visibly
    moved; a calm clip waits for a little more movement, so the tail end of a settling arm
    does not cost a frame every time."""
    n = int(round(seconds / step))
    poses = [{**DEFAULT, **clip(i * step)} for i in range(n)]
    lifts = np.array([p["arms"] for p in poses], np.float64)
    omega = 2 * math.pi * ARM_HZ
    blur = np.exp(-0.5 * (np.arange(-24, 25) * step / 0.012) ** 2)
    blur /= blur.sum()
    for a, side in enumerate((-1, 1)):
        root = np.array([move(whole(p), [(side * S, -(LEGS + HH))])[0] for p in poses])
        acc = (np.roll(root, -1, 0) - 2 * root + np.roll(root, 1, 0)) / step ** 2
        acc = np.stack([np.convolve(np.tile(acc[:, k], 3), blur, "same")[n:2 * n] for k in (0, 1)], 1)
        target = np.radians(lifts[:, a].copy())
        angle, speed = target[0], 0.0
        for _ in range(3):
            for i in range(n):
                lifting = (side * math.cos(angle), -math.sin(angle))
                push = -(acc[i, 0] * lifting[0] + acc[i, 1] * lifting[1]) / ARM * ARM_PUSH
                speed += (-omega * omega * (angle - target[i]) - 2 * ARM_DAMPING * omega * speed + push) * step
                angle += speed * step
                lifts[i, a] = math.degrees(angle)

    frames, every, ms, within = [], int(round(1 / fps / step)), round(1000 / fps), 1.2 if calm else 0.25
    for i in range(0, n, every):
        pose = {**poses[i], "arms": (round(float(lifts[i, 0]), 1), round(float(lifts[i, 1]), 1))}
        if frames and same(frames[-1][0], pose, within):
            frames[-1] = (frames[-1][0], frames[-1][1] + ms)
        else:
            frames.append((pose, ms))
    if len(frames) > 1 and same(frames[0][0], frames[-1][0], within):
        frames[0] = (frames[0][0], frames[0][1] + frames.pop()[1])
    return frames


def same(a, b, within):
    """Whether two poses would look the same on screen: nothing more than `within` degrees
    or units apart, and nothing else changed."""
    def flat(p):
        return [*p["arms"], *p["bend"], *p["legs"][0], *p["legs"][1], *(2 * v for v in p["look"]),
                p["squash"] * 150, p["lean"] * 2, p["dx"], p["dy"], p["yaw"] * 2, p["melt"] * 200,
                p["shine"] * 60, p["puddle"] * 100]
    return ((a["eyes"], a["mouth"], a["seated"], a["drips"], a["fx"]) == (b["eyes"], b["mouth"], b["seated"], b["drips"], b["fx"])
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


def q(v, step):
    """Rounded to a step, so that tiny changes do not cost a frame."""
    return round(round(v / step) * step, 3)


OPEN, WIDE, HAPPY, CLOSED, DIZZY, SQUINT = (("open", "open"), ("wide", "wide"), ("happy", "happy"), ("closed", "closed"),
                                            ("dizzy", "dizzy"), ("squint", "squint"))


def sparkles(t, start, length, centre, spread, count=6, size=13.0, seed=0.0):
    """A burst of sparkles thrown out from a point, growing and fading."""
    u = (t - start) / length
    if not 0 <= u <= 1:
        return ()
    out = []
    for i in range(count):
        a = 2 * math.pi * (i / count) + seed
        r = spread * (0.35 + 0.65 * u ** 0.6) * (0.75 + 0.25 * math.sin(3.1 * i + seed))
        s = size * math.sin(math.pi * u) * (0.7 + 0.3 * math.cos(2.3 * i))
        out.append(("spark", q(centre[0] + r * math.cos(a), 0.5), q(centre[1] + r * math.sin(a) * 0.8, 0.5),
                    q(s, 0.5), q(20 * u + 15 * i, 1)))
    return tuple(out)


# ---------------------------------------------------------------- the clips

def idle(t):
    """Stands about: blinks, glances to one side, a glint sweeps across its front, a drop
    of meltwater swells at a corner and falls, and now and then it shivers."""
    eyes = blink(t, 1.2) or blink(t, 3.6) or blink(t, 7.4) or blink(t, 7.7) or OPEN
    glance = bump(t, 4.6, 0.3, 1.4, 0.35)
    shine = -1.0 if not 2.0 <= t <= 2.9 else (t - 2.0) / 0.9
    drip = ((1, q((t - 5.6) / 1.4, 0.02)),) if 5.6 <= t <= 7.0 else ()
    shiver = bump(t, 8.6, 0.06, 0.55, 0.12)
    shake = 3.2 * math.sin(2 * math.pi * 16 * t) * shiver
    mouth = "chatter" if shiver > 0.3 else "smile"
    if shiver > 0.3:
        eyes = SQUINT
    return dict(eyes=eyes, look=(q(8 * glance, 0.5), 0.0), shine=q(shine, 0.02), drips=drip, mouth=mouth,
                dx=q(shake, 0.25), squash=q(0.03 * shiver, 0.005), arms=(28 - 10 * shiver, 28 - 10 * shiver),
                lean=q(1.5 * glance, 0.1))


def walk(t):
    """A waddle on stubby legs: rocks from foot to foot, lifting the free one, arms
    swinging the other way."""
    u = 2 * math.pi * t / 0.5
    side = math.sin(u)
    left, right = max(0.0, side), max(0.0, -side)
    return dict(look=(6.0, 0.0), lean=1.5 + 4.0 * side, dy=-5.0 * abs(side), dx=2.0 * side,
                squash=0.025 * math.cos(u) ** 2,
                legs=((4 * left, 12 * left ** 0.8), (4 * right, 12 * right ** 0.8)),
                arms=(30 + 16 * side, 30 - 16 * side))


def cool_moves(t):
    """Shown during every built-in dance move, which adds its own body motion on top: both
    arms up and waving, a big open grin, and a sparkle off a corner on every beat."""
    u = 2 * math.pi * t / 1.0
    beat = (t % 0.5) / 0.5
    corner = (-S * 0.9 if t % 1.0 < 0.5 else S * 0.9, -(LEGS + 2 * HH) - 10)
    return dict(eyes=HAPPY, mouth="grin", arms=(130 + 25 * math.sin(u), 130 - 25 * math.sin(u)),
                shine=q(-1.0 if beat > 0.6 else beat / 0.6, 0.04),
                fx=sparkles(beat, 0.0, 0.55, corner, 26, count=3, size=12, seed=1.0 if t % 1 < 0.5 else 2.0))


def ice_skate(t):
    """Four beats. It glides off to one side on one foot, arms out like wings, glides back
    the other way, then gathers itself and spins round on the spot in a flurry of
    sparkles, and lands facing us with its arms up."""
    # Beats 1 and 2: glide right, glide left. Beats 3 and 4: the spin, and the finish.
    if t < 1.0:
        g = math.sin(math.pi * t)                      # out and back, over two beats
        way = 1 if t < 0.5 else -1
        glide = 36 * math.sin(2 * math.pi * t)
        lean = -9 * math.sin(2 * math.pi * t)
        legs = ((6, 22 * abs(math.sin(2 * math.pi * t))), (0, 0)) if t < 0.5 else ((0, 0), (6, 22 * abs(math.sin(2 * math.pi * t))))
        return dict(eyes=HAPPY, mouth="open", dx=q(glide, 0.5), lean=q(lean, 0.2), arms=(96, 96),
                    look=(q(8 * math.sin(2 * math.pi * t), 0.5), 0.0), legs=legs,
                    fx=(("flake", q(-glide * 0.9 - way * 40, 1), -6.0, q(8 * g, 0.5), q(60 * t, 1)),) if g > 0.2 else ())
    if t < 1.15:                                          # gather
        u = (t - 1.0) / 0.15
        return dict(eyes=OPEN, mouth="o", squash=q(0.07 * math.sin(math.pi * u), 0.005), arms=(60, 60))
    if t < 1.65:                                          # the spin
        u = (t - 1.15) / 0.5
        spin = 360 * (1 - (1 - u) ** 1.7)
        hop = math.sin(math.pi * u)
        return dict(eyes=HAPPY, mouth="open", yaw=q(spin, 1), dy=q(-18 * hop, 0.5), squash=q(-0.05 * hop, 0.005),
                    arms=(150, 150), legs=((4 * hop, 10 * hop), (4 * hop, 10 * hop)),
                    fx=sparkles(t, 1.2, 0.55, (0, -140), 175, count=8, size=15, seed=0.5))
    u = (t - 1.65) / 0.35                                 # land and pose, arms coming down at the end
    land = math.sin(math.pi * min(u / 0.35, 1))
    arms = 150 - 122 * ease(u, 0.55, 1)
    return dict(eyes=HAPPY, mouth="grin", squash=q(0.08 * land, 0.005), arms=(arms, arms),
                fx=sparkles(t, 1.6, 0.4, (0, -140), 190, count=8, size=12, seed=0.9))


def meltdown(t):
    """Four beats. It starts to sweat, drips, and sinks down into a puddle, spreading out
    and grinning dizzily, then all at once freezes back up into a cube with a sparkle and
    a little bounce."""
    if t < 1.3:                                           # melting
        m = ease(t, 0.15, 1.2)
        wob = 0.03 * math.sin(2 * math.pi * 4 * t) * m
        drips = ((-1, q(min(t / 0.7, 0.99), 0.02)),) if t < 0.7 else ()
        eyes = OPEN if t < 0.35 else (("wide", "wide") if t < 0.6 else DIZZY)
        mouth = "o" if t < 0.6 else "cat"
        return dict(melt=q(m, 0.02), squash=q(wob, 0.004), eyes=eyes, mouth=mouth, drips=drips,
                    arms=(28 + 60 * ease(t, 0.0, 0.3) - 70 * m, 28 + 60 * ease(t, 0.0, 0.3) - 70 * m))
    if t < 1.55:                                          # a puddle, wobbling
        return dict(melt=1.0, eyes=DIZZY, mouth="cat", squash=q(0.03 * math.sin(2 * math.pi * 3 * t), 0.004),
                    arms=(0, 0))
    if t < 1.66:                                          # snap! frozen again, stretched tall
        u = (t - 1.55) / 0.11
        return dict(melt=q(1 - ease(u, 0, 1), 0.02), squash=q(-0.12 * ease(u, 0.3, 1), 0.005), eyes=WIDE, mouth="o",
                    arms=(120, 120), fx=sparkles(t, 1.55, 0.45, (0, -140), 185, count=8, size=17, seed=0.3))
    u = (t - 1.66) / 0.34                                 # settle with a bounce
    bounce = -0.12 * math.cos(math.pi * 2.5 * u) * (1 - u) ** 1.5
    return dict(squash=q(bounce, 0.005), eyes=HAPPY, mouth="grin", arms=(120 - 92 * ease(u, 0.3, 1), 120 - 92 * ease(u, 0.3, 1)),
                fx=sparkles(t, 1.55, 0.45, (0, -140), 185, count=8, size=17, seed=0.3))


def brr(t):
    """Two beats. A shiver from head to foot, teeth chattering, hugging itself, then a
    great sneeze that blows out a puff of frost and a flurry of snowflakes."""
    if t < 0.6:
        shake = 4 * math.sin(2 * math.pi * 18 * t)
        return dict(eyes=SQUINT, mouth="chatter", dx=q(shake, 0.25), squash=0.03, arms=(12, 12), bend=(-20, -20),
                    lean=q(1.2 * math.sin(2 * math.pi * 9 * t), 0.2))
    if t < 0.72:                                          # the breath in
        u = (t - 0.6) / 0.12
        return dict(eyes=("closed", "closed"), mouth="o", squash=q(-0.08 * u, 0.005), lean=q(-5 * u, 0.2), arms=(40, 40))
    u = (t - 0.72) / 0.28                                 # achoo
    snap = math.sin(math.pi * min(u / 0.4, 1))
    puff = ease(u, 0, 0.5)
    gone = ease(u, 0.55, 1)
    fx = (("puff", q(70 + 60 * puff, 1), q(-120 - 10 * puff, 1), q((10 + 26 * puff) * (1 - gone), 1), 0.95),)
    fx += tuple(("flake", q(80 + 110 * puff + 18 * i, 1), q(-150 + 40 * i - 30 * puff + 25 * puff * i, 1),
                 q(9 * (1 - ease(u, 0.6, 1)), 0.5), q(40 * u + 30 * i, 1)) for i in range(3))
    return dict(eyes=SQUINT if u < 0.5 else HAPPY, mouth="grin" if u < 0.5 else "smile", squash=q(0.09 * snap, 0.005),
                lean=q(6 * snap, 0.2), dx=q(4 * snap, 0.5), arms=(60 - 30 * u, 60 - 30 * u), fx=fx)


def carried(t):
    """Picked up: eyes wide, a little "o", arms flailing, legs pedalling, a nervous drip."""
    u = 2 * math.pi * t / 0.4
    return dict(eyes=WIDE, mouth="o", squash=-0.04, lean=1.5 * math.sin(u),
                arms=(100 + 30 * math.sin(u), 100 - 30 * math.sin(u)),
                legs=((6 + 8 * math.sin(u + 1.0), 4 + 4 * math.sin(u + 1.0)), (6 - 8 * math.sin(u + 1.0), 4 - 4 * math.sin(u + 1.0))),
                drips=((-1, 0.5),))


def falling(t):
    """Dropped: arms up, legs trailing, mouth open in alarm."""
    u = 2 * math.pi * t / 0.24
    return dict(eyes=WIDE, mouth="open", squash=-0.06,
                arms=(140 + 8 * math.sin(u), 140 + 8 * math.sin(u + 1.6)),
                legs=((10 + 4 * math.sin(u), 6), (10 + 4 * math.sin(u + 2.0), 6)))


SITTING = dict(seated=True, puddle=0.15, arms=(40.0, 40.0))


def sitting(t):
    """Sat down on a little puddle with its feet out in front. Blinks, waggles its feet,
    and lets a drip fall now and then."""
    eyes = blink(t, 1.4) or blink(t, 4.8) or blink(t, 5.1) or OPEN
    waggle = 9 * math.sin(2 * math.pi * (t - 2.6) / 0.45) * bump(t, 2.6, 0.12, 0.66, 0.12)
    drip = ((-1, q((t - 3.8) / 1.4, 0.02)),) if 3.8 <= t <= 5.2 else ()
    return dict(SITTING, eyes=eyes, legs=((q(waggle, 1), 0.0), (q(-waggle, 1), 0.0)), drips=drip,
                mouth="cat" if 2.6 < t < 3.6 else "smile")


def asleep(t):
    """Dozing where it sits, eyes shut, slowly melting a little into its puddle, with a
    drip every so often. The app adds the breathing and the Zs."""
    sag = 0.5 - 0.5 * math.cos(2 * math.pi * t / 4.0)
    drip = ((1, q(t / 2.0, 0.02)),) if t < 2.0 else ()
    return dict(SITTING, eyes=CLOSED, mouth="o" if sag > 0.5 else "smile", melt=q(0.06 + 0.04 * sag, 0.02), puddle=0.3,
                lean=2.0, arms=(30.0, 30.0), drips=drip, look=(0.0, 3.0))


CLIPS = {
    # key: file, name in the Dance move menu, the clip, its length, frames a second, calm
    "idle": ("idle.webp", None, idle, 10.0, 20, True),
    "walk": ("walk.webp", None, walk, 0.5, 25, False),
    "sit": ("sit.webp", None, sitting, 7.0, 20, True),
    "sleep": ("sleep.webp", None, asleep, 4.0, 10, True),
    "dance": ("dance.webp", "Cool Moves", cool_moves, 1.0, 25, False),
    "dance_ice_skate": ("dance_ice_skate.webp", "Ice Skate", ice_skate, 2.0, 25, False),
    "dance_meltdown": ("dance_meltdown.webp", "Meltdown", meltdown, 2.0, 25, False),
    "dance_brr": ("dance_brr.webp", "Brr!", brr, 1.0, 25, False),
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
    manifest = {"name": "Kori", "height": 140, "facing": "right", "removeBackground": False, "clips": {}}
    standing = render({})[..., 3].any(axis=1).sum()            # how tall the mate is standing still, in saved pixels
    rows, pixels = [], 0
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    old = json.loads((PACK / "character.json").read_text())["clips"] if (PACK / "character.json").exists() else {}
    for key, (file, name, *_) in CLIPS.items():
        if only and key not in only:
            if key in old:
                manifest["clips"][key] = old[key]
            continue
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
            # ever reach above its head, that would shrink it, so allow for it.
            manifest["height"] = round(140 * (images[0].height - 4) / standing)
        rows.append(images)
        pixels += len(images) * images[0].width * images[0].height
        print(f"{file}: {len(images)} frames of {images[0].width}x{images[0].height}, {sum(durations) / 1000:.2f}s, "
              f"{(PACK / file).stat().st_size // 1024} KB")
    print(f"these clips: {sum(len(r) for r in rows)} frames, {pixels * 4 / 2 ** 20:.0f} MB once the app has unpacked them")

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
