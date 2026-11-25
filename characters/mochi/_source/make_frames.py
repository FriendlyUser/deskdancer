#!/usr/bin/env python3
"""Builds Mochi's animations from one cut-out picture.

    python3 make_frames.py            # writes the clips into the character folder
    python3 make_frames.py --sheet    # also saves sheet.png, every frame on one page

The picture is split into three layers: the head and body, and one layer per ear. The
ears turn about their roots and sit behind the head, so they can twitch, flap and droop
without leaving a gap. The face is redrawn on top for blinks, closed and happy eyes,
wide eyes and an open mouth. Every clip is drawn on the same canvas with the feet in the
same place, and character.json pins that point so clips never jump sideways.

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

S = 2.0                                 # working resolution, in multiples of the source picture
OUT = 1.6                               # saved resolution, in multiples of the source picture
X0, Y0, X1, Y1 = -10, -75, 385, 325     # canvas, in source pixels; room above for hops and ears
W, H = int((X1 - X0) * S), int((Y1 - Y0) * S)
SS = 4                                  # supersampling for drawn strokes

# Shapes, in source pixels. The head outline continues under where the ears join it.
HEAD = [(195, 2), (215, 2), (235, 4), (250, 8), (262, 14), (270, 24), (274, 36), (277, 50), (280, 68),
        (283, 88), (285, 110), (285, 160), (110, 160), (112, 110), (118, 80), (124, 58), (128, 44),
        (134, 30), (142, 18), (155, 9), (175, 4)]
# Around each ear. Where an ear meets the head the outline runs a few pixels inside the
# head; across the top it stops where the ear ends, so no scalp is carried off with it.
EAR_L = [(-40, -80), (148, -80), (148, 10), (150, 16), (143, 26), (137, 36), (132, 47), (126, 58),
         (110, 60), (-40, 64)]
EAR_R = [(252, -80), (420, -80), (420, 170), (300, 170), (295, 140), (291, 100), (280, 92), (278, 88),
         (275, 68), (272, 50), (269, 38), (265, 28), (258, 19), (250, 13)]
PIVOT_L = (143, 29)
PIVOT_R = (262, 30)
ROOT = 18                               # how far from the pivot the hidden strip reaches
MOUTH = (198, 125.5)                    # middle of the mouth line
EYE_BOXES = [(130, 58, 178, 112), (222, 60, 272, 118)]

# Colours, linear 0..1 RGB.
INK = (0.17, 0.11, 0.11)
MOUTH_IN = (0.45, 0.17, 0.18)
TONGUE = (0.96, 0.56, 0.57)


def w(x, y):
    """Source pixel -> working canvas pixel."""
    return ((x - X0) * S, (y - Y0) * S)


def poly_mask(points, feather=0.8):
    m = np.zeros((H, W), np.uint8)
    pts = np.array([w(*p) for p in points]) * 16
    cv2.fillPoly(m, [np.round(pts).astype(np.int32)], 255, cv2.LINE_AA, shift=4)
    m = m.astype(np.float32) / 255
    return cv2.GaussianBlur(m, (0, 0), feather * S) if feather else m


def over(top, bottom):
    """Premultiplied 'top over bottom'."""
    return top + bottom * (1 - top[..., 3:4])


def coverage(draw):
    """Runs draw(canvas, to_px) on a supersampled canvas and returns the smoothed coverage."""
    c = np.zeros((H * SS, W * SS), np.uint8)
    draw(c, lambda x, y: (int(round(w(x, y)[0] * SS * 16)), int(round(w(x, y)[1] * SS * 16))))
    return cv2.resize(c, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255


def paint(img, cov, colour):
    out = img.copy()
    m = cov[..., None]
    out[..., :3] = out[..., :3] * (1 - m) + np.array(colour, np.float32) * m
    out[..., 3:] = out[..., 3:] + m * (1 - out[..., 3:])
    return out


def stroke(points, widths):
    """A smooth line of varying width through source-pixel points, as coverage."""
    def draw(c, px):
        pts = np.array(points, np.float64)
        wd = np.array(widths, np.float64)
        for i in range(len(pts) - 1):
            n = max(2, int(np.hypot(*(pts[i + 1] - pts[i])) * S * 3))
            for t in np.linspace(0, 1, n, endpoint=False):
                x, y = pts[i] + (pts[i + 1] - pts[i]) * t
                r = (wd[i] + (wd[i + 1] - wd[i]) * t) / 2
                cv2.circle(c, px(x, y), int(round(r * S * SS * 16)), 255, -1, cv2.LINE_8, shift=4)
        cv2.circle(c, px(*pts[-1]), int(round(wd[-1] / 2 * S * SS * 16)), 255, -1, cv2.LINE_8, shift=4)
    return coverage(draw)


def shape(points):
    def draw(c, px):
        cv2.fillPoly(c, [np.array([px(x, y) for x, y in points], np.int32)], 255, cv2.LINE_8, shift=4)
    return coverage(draw)


def ellipse_mask(cx, cy, rx, ry, feather=0.6):
    """cx..ry in working pixels."""
    m = np.zeros((H, W), np.uint8)
    cv2.ellipse(m, (int(cx * 16), int(cy * 16)), (int(rx * 16), int(ry * 16)), 0, 0, 360, 255, -1,
                cv2.LINE_AA, shift=4)
    m = m.astype(np.float32) / 255
    return cv2.GaussianBlur(m, (0, 0), feather * S) if feather else m


def disc(px):
    k = int(round(px * S)) * 2 + 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def skin_fill(img, region):
    """Paints over a region with skin that blends evenly between the colours all round its
    edge (a membrane fill: every hidden pixel is the average of its neighbours), so it meets
    them without a seam and without smearing any one colour inwards."""
    hole = region > 0.01
    ys, xs = np.nonzero(hole)
    y0, y1, x0, x1 = ys.min() - 2, ys.max() + 3, xs.min() - 2, xs.max() + 3
    sub = img[y0:y1, x0:x1, :3]
    h = hole[y0:y1, x0:x1, None]
    known = 1 - h[..., 0].astype(np.float32)
    # Start from a blurred guess, then relax it.
    guess = (cv2.GaussianBlur(sub * known[..., None], (0, 0), 6 * S)
             / (cv2.GaussianBlur(known, (0, 0), 6 * S)[..., None] + 1e-6))
    fill = np.where(h, guess, sub)
    kernel = np.array([[0, 0.25, 0], [0.25, 0, 0.25], [0, 0.25, 0]], np.float32)
    for _ in range(800):
        fill = np.where(h, cv2.filter2D(fill, -1, kernel, borderType=cv2.BORDER_REPLICATE), sub)
    out = img.copy()
    m = region[y0:y1, x0:x1, None]
    out[y0:y1, x0:x1, :3] = sub * (1 - m) + fill * m
    return out


# ---------------------------------------------------------------- the rig

class Rig:
    def __init__(self):
        rgba = np.asarray(Image.open(HERE / "cutout.png").convert("RGBA"), np.float32) / 255
        rgba[..., :3] *= rgba[..., 3:]
        sh, sw = rgba.shape[:2]
        big = cv2.resize(rgba, (int(sw * S), int(sh * S)), interpolation=cv2.INTER_CUBIC)
        big = np.clip(big, 0, 1)
        big[..., :3] = np.minimum(big[..., :3], big[..., 3:])
        self.base = np.zeros((H, W, 4), np.float32)
        ox, oy = int(-X0 * S), int(-Y0 * S)
        bh, bw = min(big.shape[0], H - oy), min(big.shape[1], W - ox)
        assert big[bh:, :, 3].max(initial=0) < 0.01, "the canvas cuts off part of the picture"
        self.base[oy:oy + bh, ox:ox + bw] = big[:bh, :bw]

        # Where the feet are: the bottom of the picture, centred on the body.
        a = rgba[..., 3]
        ys = np.nonzero(a.max(axis=1) > 0.5)[0]
        self.floor_y = float(ys.max()) + 1
        rows = [np.nonzero(a[y] > 0.5)[0] for y in range(200, 270)]
        self.mid_x = float(np.mean([(r.min() + r.max()) / 2 for r in rows if len(r)]))

        # The body loses each ear where the ear's outline lies outside the head, with a soft
        # edge along the head; the ear layer is exactly what was cut, so the two add back up
        # to the original (see pose). Near its root an ear also carries a strip of head along
        # the join, reaching in under the head's soft edge, which fills the wedge that opens
        # there as the ear turns. The strip keeps clear of the head's outer edge, and stays
        # near the root, so none of it swings out on its own.
        head = poly_mask(HEAD, 0.6)
        solid = cv2.erode((self.base[..., 3] > 0.99).astype(np.uint8), disc(4))
        self.cut = np.zeros((H, W), np.float32)
        for name, outline, pivot in (("ear_l", EAR_L, PIVOT_L), ("ear_r", EAR_R, PIVOT_R)):
            cut = poly_mask(outline, 0.5) * (1 - head)
            self.cut += cut
            along = cv2.dilate((cut > 0.5).astype(np.uint8), disc(6)) & solid
            near = ellipse_mask(*w(*pivot), ROOT * S, ROOT * S, 0)
            root = cv2.GaussianBlur(along.astype(np.float32) * near, (0, 0), 0.6 * S)
            setattr(self, name, self.base * np.maximum(cut, root)[..., None])
        self.body = self.base * (1 - self.cut)[..., None]
        self.eyes = [self.find_eye(box) for box in EYE_BOXES]

        # The face with nothing on it, for painting new eyes and mouths onto.
        bare = self.body
        for cx, cy, rx, ry in self.eyes:
            bare = skin_fill(bare, self.eye_cover(cx, cy, rx, ry))
        self.bare_eyes = bare
        mx, my = w(*MOUTH)
        self.no_mouth = ellipse_mask(mx, my, 21 * S, 5.5 * S, 0.8)
        self._faces = {}

    def find_eye(self, box):
        x0, y0, x1, y1 = box
        (a, b), (c, d) = w(x0, y0), w(x1, y1)
        a, b, c, d = int(a), int(b), int(c), int(d)
        rgb = self.base[b:d, a:c, :3]
        dark = (rgb @ np.array([0.299, 0.587, 0.114], np.float32)) < 0.45
        dark = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        x, y, bw, bh = cv2.boundingRect(max(contours, key=cv2.contourArea))
        return a + x + bw / 2, b + y + bh / 2, bw / 2, bh / 2      # working pixels

    @staticmethod
    def eye_cover(cx, cy, rx, ry):
        # Generous, because the eyes have a pale halo that would otherwise show as a ring.
        return ellipse_mask(cx, cy, rx * 1.2 + 5 * S, ry * 1.15 + 5 * S, 1.6)

    # ---- faces

    def face(self, left, right, mouth):
        key = (left, right, mouth)
        if key not in self._faces:
            img = self.body
            for state, eye in ((left, self.eyes[0]), (right, self.eyes[1])):
                img = self.draw_eye(img, state, *eye)
            img = self.draw_mouth(img, mouth)
            self._faces[key] = img
        return self._faces[key]

    def draw_eye(self, img, state, cx, cy, rx, ry):
        # cx..ry are working pixels; strokes are given in source pixels.
        def src(x, y):
            return x / S + X0, y / S + Y0

        if state == "open":
            return img
        if state == "wide":
            return self.magnify(img, cx, cy, rx, ry, 1.17)

        bare = skin_fill(img, self.eye_cover(cx, cy, rx, ry))
        ex, ey = rx * 1.1 + 2 * S, ry * 1.08 + 2 * S
        us = np.linspace(-1, 1, 41)
        if isinstance(state, float):                        # upper lid part way down
            f = state
            yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
            u = np.clip((xx - cx) / ex, -1, 1)
            lid = cy - ey * np.sqrt(1 - u * u) + f * 2 * ey
            hide = self.eye_cover(cx, cy, rx, ry) * np.clip((lid - yy) / S + 0.5, 0, 1)
            out = img * (1 - hide[..., None]) + bare * hide[..., None]
            pts, wid = [], []
            for uu in us:
                top = cy - ey * math.sqrt(1 - uu * uu)
                y = top + f * 2 * ey
                if y <= cy + ey * math.sqrt(1 - uu * uu):
                    pts.append(src(cx + uu * ex * 0.97, y))
                    wid.append(1.0 + 1.4 * math.sqrt(1 - uu * uu))
            return paint(out, stroke(pts, wid), INK) if len(pts) > 1 else out
        if state == "closed":                               # relaxed, curving down
            pts = [src(cx + u * rx * 1.08, cy + ry * (0.18 + 0.32 * (1 - u * u))) for u in us]
            wid = [1.0 + 1.6 * math.sqrt(1 - u * u) for u in us]
            return paint(bare, stroke(pts, wid), INK)
        if state == "happy":                                # ^ ^
            pts = [src(cx + u * rx * 1.0, cy + ry * (0.42 - 0.72 * (1 - u * u) ** 0.9)) for u in us]
            wid = [1.3 + 1.9 * math.sqrt(1 - u * u) for u in us]
            return paint(bare, stroke(pts, wid), INK)
        raise ValueError(state)

    @staticmethod
    def magnify(img, cx, cy, rx, ry, k):
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        dx, dy = (xx - cx) / rx, (yy - cy) / ry
        r = np.sqrt(dx * dx + dy * dy) + 1e-6
        r2 = 1.9
        rs = np.where(r < 1, r / k, np.where(r < r2, 1 / k + (r - 1) * (r2 - 1 / k) / (r2 - 1), r))
        f = rs / r
        return cv2.remap(img, (cx + (xx - cx) * f).astype(np.float32), (cy + (yy - cy) * f).astype(np.float32),
                         cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=0).clip(0, 1)

    def draw_mouth(self, img, mouth):
        if mouth is None:
            return img
        mx, my = MOUTH
        img = skin_fill(img, self.no_mouth)
        if mouth == "smile":
            us = np.linspace(-1, 1, 33)
            top = [(mx + 10.5 * u, my - 0.5 + 2.0 * (1 - u * u)) for u in us]
            bot = [(mx + 10.5 * u, my - 0.5 + 2.0 * (1 - u * u) + 8.5 * (1 - u * u) ** 0.75) for u in us]
            outline = top + bot[::-1]
            inside = shape(outline)
            tongue = np.minimum(inside, coverage(lambda c, px: cv2.ellipse(
                c, px(mx, my + 8.6), (int(6.2 * S * SS * 16), int(3.6 * S * SS * 16)), 0, 0, 360, 255, -1,
                cv2.LINE_8, shift=4)))
            img = paint(img, inside, MOUTH_IN)
            img = paint(img, tongue, TONGUE)
            ring = stroke(outline + outline[:1], [1.1] * (len(outline) + 1))
            return paint(img, np.clip(ring - inside * 0.55, 0, 1), INK)
        if mouth == "o":
            outline = [(mx + 4.3 * math.cos(t), my + 3.4 + 5.0 * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 40)]
            inside = shape(outline)
            tongue = np.minimum(inside, coverage(lambda c, px: cv2.ellipse(
                c, px(mx, my + 7.6), (int(3.4 * S * SS * 16), int(2.0 * S * SS * 16)), 0, 0, 360, 255, -1,
                cv2.LINE_8, shift=4)))
            img = paint(img, inside, MOUTH_IN)
            img = paint(img, tongue, TONGUE)
            return paint(img, stroke(outline, [1.0] * len(outline)), INK)
        raise ValueError(mouth)

    # ---- poses

    def pose(self, eyes=("open", "open"), mouth=None, ears=(0.0, 0.0), squash=0.0, lean=0.0, dx=0.0, dy=0.0):
        """ears: degrees each ear tip is lifted. squash > 0 is shorter and wider, lean > 0
        tips the head right, dx/dy move the whole mate (source pixels, dy < 0 is up)."""
        def turn(layer, pivot, deg):
            if abs(deg) < 1e-3:
                return layer
            m = cv2.getRotationMatrix2D(w(*pivot), deg, 1.0)
            return cv2.warpAffine(layer, m, (W, H), flags=cv2.INTER_CUBIC, borderValue=(0, 0, 0, 0)).clip(0, 1)

        # Lifting the left ear's tip turns it clockwise on screen, the right ear's anticlockwise.
        body = self.face(eyes[0], eyes[1], mouth)
        both = turn(self.ear_l, PIVOT_L, -ears[0]) + turn(self.ear_r, PIVOT_R, ears[1])
        # The ears sit behind the head, except where they were cut from it: there they are
        # added back in full. At rest that gives back the original exactly, where two soft
        # edges laid over each other would leave a faint see-through seam.
        show = np.maximum(1 - body[..., 3], np.clip(self.cut * 20, 0, 1))[..., None]
        img = body + both * show
        img /= np.maximum(img[..., 3:], 1)
        if squash or lean or dx or dy:
            ax, ay = w(self.mid_x, self.floor_y)
            sx, sy = 1 + 0.7 * squash, 1 - squash
            c, s = math.cos(math.radians(lean)), math.sin(math.radians(lean))
            a = np.array([[c * sx, -s * sy], [s * sx, c * sy]])
            t = np.array([ax, ay]) - a @ np.array([ax, ay]) + np.array([dx, dy]) * S
            img = cv2.warpAffine(img, np.hstack([a, t[:, None]]), (W, H), flags=cv2.INTER_CUBIC,
                                 borderValue=(0, 0, 0, 0)).clip(0, 1)
        return img

    def save_size(self, img):
        out = cv2.resize(img, (int(W * OUT / S), int(H * OUT / S)), interpolation=cv2.INTER_AREA)
        a = out[..., 3:]
        rgb = np.where(a > 1e-4, out[..., :3] / np.maximum(a, 1e-4), 0)
        return Image.fromarray((np.clip(np.dstack([rgb, a]), 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA")

    @property
    def anchor(self):
        return [round((self.mid_x - X0) * OUT, 1), round((self.floor_y - Y0) * OUT, 1)]


# ---------------------------------------------------------------- the clips

def blink(frames, eyes_after=("open", "open")):
    frames += [(dict(eyes=(0.45, 0.45)), 40), (dict(eyes=("closed", "closed")), 70),
               (dict(eyes=(0.45, 0.45)), 50)]


def idle():
    f = [(dict(), 1700)]
    blink(f)
    f.append((dict(), 1300))
    for lift, ms in ((7, 50), (13, 50), (5, 60), (-3, 60), (2, 60)):      # right ear flicks
        f.append((dict(ears=(0, lift)), ms))
    f.append((dict(), 1500))
    blink(f)
    f.append((dict(), 110))
    blink(f)
    f.append((dict(), 900))
    for lift, ms in ((8, 50), (14, 50), (6, 60), (-3, 60), (1, 60)):      # then the left
        f.append((dict(ears=(lift, 0)), ms))
    f.append((dict(), 1200))
    return f


def happy_ears():
    """Shown during every built-in dance move, which adds its own body motion on top."""
    n, beat = 10, 0.5
    out = []
    for i in range(n):
        p = 2 * math.pi * i / n
        out.append((dict(eyes=("happy", "happy"), mouth="smile",
                         ears=(15 * math.sin(p), 15 * math.sin(p + math.pi))), beat * 1000 / n))
    return out


def bunny_hop():
    """Two hops, one leaning each way. Clip dances get no motion from the app, so it is all here."""
    out, n = [], 12
    for hop in range(2):
        side = 1 if hop == 0 else -1
        for i in range(n):
            p = i / n
            squash, dy, ears = 0.0, 0.0, 0.0
            if p < 0.15:                                    # crouch
                squash, ears = 0.10 * p / 0.15, -6 * p / 0.15
            elif p < 0.65:                                  # in the air
                q = (p - 0.15) / 0.5
                dy = -42 * math.sin(math.pi * q)
                squash = -0.07 * (1 - q) + 0.02 * q
                ears = -10 + 28 * q
            elif p < 0.8:                                   # land
                q = (p - 0.65) / 0.15
                squash, ears = 0.12 * math.sin(math.pi * q), 18 - 14 * q
            else:
                q = (p - 0.8) / 0.2
                ears = 4 * (1 - q)
            lean = side * 6 * math.sin(math.pi * min(1, p / 0.8))
            out.append((dict(eyes=("happy", "happy"), mouth="smile", ears=(ears, ears),
                             squash=squash, lean=lean, dy=dy), 500 / n))
    return out


def ear_wave():
    """Sways side to side, bobbing on the beat, lifting the ear on the high side."""
    out, n = [], 24
    for i in range(n):
        t = i / n                                           # one second: two beats
        s = math.sin(2 * math.pi * t)
        bob = 0.5 * (1 + math.cos(4 * math.pi * t))
        out.append((dict(eyes=("open", "open") if i % 12 not in (5, 6) else ("happy", "happy"),
                         mouth="smile", ears=(22 * max(0, -s) - 4, 22 * max(0, s) - 4),
                         lean=9 * s, dx=7 * s, squash=0.045 * bob), 1000 / n))
    return out


def dangle():
    """Picked up: wide eyes, a little 'o', ears up and fluttering."""
    out, n = [], 8
    for i in range(n):
        p = 2 * math.pi * i / n
        out.append((dict(eyes=("wide", "wide"), mouth="o",
                         ears=(20 + 6 * math.sin(p), 22 + 6 * math.sin(p + 1.3)), squash=-0.05), 45))
    return out


def sleep():
    return [(dict(eyes=("closed", "closed"), ears=(-14, -9), squash=0.09, lean=6), 1000)]


CLIPS = {
    # key: (file, menu name or None, frames)
    "idle": ("idle.webp", None, idle),
    "dance": ("dance.webp", "Happy Ears", happy_ears),
    "dance_bunny_hop": ("dance_bunny_hop.webp", "Bunny Hop", bunny_hop),
    "dance_ear_wave": ("dance_ear_wave.webp", "Ear Wave", ear_wave),
    "drag": ("drag.webp", None, dangle),
    "sleep": ("sleep.png", None, sleep),
}


def main():
    rig = Rig()
    print("eyes (source px):", [(round(cx / S + X0, 1), round(cy / S + Y0, 1), round(rx / S, 1), round(ry / S, 1))
                                for cx, cy, rx, ry in rig.eyes])
    print("feet at", round(rig.mid_x, 1), round(rig.floor_y, 1), "-> anchor", rig.anchor)

    manifest = {"name": "Mochi", "height": 150, "facing": "right", "removeBackground": False, "clips": {}}
    sheet_rows = []
    for key, (file, name, make) in CLIPS.items():
        frames = make()
        images = [rig.save_size(rig.pose(**spec)) for spec, _ in frames]
        durations = [max(20, int(round(ms / 10)) * 10) for _, ms in frames]   # WebP keeps whole ms; 10 ms is safe for GIF viewers too
        path = PACK / file
        if len(images) == 1:
            images[0].save(path, optimize=True)
        else:
            images[0].save(path, save_all=True, append_images=images[1:], duration=durations, loop=0,
                           lossless=False, quality=92, alpha_quality=100, method=6)
        clip = {"file": file, "anchor": rig.anchor}
        if name:
            clip["name"] = name
        manifest["clips"][key] = clip
        sheet_rows.append((key, images))
        print(f"{file}: {len(images)} frames, {sum(durations) / 1000:.2f}s, {path.stat().st_size // 1024} KB")

    (PACK / "character.json").write_text(json.dumps(manifest, indent=2) + "\n")

    if "--sheet" in sys.argv:
        cell = 160
        cols = max(len(im) for _, im in sheet_rows)
        sheet = Image.new("RGBA", (cols * cell, len(sheet_rows) * cell), (40, 44, 64, 255))
        for r, (_, images) in enumerate(sheet_rows):
            for c, im in enumerate(images):
                t = im.copy()
                t.thumbnail((cell, cell), Image.LANCZOS)
                sheet.alpha_composite(t, (c * cell + (cell - t.width) // 2, r * cell + (cell - t.height) // 2))
        sheet.save(HERE / "sheet.png")


if __name__ == "__main__":
    main()
