#!/usr/bin/env python3
"""Builds Mochi's animations from one cut-out picture.

    python3 make_frames.py            # writes the clips and character.json into the pack
    python3 make_frames.py --sheet    # also saves sheet.png, every frame on one page

cutout.png (made by cut_out.py) is taken apart into a body, two ears and two feet. The
ears and feet sit behind the body. Each stays attached along the line where it joins the
body and bends away from there, like skin, so it can swing without a gap opening; the
ears also curl along their length. The head can tilt and nod on the neck, the whole mate
can squash, stretch, lean and jump, and the face is repainted for blinks, closed, happy
and wide eyes, an open mouth and a blush.

Each clip is a small function of time that returns a pose. The ears are not posed by
hand beyond that: a spring carries them, pushed about by how their roots move, so they
lag, float and flop on their own.

Needs numpy, pillow and opencv-python-headless. This folder starts with "_", so the app
does not load anything from it.
"""
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
PACK = HERE.parent

# ---------------------------------------------------------------- sizes
# Every position below is in pixels of the original photo.

S = 4                                   # the cut-out, and all the drawing, is 4x the photo
OUT = 1.1                               # the saved frames, in multiples of the photo
TOP_PAD = 2                             # rows cut_out.py added above the photo
X0, Y0, X1, Y1 = -60, -114, 440, 326    # the canvas: room for ears, leans and hops
W, H = (X1 - X0) * S, (Y1 - Y0) * S
SS = 2                                  # extra supersampling for drawn lines

# ---------------------------------------------------------------- the shape of the character

# The head and body, with the ears and feet left out. Only the stretches where it runs
# along a join matter; elsewhere it just has to stay clear of the ears and feet.
CORE = [
    (200, -30), (259, -30),
    (259, 12), (262, 18), (265, 25), (268, 33), (270, 40), (273, 50), (276, 60), (278.5, 70),
    (280.2, 77.6),                                              # right ear: crease, down to the notch
    (283.5, 84), (288, 95), (292, 110), (296, 135), (300, 170), (340, 200), (340, 285),
    (290, 340), (272, 340), (262, 300),
    (252.6, 290.6), (241, 291.2), (229.4, 290.4), (228.4, 288.6),   # right foot: just under the crease
    (220, 300), (212, 340), (162, 340), (158, 290),
    (147.6, 276.4), (135, 277.0), (124.4, 276.0), (122.8, 273.8),   # left foot
    (100, 285), (85, 340), (-58, 340), (-58, 70), (120, 50),
    (131.6, 38.4), (137, 32), (140, 28), (143, 24), (146.5, 17.5),  # left ear: notch, crease, notch
    (146.5, -30),
]

# Each part: an outline that takes in the whole part and crosses the character's edge
# exactly where CORE does, and the point it turns about. A part is not a stiff board
# hinged there: it stays attached along its join and bends away from it over `soft`
# pixels, like skin, so no gap can open. The right ear only touches the head lower down,
# so beyond `free` pixels from its root it comes away from the head instead.
PARTS = {
    "ear_l": dict(
        outline=[(-58, -112), (146.5, -112), (146.5, 17.5), (152, 24), (146, 34), (139, 41), (131.6, 38.4),
                 (120, 50), (-58, 70)],
        pivot=(140, 28), length=124, soft=32, free=None, box=(-58, -112, 184, 124)),
    "ear_r": dict(
        outline=[(259, -112), (438, -112), (438, 170), (300, 170), (296, 135), (292, 110), (288, 95),
                 (283.5, 84), (280.2, 77.6), (273, 74), (269, 60), (266, 48), (263, 38), (260, 28),
                 (256, 18), (259, 12)],
        pivot=(262, 17), length=152, soft=17, free=(20, 44), box=(232, -112, 440, 204)),
    "foot_l": dict(
        outline=[(122.8, 273.8), (126, 268), (146, 269.5), (147.6, 276.4), (158, 290), (162, 340),
                 (85, 340), (100, 285)],
        pivot=(135.5, 276), length=30, soft=7, free=None, box=(84, 252, 188, 326)),
    "foot_r": dict(
        outline=[(228.4, 288.6), (231, 283), (251, 284.5), (252.6, 290.6), (262, 300), (272, 340),
                 (212, 340), (220, 300)],
        pivot=(241, 290.5), length=30, soft=7, free=None, box=(192, 264, 292, 326)),
}

NECK = (197, 152)                       # the head tilts and nods about here
NECK_TOP, NECK_BOTTOM = 134, 172        # above: moves with the head; below: stays with the body
FACE = (104, 46, 296, 152)              # the part of the body that gets repainted
EYE_BOXES = [(130, 58, 178, 112), (222, 60, 272, 118)]
MOUTH = (198, 126.8)                    # middle of the mouth line
CHEEKS = [(129, 118, 12, 7.5), (269.5, 121.5, 11.5, 7.5)]

# Colours, 0..1 RGB.
INK = (0.17, 0.10, 0.10)
MOUTH_IN = (0.47, 0.17, 0.18)
TONGUE = (0.97, 0.56, 0.57)
BLUSH = (1.0, 0.50, 0.48)


# ---------------------------------------------------------------- drawing helpers

def w(x, y):
    """Photo pixel -> canvas pixel."""
    return (x - X0) * S, (y - Y0) * S


def poly_mask(points, feather):
    m = np.zeros((H, W), np.uint8)
    pts = np.array([w(*p) for p in points]) * 16
    cv2.fillPoly(m, [np.round(pts).astype(np.int32)], 255, cv2.LINE_AA, shift=4)
    return cv2.GaussianBlur(m.astype(np.float32) / 255, (0, 0), feather * S)


def smooth(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


class Patch:
    """A rectangle of the canvas, with tools for painting clean shapes into it."""

    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0 = x0, y0
        self.w, self.h = int((x1 - x0) * S), int((y1 - y0) * S)
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        self.xx, self.yy = xx / S + x0, yy / S + y0          # photo coordinates of every pixel

    def coverage(self, draw):
        """Runs draw(canvas, to_px, scale) at a higher resolution and returns the smoothed result."""
        c = np.zeros((self.h * SS, self.w * SS), np.uint8)
        k = S * SS * 16
        draw(c, lambda x, y: (int(round((x - self.x0) * k)), int(round((y - self.y0) * k))), k)
        return cv2.resize(c, (self.w, self.h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255

    def stroke(self, points, widths):
        """A smooth line of varying width."""
        def draw(c, px, k):
            pts, wd = np.array(points, np.float64), np.array(widths, np.float64)
            for i in range(len(pts) - 1):
                n = max(2, int(np.hypot(*(pts[i + 1] - pts[i])) * S * SS))
                for t in np.linspace(0, 1, n, endpoint=False):
                    x, y = pts[i] + (pts[i + 1] - pts[i]) * t
                    cv2.circle(c, px(x, y), int(round((wd[i] + (wd[i + 1] - wd[i]) * t) / 2 * k)), 255, -1,
                               cv2.LINE_8, shift=4)
            cv2.circle(c, px(*pts[-1]), int(round(wd[-1] / 2 * k)), 255, -1, cv2.LINE_8, shift=4)
        return self.coverage(draw)

    def shape(self, points):
        return self.coverage(lambda c, px, k: cv2.fillPoly(
            c, [np.array([px(x, y) for x, y in points], np.int32)], 255, cv2.LINE_8, shift=4))

    def ellipse(self, cx, cy, rx, ry, feather=0.0):
        m = self.coverage(lambda c, px, k: cv2.ellipse(
            c, px(cx, cy), (int(rx * k), int(ry * k)), 0, 0, 360, 255, -1, cv2.LINE_8, shift=4))
        return cv2.GaussianBlur(m, (0, 0), feather * S) if feather else m


def paint(img, cov, colour, strength=1.0):
    m = (cov * strength)[..., None] * img[..., 3:]              # never outside the character
    out = img.copy()
    out[..., :3] = out[..., :3] * (1 - m) + np.array(colour, np.float32) * m
    return out


def skin_fill(img, region):
    """Paints over a region with skin that blends evenly between the colours all round its
    edge (every hidden pixel is the average of its neighbours), so it meets them without a
    seam and without smearing any one colour inwards. Solved small first, then refined."""
    kernel = np.array([[0, 0.25, 0], [0.25, 0, 0.25], [0, 0.25, 0]], np.float32)

    def relax(rgb, hole, rounds):
        for _ in range(rounds):
            rgb = np.where(hole, cv2.filter2D(rgb, -1, kernel, borderType=cv2.BORDER_REPLICATE), rgb)
        return rgb

    ys, xs = np.nonzero(region > 0.01)
    y0, y1 = max(ys.min() - 2 * S, 0), min(ys.max() + 2 * S, img.shape[0])
    x0, x1 = max(xs.min() - 2 * S, 0), min(xs.max() + 2 * S, img.shape[1])
    sub = img[y0:y1, x0:x1, :3]
    hole = region[y0:y1, x0:x1] > 0.01
    small = (sub.shape[1] // S, sub.shape[0] // S)
    hole_s = cv2.resize(hole.astype(np.float32), small, interpolation=cv2.INTER_AREA) > 0.01
    known = 1 - hole_s.astype(np.float32)
    rgb_s = cv2.resize(sub, small, interpolation=cv2.INTER_AREA)
    guess = (cv2.GaussianBlur(rgb_s * known[..., None], (0, 0), 6) / (cv2.GaussianBlur(known, (0, 0), 6)[..., None] + 1e-6))
    rgb_s = relax(np.where(hole_s[..., None], guess, rgb_s), hole_s[..., None], 900)
    fill = cv2.resize(rgb_s, (sub.shape[1], sub.shape[0]), interpolation=cv2.INTER_CUBIC)
    fill = relax(np.where(hole[..., None], fill, sub), hole[..., None], 40)
    out = img.copy()
    m = region[y0:y1, x0:x1, None]
    out[y0:y1, x0:x1, :3] = sub * (1 - m) + fill * m
    return out


# ---------------------------------------------------------------- the rig

DEFAULT = dict(eyes=("open", "open"), mouth=None, blush=0.0,
               ears=(0.0, 0.0), bend=(0.0, 0.0),             # degrees each ear is lifted, and curled further at the tip
               feet=((0.0, 0.0), (0.0, 0.0)),                # each foot: degrees swung (+ is to the right), pixels lifted
               head=(0.0, 0.0, 0.0),                         # degrees tilted (+ tips right), pixels right, pixels down
               squash=0.0, lean=0.0, dx=0.0, dy=0.0)         # the whole mate; dy < 0 is up


class Rig:
    def __init__(self):
        rgba = np.asarray(Image.open(HERE / "cutout.png").convert("RGBA"), np.float32) / 255
        rgba[..., :3] *= rgba[..., 3:]
        self.base = np.zeros((H, W, 4), np.float32)
        ox, oy = int(w(0, -TOP_PAD)[0]), int(w(0, -TOP_PAD)[1])
        rows = min(rgba.shape[0], H - oy)                       # the photo has empty rows under the feet
        assert rgba[rows:, :, 3].max(initial=0) < 0.01, "the canvas cuts off part of the picture"
        self.base[oy:oy + rows, ox:ox + rgba.shape[1]] = rgba[:rows]

        # Where the feet are: the bottom of the picture, centred on the body.
        a = rgba[..., 3]
        self.floor_y = float(np.nonzero(a.max(axis=1) > 0.5)[0].max() + 1) / S - TOP_PAD
        rows = [np.nonzero(a[int((y + TOP_PAD) * S)] > 0.5)[0] for y in range(200, 270)]
        self.mid_x = float(np.mean([(r.min() + r.max()) / 2 for r in rows])) / S

        # The body loses each part where the part's outline lies outside CORE, with a soft
        # edge along the join, and the part's layer is exactly what was cut, so the two add
        # back up to the original (see render). `stiff` says how fully each point of a part
        # follows when the part turns: not at all on the join, completely a little way off.
        core = poly_mask(CORE, 0.5)
        # How far each point is from the head and body themselves (not from CORE, which
        # also takes in empty space around them).
        off_core = cv2.distanceTransform(((core < 0.5) | (self.base[..., 3] < 0.5)).astype(np.uint8), cv2.DIST_L2, 5) / S
        self.cut = np.zeros((H, W), np.float32)
        self.parts = {}
        for name, part in PARTS.items():
            cut = poly_mask(part["outline"], 0.4) * (1 - core)
            self.cut += cut
            px, py = w(*part["pivot"])
            bx0, by0 = (int(v) for v in w(part["box"][0], part["box"][1]))
            bx1, by1 = (int(v) for v in w(part["box"][2], part["box"][3]))
            layer = self.base * cut[..., None]
            assert layer[..., 3].sum() - layer[by0:by1, bx0:bx1, 3].sum() < 1, f"{name} does not fit its box"
            # The warp is worked out at one point per photo pixel and stretched to full size.
            gy, gx = np.mgrid[0:(by1 - by0) // S, 0:(bx1 - bx0) // S].astype(np.float32)
            dx, dy = (gx + 0.5) * S - 0.5 - (px - bx0), (gy + 0.5) * S - 0.5 - (py - by0)
            far = np.hypot(dx, dy) / S
            stiff = smooth(cv2.resize(off_core[by0:by1, bx0:bx1], (gx.shape[1], gx.shape[0]), interpolation=cv2.INTER_AREA)
                           / part["soft"])
            if part["free"]:
                stiff = np.maximum(stiff, smooth((far - part["free"][0]) / (part["free"][1] - part["free"][0])))
            self.parts[name] = dict(layer=np.ascontiguousarray(layer[by0:by1, bx0:bx1]), box=(bx0, by0, bx1, by1),
                                    dx=dx, dy=dy, pivot=(px - bx0, py - by0), stiff=stiff.astype(np.float32),
                                    along=(np.clip(far / part["length"], 0, 1) ** 2).astype(np.float32))
        self.body = self.base * (1 - self.cut)[..., None]
        # The parts sit behind the body, except where they were cut from it: there they are
        # added back in full. At rest that gives back the original exactly, where two soft
        # edges laid over each other would leave a faint see-through seam.
        self.show = np.maximum(1 - self.body[..., 3], np.clip(self.cut * 20, 0, 1))[..., None]

        self.patch = Patch(*FACE)
        self.fx, self.fy = (int(v) for v in w(FACE[0], FACE[1]))
        self.face0 = self.body[self.fy:self.fy + self.patch.h, self.fx:self.fx + self.patch.w].copy()
        self.eyes = [self.find_eye(box) for box in EYE_BOXES]
        self._faces = {}

        # Sample points for the whole-canvas warp (head and whole-body moves).
        gy, gx = np.mgrid[0:H // S, 0:W // S].astype(np.float32)
        self.gx, self.gy = (gx + 0.5) * S - 0.5, (gy + 0.5) * S - 0.5

    @property
    def anchor(self):
        return self.mid_x, self.floor_y

    def find_eye(self, box):
        """Centre and half-width/height of an eye, in photo pixels."""
        p = self.patch
        x0, y0, x1, y1 = (int(round((v - o) * S)) for v, o in zip(box, (p.x0, p.y0, p.x0, p.y0)))
        dark = (self.face0[y0:y1, x0:x1, :3] @ np.array([0.299, 0.587, 0.114], np.float32)) < 0.45
        dark = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((4 * S + 1, 4 * S + 1), np.uint8))
        contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        x, y, bw, bh = cv2.boundingRect(max(contours, key=cv2.contourArea))
        return (x0 + x + bw / 2) / S + p.x0, (y0 + y + bh / 2) / S + p.y0, bw / 2 / S, bh / 2 / S

    # ---- faces

    def face(self, eyes, mouth, blush):
        key = (eyes, mouth, round(blush, 2))
        if key not in self._faces:
            img = self.face0
            for state, eye in zip(eyes, self.eyes):
                img = self.draw_eye(img, state, *eye)
            img = self.draw_mouth(img, mouth)
            if blush > 0:
                for cx, cy, rx, ry in CHEEKS:
                    img = paint(img, self.patch.ellipse(cx, cy, rx, ry, 5.0), BLUSH, 0.46 * blush)
            self._faces[key] = img
        return self._faces[key]

    def eye_cover(self, cx, cy, rx, ry):
        # Generous, to take in the pale rim round each eye as well.
        return self.patch.ellipse(cx, cy, rx * 1.2 + 4.5, ry * 1.15 + 4.5, 1.6)

    def draw_eye(self, img, state, cx, cy, rx, ry):
        p = self.patch
        if state == "open":
            return img
        if state == "wide":
            return self.magnify(img, cx, cy, rx, ry, 1.16)

        bare = skin_fill(img, self.eye_cover(cx, cy, rx, ry))
        ex, ey = rx * 1.06 + 0.8, ry * 1.05 + 0.8                # the eye with its dark edge
        us = np.linspace(-1, 1, 49)
        if isinstance(state, float):                            # upper lid part way down
            u = np.clip((p.xx - cx) / ex, -1, 1)
            lid = cy - ey * np.sqrt(1 - u * u) + state * 2 * ey
            hide = self.eye_cover(cx, cy, rx, ry) * np.clip((lid - p.yy) * S / 2 + 0.5, 0, 1)
            out = img * (1 - hide[..., None]) + bare * hide[..., None]
            line = [(cx + v * ex * 0.985, cy - ey * math.sqrt(1 - v * v) + state * 2 * ey, 1.0 + 1.5 * math.sqrt(1 - v * v))
                    for v in us if -ey * math.sqrt(1 - v * v) + state * 2 * ey <= ey * math.sqrt(1 - v * v)]
            return paint(out, p.stroke([q[:2] for q in line], [q[2] for q in line]), INK) if len(line) > 1 else out
        if state == "closed":                                   # relaxed, curving down
            line = [(cx + v * rx * 1.08, cy + ry * (0.20 + 0.30 * (1 - v * v))) for v in us]
            return paint(bare, p.stroke(line, [1.1 + 1.7 * math.sqrt(1 - v * v) for v in us]), INK)
        if state == "happy":                                    # ^ ^
            line = [(cx + v * rx * 1.02, cy + ry * (0.42 - 0.74 * (1 - v * v) ** 0.9)) for v in us]
            return paint(bare, p.stroke(line, [1.5 + 2.1 * math.sqrt(1 - v * v) for v in us]), INK)
        raise ValueError(state)

    def magnify(self, img, cx, cy, rx, ry, k):
        p = self.patch
        dx, dy = (p.xx - cx) / rx, (p.yy - cy) / ry
        r = np.sqrt(dx * dx + dy * dy) + 1e-6
        far = 1.9
        f = np.where(r < 1, 1 / k, np.where(r < far, (1 / k + (r - 1) * (far - 1 / k) / (far - 1)) / r, 1))
        mx = ((cx + (p.xx - cx) * f) - p.x0) * S
        my = ((cy + (p.yy - cy) * f) - p.y0) * S
        return cv2.remap(img, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_CUBIC,
                         borderMode=cv2.BORDER_REPLICATE).clip(0, 1)

    def draw_mouth(self, img, mouth):
        if mouth is None:
            return img
        p = self.patch
        mx, my = MOUTH
        img = skin_fill(img, p.ellipse(mx, my, 22, 5.5, 1.0))
        us = np.linspace(-1, 1, 41)
        if mouth == "smile":                                    # open, laughing
            top = [(mx + 11.5 * u, my - 0.8 + 2.2 * (1 - u * u)) for u in us]
            bottom = [(x, y + 9.4 * (1 - u * u) ** 0.75) for (x, y), u in zip(top, us)]
            outline = top + bottom[::-1]
            inside = p.shape(outline)
            img = paint(img, inside, MOUTH_IN)
            img = paint(img, np.minimum(inside, p.ellipse(mx, my + 9.6, 6.8, 4.0)), TONGUE)
            return paint(img, np.clip(p.stroke(outline + outline[:1], [1.2] * (len(outline) + 1)) - inside * 0.5, 0, 1), INK)
        if mouth == "o":
            outline = [(mx + 4.6 * math.cos(t), my + 3.6 + 5.4 * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 48)]
            inside = p.shape(outline)
            img = paint(img, inside, MOUTH_IN)
            img = paint(img, np.minimum(inside, p.ellipse(mx, my + 8.0, 3.6, 2.2)), TONGUE)
            return paint(img, p.stroke(outline, [1.1] * len(outline)), INK)
        if mouth == "grin":                                     # closed, turned up
            line = [(mx + 9.5 * u, my + 2.6 - 3.2 * u * u) for u in us]
            return paint(img, p.stroke(line, [0.7 + 1.0 * math.sqrt(1 - u * u) for u in us]), INK)
        raise ValueError(mouth)

    # ---- poses

    def turn(self, name, angle, bend=0.0, lift=0.0):
        """A part's layer, turned `angle` degrees anticlockwise about its pivot, curled a
        further `bend` degrees by its tip, and raised `lift` pixels."""
        part = self.parts[name]
        if not (angle or bend or lift):
            return part["layer"]
        # For every point of the result, find the point of the layer that lands there. How
        # far a point turns depends on where it started, so guess and refine.
        px, py = part["pivot"]
        dx, dy = part["dx"], part["dy"] + lift * S
        qx, qy = dx, dy
        for _ in range(6):
            at = ((qx + px + 0.5) / S - 0.5).astype(np.float32), ((qy + py + 0.5) / S - 0.5).astype(np.float32)
            theta = (math.radians(angle) * cv2.remap(part["stiff"], *at, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                     + math.radians(bend) * cv2.remap(part["along"], *at, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE))
            c, s = np.cos(theta), np.sin(theta)
            qx, qy = dx * c - dy * s, dx * s + dy * c
        size = (part["layer"].shape[1], part["layer"].shape[0])
        mx = cv2.resize((px + qx).astype(np.float32), size, interpolation=cv2.INTER_LINEAR)
        my = cv2.resize((py + qy).astype(np.float32), size, interpolation=cv2.INTER_LINEAR)
        return cv2.remap(part["layer"], mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=0)

    def head_weight(self, x, y):
        """How much of the head's movement a point takes part in: all of it above the neck,
        none below, and all of it out to the right where only the hanging ear can be."""
        return np.maximum(smooth((NECK_BOTTOM - y) / (NECK_BOTTOM - NECK_TOP)), smooth((x - 290) / 10) * (y < 200))

    def carry(self, pose, x, y):
        """Where a point on the head ends up once the head and the whole mate have moved."""
        tilt, hx, hy = pose["head"]
        c, s = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
        x, y = NECK[0] + (x - NECK[0]) * c - (y - NECK[1]) * s + hx, NECK[1] + (x - NECK[0]) * s + (y - NECK[1]) * c + hy
        ax, ay = self.anchor
        sx, sy = 1 + 0.7 * pose["squash"], 1 - pose["squash"]
        c, s = math.cos(math.radians(pose["lean"])), math.sin(math.radians(pose["lean"]))
        x, y = (x - ax) * sx, (y - ay) * sy
        return ax + x * c - y * s + pose["dx"], ay + x * s + y * c + pose["dy"]

    def render(self, pose):
        """The pose, drawn on the canvas."""
        pose = {**DEFAULT, **pose}
        img = self.body.copy()
        face = self.face(pose["eyes"], pose["mouth"], pose["blush"])
        img[self.fy:self.fy + face.shape[0], self.fx:self.fx + face.shape[1]] = face

        # Lifting the left ear's tip turns it clockwise on screen, the right ear's anticlockwise.
        for name, angle, bend, lift in (("ear_l", -pose["ears"][0], -pose["bend"][0], 0),
                                        ("ear_r", pose["ears"][1], pose["bend"][1], 0),
                                        ("foot_l", pose["feet"][0][0], 0, pose["feet"][0][1]),
                                        ("foot_r", pose["feet"][1][0], 0, pose["feet"][1][1])):
            x0, y0, x1, y1 = self.parts[name]["box"]
            region = img[y0:y1, x0:x1]
            region += self.turn(name, angle, bend, lift) * self.show[y0:y1, x0:x1]
            region /= np.maximum(region[..., 3:], 1)

        tilt, hx, hy = pose["head"]
        whole = pose["squash"] or pose["lean"] or pose["dx"] or pose["dy"]
        if not (tilt or hx or hy or whole):
            return img
        # One warp for the head and the whole body together. For every point of the result,
        # work back to where it comes from: first undo the whole-body move...
        ax, ay = w(*self.anchor)
        sx, sy = 1 + 0.7 * pose["squash"], 1 - pose["squash"]
        c, s = math.cos(math.radians(pose["lean"])), math.sin(math.radians(pose["lean"]))
        px, py = self.gx - ax - pose["dx"] * S, self.gy - ay - pose["dy"] * S
        px, py = ax + (px * c + py * s) / sx, ay + (-px * s + py * c) / sy
        # ...then the head's. How far a point moves depends on where it started, so guess and refine.
        if tilt or hx or hy:
            nx, ny = w(*NECK)
            qx, qy = px, py
            for _ in range(4):
                k = self.head_weight(qx / S + X0, qy / S + Y0)
                c, s = np.cos(math.radians(tilt) * k), np.sin(math.radians(tilt) * k)
                dx, dy = px - nx - hx * S * k, py - ny - hy * S * k
                qx, qy = nx + dx * c + dy * s, ny - dx * s + dy * c
            px, py = qx, qy
        mx = cv2.resize(px.astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR)
        my = cv2.resize(py.astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR)
        return cv2.remap(img, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=0)

    def frame(self, pose):
        """The pose as a finished picture at the saved size."""
        img = np.clip(self.render(pose), 0, 1)
        out = cv2.resize(img, (round(W * OUT / S), round(H * OUT / S)), interpolation=cv2.INTER_AREA)
        a = out[..., 3:]
        rgb = np.where(a > 1e-4, out[..., :3] / np.maximum(a, 1e-4), 0)
        return (np.clip(np.dstack([rgb, a]), 0, 1) * 255 + 0.5).astype(np.uint8)


# ---------------------------------------------------------------- movement

EAR_HZ, EAR_DAMPING = 2.7, 0.46         # how fast an ear swings back, and how soon it settles
EAR_PUSH = 0.62                         # how hard the head's movement throws the ears about
EAR_CURL = 2.2                          # degrees the tip trails behind per radian/second of swing
# Which way each ear's tip goes when it lifts (screen directions: x right, y down).
EAR_LIFTS = {"ear_l": (-0.204, -0.977), "ear_r": (0.83, -0.56)}


def animate(rig, clip, seconds, fps, calm, step=1 / 500):
    """Samples clip(t) through one turn of the loop, lets the ears swing, and returns the
    frames as (pose, milliseconds). A frame is held for as long as nothing has visibly
    moved; a calm clip waits for a little more movement, so the tail end of a settling ear
    does not cost a frame every time."""
    n = int(round(seconds / step))
    poses = [{**DEFAULT, **clip(i * step)} for i in range(n)]
    lifts = np.array([p["ears"] for p in poses], np.float64)
    curls = np.array([p["bend"] for p in poses], np.float64)
    omega = 2 * math.pi * EAR_HZ
    for e, name in enumerate(("ear_l", "ear_r")):
        # How the ear's root is being thrown about: its acceleration, measured across the ear.
        root = np.array([rig.carry(p, *PARTS[name]["pivot"]) for p in poses])
        acc = (np.roll(root, -1, 0) - 2 * root + np.roll(root, 1, 0)) / step ** 2
        acc = cv2.GaussianBlur(np.concatenate([acc] * 3), (1, 0), 0.012 / step)[n:2 * n]
        push = -(acc @ np.array(EAR_LIFTS[name])) / PARTS[name]["length"] * EAR_PUSH
        # A spring pulls the ear towards where the clip wants it. Three turns of the loop,
        # so that the last one starts as it ends and the loop joins up.
        target, posed = np.radians(lifts[:, e]), curls[:, e].copy()
        angle, speed = target[0], 0.0
        for _ in range(3):
            for i in range(n):
                speed += (-omega * omega * (angle - target[i]) - 2 * EAR_DAMPING * omega * speed + push[i]) * step
                angle += speed * step
                lifts[i, e] = math.degrees(angle)
                curls[i, e] = min(max(posed[i] - EAR_CURL * speed, -15), 15)

    frames, every, ms, within = [], int(round(1 / fps / step)), round(1000 / fps), 0.9 if calm else 0.2
    for i in range(0, n, every):
        pose = {**poses[i], "ears": (round(float(lifts[i, 0]), 1), round(float(lifts[i, 1]), 1)),
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
    or pixels apart."""
    def flat(p):
        return [*p["ears"], *p["bend"], *p["feet"][0], *p["feet"][1], *(2 * v for v in p["head"]),
                p["squash"] * 150, p["lean"] * 2, p["dx"], p["dy"], p["blush"] * 10]
    return (a["eyes"], a["mouth"]) == (b["eyes"], b["mouth"]) and max(abs(x - y) for x, y in zip(flat(a), flat(b))) < within


def ease(t, a=0.0, b=1.0):
    """0 before a, 1 after b, gliding between."""
    return float(smooth((t - a) / (b - a)))


def bump(t, start, rise, hold, fall):
    """0, gliding up to 1 over `rise`, staying for `hold`, gliding back over `fall`."""
    return ease(t, start, start + rise) * (1 - ease(t, start + rise + hold, start + rise + hold + fall))


def blink(t, at):
    """The eyes for a blink that starts at `at`: quick to shut, a little slower to open."""
    for until, lids in ((0.05, 0.55), (0.15, "closed"), (0.20, 0.62)):
        if at <= t < at + until:
            return (lids, lids)
    return None


# ---------------------------------------------------------------- the clips

def idle(t):
    """Stands and looks about: blinks, flicks an ear, tilts its head to one side for a moment."""
    eyes = blink(t, 1.2) or blink(t, 5.6) or blink(t, 7.6) or blink(t, 7.9) or ("open", "open")
    flick_r = 26 * bump(t, 2.6, 0.05, 0.03, 0.06)               # a quick tug; the spring does the rest
    flick_l = 24 * bump(t, 8.9, 0.05, 0.03, 0.06)
    tilt = 7.5 * bump(t, 4.3, 0.34, 1.9, 0.40)
    return dict(eyes=eyes, mouth="grin" if 4.5 < t < 6.5 else None,
                ears=(flick_l + 0.5 * tilt, flick_r + 0.3 * tilt), head=(tilt, 0.5 * tilt, 0))


def walk(t):
    """A waddle: rocks from foot to foot, lifting the free one, head staying level and
    the ears bobbing along."""
    u = 2 * math.pi * t / 0.52
    side = math.sin(u)
    return dict(lean=5.0 * side, dy=-4.5 * abs(side), squash=0.025 * math.cos(u) ** 2, dx=1.5 * side,
                head=(-3.2 * math.sin(u - 0.5), 0, 1.2 * math.cos(u) ** 2),
                ears=(3 - 6 * abs(side), 2 - 4 * abs(side)),
                feet=((-10 * max(0.0, side), 7.5 * max(0.0, side) ** 0.8), (10 * max(0.0, -side), 7.5 * max(0.0, -side) ** 0.8)))


def happy_ears(t):
    """Shown during every built-in dance move, which adds its own body motion on top:
    a delighted face, with the ears flapping in turn like little wings."""
    u = 2 * math.pi * t / 0.52
    return dict(eyes=("happy", "happy"), mouth="smile", blush=1.0,
                ears=(13 * math.sin(u), 13 * math.sin(u + math.pi)))


def bunny_hop(t):
    """Two hops, one to each side. Clip dances get no motion from the app, so it is all here.
    It bounces like a ball: squashes as it lands, springs off stretched, hangs at the top,
    and comes down stretched again, with the feet kicking out in the air."""
    hop, side = (t % 0.48) / 0.48, 1 if t % 0.96 < 0.48 else -1
    ground = 0.36                                               # share of each hop spent on the floor
    if hop < ground:
        g = hop / ground
        air, height = 0.0, 0.0
        squash = 0.13 * math.sin(math.pi * g) - 0.07 * (1 - ease(g, 0, 0.3)) - 0.07 * ease(g, 0.7, 1)
    else:
        air = (hop - ground) / (1 - ground)
        height = 46 * 4 * air * (1 - air)
        squash = -0.07 * abs(1 - 2 * air) ** 1.5
    up = math.sin(math.pi * air)
    tuck = bump(air, 0.12, 0.3, 0.16, 0.3)
    return dict(eyes=("happy", "happy"), mouth="smile", blush=1.0,
                squash=squash, dy=-height, lean=side * 5.5 * up, dx=side * 5 * up,
                head=(-side * 2.5 * up, 0, 22 * max(squash, 0) - 1.5 * tuck),
                feet=((-14 * tuck, 5 * tuck), (14 * tuck, 5 * tuck)))


def ear_wave(t):
    """Sways from side to side on the beat, tapping the free foot and waving the high ear."""
    u = 2 * math.pi * t / 0.96
    side = math.sin(u)
    left, right = max(0.0, -side), max(0.0, side)
    tap_l = max(0.0, math.sin(2 * u - 0.6)) * (side > 0)        # the foot away from the lean
    tap_r = max(0.0, math.sin(2 * u - 0.6)) * (side < 0)
    happy = abs(side) > 0.93
    return dict(eyes=("happy", "happy") if happy else ("open", "open"), mouth="smile", blush=0.8,
                lean=8 * side, dx=6 * side, squash=0.045 * side * side,
                head=(-4.5 * math.sin(u - 0.45), 0, 1.5 * side * side),
                feet=((-6 * tap_l, 5.5 * tap_l), (6 * tap_r, 5.5 * tap_r)),
                ears=(20 * left - 3, 20 * right - 3), bend=(6 * left * math.sin(4 * u), 6 * right * math.sin(4 * u)))


def carried(t):
    """Picked up by the scruff: wide eyes, a little 'o', ears up, feet pedalling."""
    u = 2 * math.pi * t / 0.4
    return dict(eyes=("wide", "wide"), mouth="o", squash=-0.05, lean=1.5 * math.sin(u),
                ears=(22 + 4 * math.sin(2 * u), 24 + 4 * math.sin(2 * u + 1.4)),
                bend=(7 * math.sin(2 * u - 1.0), 7 * math.sin(2 * u + 0.4)),
                feet=((-4 + 14 * math.sin(u), 2 + 2 * math.sin(u)), (4 - 14 * math.sin(u), 2 - 2 * math.sin(u))))


def falling(t):
    """Dropped: ears streaming up, feet trailing."""
    u = 2 * math.pi * t / 0.24
    return dict(eyes=("wide", "wide"), mouth="o", squash=-0.07, head=(0, 0, -2),
                ears=(29 + 3 * math.sin(u), 31 + 3 * math.sin(u + 1.6)),
                bend=(7 + 4 * math.sin(u - 1.0), 7 + 4 * math.sin(u + 0.6)),
                feet=((-9 + 4 * math.sin(u), 4), (9 + 4 * math.sin(u + 2.0), 4)))


def asleep(t):
    """Slumped with its head on one side; an ear twitches now and then. The app adds the
    breathing and the Zs."""
    return dict(eyes=("closed", "closed"), squash=0.06, lean=2.5, head=(7, 2, 3),
                ears=(-16 + 20 * bump(t, 3.0, 0.05, 0.03, 0.07), -12))


CLIPS = {
    # key: file, name in the Dance move menu, the clip, its length, frames a second, calm
    "idle": ("idle.webp", None, idle, 10.0, 20, True),
    "walk": ("walk.webp", None, walk, 0.52, 25, False),
    "dance": ("dance.webp", "Happy Ears", happy_ears, 0.52, 25, False),
    "dance_bunny_hop": ("dance_bunny_hop.webp", "Bunny Hop", bunny_hop, 0.96, 25, False),
    "dance_ear_wave": ("dance_ear_wave.webp", "Ear Wave", ear_wave, 0.96, 25, False),
    "drag": ("drag.webp", None, carried, 0.40, 25, False),
    "fall": ("fall.webp", None, falling, 0.24, 25, False),
    "sleep": ("sleep.webp", None, asleep, 6.0, 20, True),
}


def build(rig, key):
    """Renders one clip: its frames cropped to what they use, their timings, and where the
    feet are in the cropped frames."""
    _, _, clip, seconds, fps, calm = CLIPS[key]
    timeline = animate(rig, clip, seconds, fps, calm)
    images = [rig.frame(pose) for pose, _ in timeline]
    used = np.max([im[..., 3] for im in images], axis=0) > 0
    ys, xs = np.nonzero(used.any(axis=1))[0], np.nonzero(used.any(axis=0))[0]
    x0, y0, x1, y1 = max(xs[0] - 2, 0), max(ys[0] - 2, 0), xs[-1] + 3, ys[-1] + 3
    anchor = [round((rig.mid_x - X0) * OUT - x0, 1), round((rig.floor_y - Y0) * OUT - y0, 1)]
    return [Image.fromarray(im[y0:y1, x0:x1], "RGBA") for im in images], [ms for _, ms in timeline], anchor


def main():
    rig = Rig()
    print("eyes:", [tuple(round(v, 1) for v in eye) for eye in rig.eyes], " feet:", round(rig.mid_x, 1), round(rig.floor_y, 1))

    manifest = {"name": "Mochi", "height": 150, "facing": "right", "removeBackground": False, "clips": {}}
    standing = rig.frame({})[..., 3].any(axis=1).sum()         # how tall the mate is standing still, in saved pixels
    rows, pixels = [], 0
    for key, (file, name, *_ ) in CLIPS.items():
        images, durations, anchor = build(rig, key)
        if len(images) == 1:
            file = file.rsplit(".", 1)[0] + ".png"
            images[0].save(PACK / file, optimize=True)
        else:
            images[0].save(PACK / file, save_all=True, append_images=images[1:], duration=durations, loop=0,
                           lossless=False, quality=90, alpha_quality=100, method=4, use_sharp_yuv=True)
        manifest["clips"][key] = {"file": file, "anchor": anchor, **({"name": name} if name else {})}
        if key == "idle":
            # The app makes the idle clip, at its tallest, `height` pixels high. Idle tilts
            # its head, which makes it a little taller than the mate is, so allow for that.
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
