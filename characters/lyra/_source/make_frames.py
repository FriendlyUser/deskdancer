#!/usr/bin/env python3
"""Builds Lyra's animations from one cut-out drawing.

    python3 make_frames.py              # writes the clips and character.json into the pack
    python3 make_frames.py --sheet      # also saves sheet.png, every frame on one page
    python3 make_frames.py idle drag    # only rebuilds the clips named

It takes about five minutes for everything.

The drawing is treated as a puppet with a few working parts:

- Face. Each eye can blink part way, close, smile (^ ^) or widen; the mouth can grin (as
  drawn), sing, smile with the lips closed, or make a small "o". Eyes and mouth are
  painted out with skin that blends in from all round their edge, then redrawn.
- Hair. The two long falls of hair are bent by a smooth warp that is zero over the face
  and body and grows towards the tips, so they swing and bounce without tearing. A
  damped spring drives them from the body's own motion, so they lag and overshoot.
- Hand. The open hand bends at the wrist to wave; the sash behind it is repainted so
  nothing shows through when it lifts.
- Body. Lean, squash, sway and hops, all about the point between the feet.

Every clip is drawn on the same canvas with the feet in the same place, then trimmed to
the part it uses so the pack loads quickly; character.json records where the feet are in
each clip (anchor), so clips never jump. Coordinates are pixels of cutout.png. Needs numpy, pillow and opencv-python-headless. This folder starts with "_",
so the app does not load anything from it.
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

X0, Y0, X1, Y1 = -150, -170, 1160, 1090    # canvas, in cutout pixels: room to lean and hop
W, H = X1 - X0, Y1 - Y0
OUT = 0.44                                  # saved size, relative to cutout.png
SS = 4                                      # supersampling for painted strokes

# ---- where things are, in cutout pixels

# The left eye (on screen) touches a lock of hair. Its outer edge is cut along the hair's
# outline so the hair is left alone.
EYE_L_AREA = [(243, 446), (275, 446), (310, 442), (352, 452), (356, 575), (264, 573), (240, 557),
              (231, 540), (228, 522), (230, 505), (234, 486), (239, 468)]
EYE_R_AREA = [(414, 404), (604, 404), (604, 552), (414, 552)]
EYE_REACH = 11                              # how far round the eye the skin is repainted
EYEBROWS = [(279, 433, 304, 447)]           # boxes kept out of the eye areas
MOUTH_AREA = [(355, 580), (462, 578), (462, 636), (355, 636)]

# Closed and smiling eyes are drawn as one thick stroke each, (points, widths); the
# outer corner gets a flick of lashes.
CLOSED = {
    "L": ([(345, 518), (325, 530), (300, 536), (275, 534), (252, 526), (236, 514), (226, 500)],
          [2.5, 5, 7, 8.5, 9.5, 9, 4]),
    "R": ([(428, 486), (455, 503), (490, 512), (525, 512), (558, 504), (584, 490), (600, 474)],
          [2.5, 5, 7.5, 9, 10, 10, 5]),
}
CLOSED_FLICK = {
    "L": [([(236, 514), (224, 512), (212, 506)], [6, 4, 1.2]),
          ([(244, 522), (232, 528), (222, 532)], [5, 3.5, 1.2])],
    "R": [([(590, 485), (604, 480), (618, 470)], [7, 4.5, 1.4]),
          ([(584, 494), (598, 500), (612, 502)], [5.5, 3.5, 1.2])],
}
HAPPY = {
    "L": ([(240, 530), (252, 512), (270, 499), (292, 494), (314, 499), (332, 512), (344, 526)],
          [3, 6.5, 8.5, 9, 8.5, 6, 2.5]),
    "R": ([(434, 506), (452, 484), (480, 468), (513, 462), (546, 467), (574, 482), (596, 502)],
          [3, 7, 9, 10, 9.5, 8, 4]),
}
HAPPY_FLICK = {
    "L": [([(244, 524), (232, 520), (222, 512)], [5, 3, 1.2])],
    "R": [([(590, 496), (604, 494), (618, 486)], [6, 4, 1.2])],
}

# The mouth, in a frame tilted to match the drawn grin: centre, half width, tilt.
MOUTH_C = (409, 608)
MOUTH_HW = 44
MOUTH_TILT = -10.5                          # degrees; the right corner is higher

# Hair hangs from about HAIR_ROOT_Y and is freest at HAIR_TIP_Y. Anything else that is
# drawn stays put; RIGID adds the parts the hair test cannot tell from hair (the face, and
# the gloved hand on the lute's neck).
HAIR_ROOT_Y, HAIR_TIP_Y = 330, 745
HAIR_RAMP = 100                             # how far from rigid parts the hair is fully free
HAIR_SPLIT_X = 470                          # left and right falls swing separately
RIGID = [
    [(236, 330), (330, 250), (460, 240), (600, 300), (655, 420), (650, 560), (580, 650), (450, 690),
     (330, 665), (240, 600), (212, 520), (220, 420)],
    [(612, 515), (725, 515), (725, 610), (665, 700), (565, 830), (470, 830), (560, 640)],
]
# A point near the bottom of each fall, for the spring that drives it.
HAIR_TIPS = {"L": (150, 700), "R": (800, 720)}

# The open hand bends at the wrist. HAND outlines fingers, palm, thumb and glove; the
# bend fades in between BEND_FROM and BEND_TO pixels out from the wrist.
HAND = [(304, 770), (284, 769), (266, 774), (247, 771), (232, 763), (214, 760), (203, 765), (196, 778),
        (197, 792), (207, 805), (224, 811), (233, 812), (235, 824), (243, 832), (253, 832), (263, 831), (278, 834),
        (296, 829), (308, 820), (310, 804)]
WRIST = (302, 798)
HAND_AXIS = (-1.0, -0.08)                   # from the wrist towards the fingertips
BEND_FROM, BEND_TO = 2, 30
# What the thumb hides: the top of the sash, and its outline on the left.
SASH_UNDER = [(261, 840), (275, 796), (314, 796), (314, 840)]
SASH_EDGE = ([(256, 846), (262, 832), (267, 818), (272, 806), (276, 796)], [5.5, 5.5, 5.5, 5.5, 5.5])

INK = (0.07, 0.05, 0.07)
MOUTH_IN = (0.47, 0.13, 0.19)
TONGUE = (0.86, 0.42, 0.46)
TEETH = (1.0, 0.99, 0.95)


# ---------------------------------------------------------------- helpers

def to_canvas(x, y):
    return x - X0, y - Y0


def poly_mask(points, feather=0.0):
    m = np.zeros((H, W), np.uint8)
    pts = np.array([to_canvas(*p) for p in points]) * 16
    cv2.fillPoly(m, [np.round(pts).astype(np.int32)], 255, cv2.LINE_AA, shift=4)
    m = m.astype(np.float32) / 255
    return cv2.GaussianBlur(m, (0, 0), feather) if feather else m


def coverage(draw):
    """Runs draw(canvas, px) on a supersampled canvas and returns the smoothed coverage.
    px maps cutout pixels to fixed-point supersampled canvas pixels."""
    c = np.zeros((H * SS, W * SS), np.uint8)
    draw(c, lambda x, y: (int(round((x - X0) * SS * 16)), int(round((y - Y0) * SS * 16))))
    return cv2.resize(c, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255


def stroke(points, widths, closed=False):
    """A smooth tapering line through the points (Catmull-Rom), as coverage."""
    pts = np.array(points, np.float64)
    wd = np.array(widths, np.float64)
    if closed:
        pts = np.vstack([pts, pts[:1]])
        wd = np.append(wd, wd[0])
    dense, dw = catmull(pts, wd)

    def draw(c, px):
        for (x, y), r in zip(dense, dw / 2):
            cv2.circle(c, px(x, y), max(1, int(round(r * SS * 16))), 255, -1, cv2.LINE_8, shift=4)
    return coverage(draw)


def catmull(pts, wd, per=24):
    if len(pts) < 3:
        t = np.linspace(0, 1, per * 2)[:, None]
        return pts[0] + (pts[1] - pts[0]) * t, wd[0] + (wd[1] - wd[0]) * t[:, 0]
    p = np.vstack([2 * pts[0] - pts[1], pts, 2 * pts[-1] - pts[-2]])
    out, ow = [], []
    for i in range(1, len(p) - 2):
        seg = np.hypot(*(p[i + 1] - p[i]))
        n = max(4, int(seg * 2))
        for t in np.linspace(0, 1, n, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p[i]) + (-p[i - 1] + p[i + 1]) * t
                              + (2 * p[i - 1] - 5 * p[i] + 4 * p[i + 1] - p[i + 2]) * t2
                              + (-p[i - 1] + 3 * p[i] - 3 * p[i + 1] + p[i + 2]) * t3))
            ow.append(wd[i - 1] + (wd[i] - wd[i - 1]) * t)
    out.append(p[-2])
    ow.append(wd[-1])
    return np.array(out), np.array(ow)


def shape(points):
    """Filled smooth closed shape through the points, as coverage."""
    dense, _ = catmull(np.vstack([points, points[:1]]), np.ones(len(points) + 1))

    def draw(c, px):
        cv2.fillPoly(c, [np.array([px(x, y) for x, y in dense], np.int32)], 255, cv2.LINE_8, shift=4)
    return coverage(draw)


def paint(img, cov, colour):
    """Paints an opaque colour over a premultiplied image with the given coverage."""
    m = cov[..., None]
    out = img * (1 - m)
    out[..., :3] += np.array(colour, np.float32) * m
    out[..., 3:] += m
    return out


def membrane_fill(img, hole, valid):
    """Fills `hole` with colours that blend smoothly between the `valid` pixels round its
    edge (every filled pixel becomes the average of its usable neighbours). Pixels that
    are neither are left out, so hair or lashes next to the hole do not bleed into it."""
    ys, xs = np.nonzero(hole)
    y0, y1, x0, x1 = ys.min() - 3, ys.max() + 4, xs.min() - 3, xs.max() + 4
    sub = img[y0:y1, x0:x1, :3].copy()
    h = hole[y0:y1, x0:x1]
    use = (valid[y0:y1, x0:x1] & ~h).astype(np.float32)
    live = np.maximum(use, h.astype(np.float32))
    # Start from a coarse-to-fine blur of the usable pixels, so even the middle of a big
    # hole starts close to the answer, then relax.
    guess = None
    for sigma in (64, 32, 16, 8):
        wv = cv2.GaussianBlur(use, (0, 0), sigma)
        gv = cv2.GaussianBlur(sub * use[..., None], (0, 0), sigma) / (wv[..., None] + 1e-6)
        if guess is None:
            guess = gv
        else:
            conf = np.clip(wv / 0.2, 0, 1)[..., None]
            guess = guess * (1 - conf) + gv * conf
    fill = np.where(h[..., None], guess, sub)
    k = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], np.float32)
    weight = cv2.filter2D(live, -1, k, borderType=cv2.BORDER_CONSTANT) + 1e-6
    for _ in range(1500):
        avg = cv2.filter2D(fill * live[..., None], -1, k, borderType=cv2.BORDER_CONSTANT) / weight[..., None]
        fill = np.where(h[..., None], avg, sub)
    out = img.copy()
    out[y0:y1, x0:x1, :3] = np.where(h[..., None], fill, sub)
    return out


def transform(img, matrix, interp=cv2.INTER_CUBIC):
    return cv2.warpAffine(img, matrix, (W, H), flags=interp, borderValue=(0, 0, 0, 0)).clip(0, 1)


def about(cx, cy, deg=0.0, sx=1.0, sy=None, dx=0.0, dy=0.0):
    """2x3 matrix: scale and rotate about (cx, cy) in canvas pixels, then move."""
    sy = sx if sy is None else sy
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    a = np.array([[c * sx, -s * sy], [s * sx, c * sy]])
    t = np.array([cx, cy]) - a @ np.array([cx, cy]) + np.array([dx, dy])
    return np.hstack([a, t[:, None]]).astype(np.float64)


def unpremultiply(img):
    a = img[..., 3:]
    rgb = np.where(a > 1e-4, img[..., :3] / np.maximum(a, 1e-4), 0)
    return np.dstack([np.clip(rgb, 0, 1), np.clip(a, 0, 1)])


# ---------------------------------------------------------------- the face

class Face:
    def __init__(self, base):
        self.base = base                                    # premultiplied, canvas sized
        rgb = unpremultiply(base)
        r, g, b, a = rgb[..., 0], rgb[..., 1], rgb[..., 2], rgb[..., 3]
        self.skin = (r > 0.6) & (r - g > 0.08) & (g >= b - 0.01) & (b > 0.38) & (a > 0.95)

        brows = np.zeros((H, W), bool)
        for bx0, by0, bx1, by1 in EYEBROWS:
            (cx0, cy0), (cx1, cy1) = to_canvas(bx0, by0), to_canvas(bx1, by1)
            brows[cy0:cy1, cx0:cx1] = True
        # What gets painted out: the eye (or mouth) and the soft shading round it, which
        # would otherwise be left as a smudge. Colours are only taken from clean skin.
        def around(marks, reach):
            d = cv2.distanceTransform((~marks).astype(np.uint8), cv2.DIST_L2, 5)
            return d <= reach

        self.eye_mask = {}
        for side, area in (("L", EYE_L_AREA), ("R", EYE_R_AREA)):
            inside = poly_mask(area) > 0.5
            marks = inside & ~self.skin & ~brows
            self.eye_mask[side] = around(marks, EYE_REACH) & inside & ~brows
        inside = poly_mask(MOUTH_AREA) > 0.5
        self.mouth_mask = around(inside & ~self.skin, 6) & inside
        clean = cv2.erode(self.skin.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0

        # Face with nothing on it, for drawing new eyes and mouths onto.
        bare = base
        for side in "LR":
            bare = membrane_fill(bare, self.eye_mask[side], clean)
        self.bare_eyes = bare
        self.bare_mouth = membrane_fill(base, self.mouth_mask, clean)
        self.eye_box = {}
        for side in "LR":
            ys, xs = np.nonzero(self.eye_mask[side])
            self.eye_box[side] = (xs.min(), ys.min(), xs.max(), ys.max())
        self._cache = {}

    def eye_layer(self, side):
        soft = cv2.GaussianBlur(self.eye_mask[side].astype(np.float32), (0, 0), 0.8)
        return self.base * soft[..., None], soft

    def draw_eye(self, img, side, state):
        if state == "open":
            return img
        hole = self.eye_mask[side]
        soft = cv2.GaussianBlur(hole.astype(np.float32), (0, 0), 0.8)[..., None]
        bare = img * (1 - soft) + self.bare_eyes * soft
        if state in ("closed", "happy"):
            pts, wid = (CLOSED if state == "closed" else HAPPY)[side]
            cov = stroke(pts, wid)
            for fp, fw in (CLOSED_FLICK if state == "closed" else HAPPY_FLICK)[side]:
                cov = np.maximum(cov, stroke(fp, fw))
            return paint(bare, cov, INK)
        # Part way shut, or wide: the drawn eye itself, squeezed or enlarged.
        x0, y0, x1, y1 = self.eye_box[side]
        layer, _ = self.eye_layer(side)
        cx = (x0 + x1) / 2
        if state == "wide":
            m = about(cx, (y0 + y1) / 2, 0, 1.08, 1.1)
        else:                                               # a number: how far shut
            m = about(cx, y1 - 0.12 * (y1 - y0), 0, 1.0 + 0.04 * state, 1 - 0.85 * state)
        moved = transform(layer, m)
        return moved + bare * (1 - moved[..., 3:])

    def draw_mouth(self, img, mouth):
        if mouth == "grin":
            return img
        soft = cv2.GaussianBlur(self.mouth_mask.astype(np.float32), (0, 0), 0.8)[..., None]
        img = img * (1 - soft) + self.bare_mouth * soft
        cx, cy = MOUTH_C
        ca, sa = math.cos(math.radians(MOUTH_TILT)), math.sin(math.radians(MOUTH_TILT))

        def at(u, v):                                       # mouth frame -> cutout pixels
            x, y = u * MOUTH_HW, v
            return (cx + x * ca - y * sa, cy + x * sa + y * ca)

        us = np.linspace(-1, 1, 29)
        if mouth == "smile":
            pts = [at(u * 0.92, -4 + 9 * (1 - u * u)) for u in us[::2]]
            wid = [1.8 + 3.2 * (1 - u * u) ** 0.6 for u in us[::2]]
            cov = stroke(pts, wid)
            cov = np.maximum(cov, stroke([at(0.92, -4), at(1.02, -8)], [2.2, 1.2]))
            return paint(img, cov, INK)
        if mouth == "sing":
            hw, top, depth = 0.78, -2, 34
        elif mouth == "o":
            hw, top, depth = 0.32, -10, 28
        else:
            raise ValueError(mouth)
        top_edge = [at(u * hw, top + 4 * (1 - u * u)) for u in us]
        bottom = [at(u * hw, top + 4 * (1 - u * u) + depth * (1 - u * u) ** 0.7) for u in us[::-1]]
        if mouth == "o":
            t = np.linspace(0, 2 * math.pi, 28, endpoint=False)
            outline = [at(0.33 * math.cos(a), 2 + 15 * math.sin(a)) for a in t]
        else:
            outline = top_edge + bottom[1:-1]
        inside = shape(np.array(outline))
        img = paint(img, inside, MOUTH_IN)
        if mouth == "sing":
            teeth = shape(np.array([at(u * hw * 0.93, top + 4 * (1 - u * u) - 1) for u in us]
                                   + [at(u * hw * 0.93, top + 4 * (1 - u * u) + 7 * (1 - u * u) ** 0.5)
                                      for u in us[::-1]]))
            img = paint(img, np.minimum(teeth, inside), TEETH)
        tongue_c = at(0.06, (top + depth) * 0.86 if mouth == "sing" else 12)
        rx, ry = (20, 9) if mouth == "sing" else (8, 5)
        tongue = coverage(lambda c, px: cv2.ellipse(
            c, px(*tongue_c), (int(rx * SS * 16), int(ry * SS * 16)), MOUTH_TILT, 0, 360, 255, -1,
            cv2.LINE_8, shift=4))
        img = paint(img, np.minimum(tongue, inside) * 0.95, TONGUE)
        ring = stroke(outline, [3.4] * len(outline), closed=True)
        return paint(img, np.clip(ring, 0, 1), INK)

    def get(self, eyes=("open", "open"), mouth="grin"):
        key = (eyes, mouth)
        if key not in self._cache:
            img = self.base
            img = self.draw_eye(img, "L", eyes[0])
            img = self.draw_eye(img, "R", eyes[1])
            img = self.draw_mouth(img, mouth)
            self._cache[key] = img
        return self._cache[key]


# ---------------------------------------------------------------- hair, hand and body

def smoothstep(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


class Rig:
    def __init__(self):
        self.base = load_base()
        self.face = Face(self.base)
        rgb = unpremultiply(self.base)
        a = rgb[..., 3]
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        self.grid = (xx, yy)

        # Feet, in cutout pixels: the bottom of the drawing, centred between the two soles.
        ys, xs = np.nonzero(a > 0.5)
        soles = xs[ys > ys.max() - 60]
        self.feet = ((soles.min() + soles.max()) / 2 + X0, float(ys.max()) + 1 + Y0)

        # Hair weights: 0 on everything rigid, rising with distance from it and with how
        # far down the hair hangs.
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        sat = (rgb[..., :3].max(-1) - rgb[..., :3].min(-1)) / np.maximum(rgb[..., :3].max(-1), 1e-3)
        hair = ((b >= r - 0.02) & (b >= g - 0.01) & (a > 0.5) & (sat < 0.5)).astype(np.uint8)
        hair = cv2.morphologyEx(hair, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        _, lab, stats, _ = cv2.connectedComponentsWithStats(hair)
        hair = lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        rigid = (a > 0.5) & ~hair
        for poly in RIGID:
            rigid |= poly_mask(poly) > 0.5
        dist = cv2.distanceTransform((~rigid).astype(np.uint8), cv2.DIST_L2, 5)
        hang = smoothstep((yy - (HAIR_ROOT_Y - Y0)) / (HAIR_TIP_Y - HAIR_ROOT_Y))
        near = cv2.GaussianBlur(cv2.dilate(hair.astype(np.uint8), np.ones((61, 61), np.uint8)).astype(np.float32),
                                (0, 0), 15)
        weight = cv2.GaussianBlur(smoothstep(dist / HAIR_RAMP) * hang * near, (0, 0), 8)
        side = smoothstep((xx - (HAIR_SPLIT_X - X0) + 60) / 120)
        self.hair_w = {"L": weight * (1 - side), "R": weight * side}

        # The hand, and what is behind it.
        self.hand_mask = poly_mask(HAND, 0.7)
        # The sash carries on up under the thumb: each column takes the colour the sash
        # has just below the hand, so its folds run on unbroken.
        sash = poly_mask(SASH_UNDER) > 0.5
        beige = (rgb[..., 0] > 0.55) & (rgb[..., 0] - rgb[..., 2] > 0.12) & (a > 0.95)
        hand_hard = poly_mask(HAND) > 0.05
        filled = np.zeros((H, W, 3), np.float32)
        ys, xs = np.nonzero(sash)
        for x in range(xs.min(), xs.max() + 1):
            col = np.nonzero(sash[:, x])[0]
            y = col.min()
            while y < H - 6 and (hand_hard[y, x] or not beige[y:y + 5, x].all()):
                y += 1
            filled[col, x] = rgb[y + 1:y + 5, x, :3].mean(axis=0)
        filled = cv2.GaussianBlur(filled, (0, 0), sigmaX=1.2, sigmaY=0.1)
        under = np.zeros_like(self.base)
        sash_soft = cv2.GaussianBlur(sash.astype(np.float32), (0, 0), 0.7)
        under[..., :3] = filled * sash_soft[..., None]
        under[..., 3] = sash_soft
        edge = stroke(*SASH_EDGE)                       # overlaps the drawn outline below, so it joins up
        # The sash's own outline colour: the darkest pixels along its left edge.
        (ex0, ey0), (ex1, ey1) = to_canvas(238, 838), to_canvas(256, 870)
        edge_px = rgb[ey0:ey1, ex0:ex1][(rgb[ey0:ey1, ex0:ex1, 3] > 0.95)][:, :3]
        ink = np.median(edge_px[edge_px.sum(1) < np.percentile(edge_px.sum(1), 15)], axis=0)
        under = paint(under, edge, ink)
        self.under_mask = np.maximum(self.hand_mask, edge)
        self.under = under * self.under_mask[..., None]      # shown where the hand was
        self.hand = self.base * self.hand_mask[..., None]

    def hand_pose(self, img, lift):
        """lift: degrees the fingertips rise (negative lowers them)."""
        if abs(lift) < 1e-3:
            return img
        out = self.under + img * (1 - self.under_mask[..., None])
        xx, yy = self.grid
        px, py = to_canvas(*WRIST)
        vx, vy = xx - px, yy - py
        ax, ay = np.array(HAND_AXIS) / np.hypot(*HAND_AXIS)
        phi = np.radians(lift) * smoothstep(((vx * ax + vy * ay) - BEND_FROM) / (BEND_TO - BEND_FROM))
        c, s_ = np.cos(phi), np.sin(phi)
        mx = (px + vx * c + vy * s_).astype(np.float32)
        my = (py - vx * s_ + vy * c).astype(np.float32)
        moved = cv2.remap(self.hand, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT).clip(0, 1)
        return moved + out * (1 - moved[..., 3:])

    def hair_pose(self, img, hair):
        """hair: {"L": (dx, dy), "R": (dx, dy)}, how far each fall's tip moves."""
        if all(abs(v) < 1e-3 for d in hair.values() for v in d):
            return img
        xx, yy = self.grid
        dx = sum(self.hair_w[k] * hair[k][0] for k in hair)
        dy = sum(self.hair_w[k] * hair[k][1] for k in hair)
        return cv2.remap(img, (xx - dx).astype(np.float32), (yy - dy).astype(np.float32), cv2.INTER_CUBIC,
                         borderMode=cv2.BORDER_CONSTANT).clip(0, 1)

    def body_matrix(self, lean=0.0, squash=0.0, dx=0.0, dy=0.0):
        fx, fy = to_canvas(*self.feet)
        return about(fx, fy, lean, 1 + 0.6 * squash, 1 - squash, dx, dy)

    def pose(self, eyes=("open", "open"), mouth="grin", hand=0.0, hair=None, lean=0.0, squash=0.0, dx=0.0,
             dy=0.0):
        img = self.face.get(tuple(eyes), mouth)
        img = self.hand_pose(img, hand)
        if hair:
            img = self.hair_pose(img, hair)
        if lean or squash or dx or dy:
            img = transform(img, self.body_matrix(lean, squash, dx, dy))
        return img

    @property
    def anchor(self):
        fx, fy = to_canvas(*self.feet)
        return [round(float(fx) * OUT, 1), round(float(fy) * OUT, 1)]


def load_base():
    rgba = np.asarray(Image.open(HERE / "cutout.png").convert("RGBA"), np.float32) / 255
    rgba[..., :3] *= rgba[..., 3:]
    base = np.zeros((H, W, 4), np.float32)
    h, w = rgba.shape[:2]
    base[-Y0:-Y0 + h, -X0:-X0 + w] = rgba
    return base


def to_image(img):
    out = cv2.resize(img, (int(round(W * OUT)), int(round(H * OUT))), interpolation=cv2.INTER_AREA)
    return Image.fromarray((unpremultiply(out) * 255 + 0.5).astype(np.uint8), "RGBA")


# ---------------------------------------------------------------- hair physics

class Hair:
    """Each fall of hair is a damped spring hung from the body. When the body moves, the
    tip is left behind and swings back, so the hair lags, overshoots and settles.

    body(t) gives the body pose (lean, squash, dx, dy) at time t; push(t) an extra force
    per side (a breeze, a flutter). The clip is a loop, so the spring is run for a few
    turns first and the last one is kept, which makes the loop seamless."""

    def __init__(self, rig, body, push=None, period=1.0, stiffness=110.0, damping=6.0, gain=1.0, limit=34.0):
        self.body, self.push = body, push or (lambda t: {"L": (0, 0), "R": (0, 0)})
        self.period, self.limit = period, limit
        dt = 1 / 480
        steps = int(round(period / dt))
        tips = {k: np.array(v, float) for k, v in HAIR_TIPS.items()}

        def where(t, k):
            m = rig.body_matrix(**body(t))
            x, y = to_canvas(*tips[k])
            return m @ np.array([x, y, 1.0])

        self.track = {k: [] for k in tips}
        for k in tips:
            o, v = np.zeros(2), np.zeros(2)
            for turn in range(4):
                rec = []
                for i in range(steps):
                    t = i * dt
                    acc = (where(t + dt, k) - 2 * where(t, k) + where(t - dt, k)) / (dt * dt)
                    f = np.array(self.push(t)[k], float)
                    v += (-stiffness * o - damping * v - gain * acc + f) * dt
                    o += v * dt
                    rec.append(o.copy())
            self.track[k] = np.array(rec)

    def at(self, t):
        i = int(round((t % self.period) * 480)) % len(self.track["L"])
        lean = math.radians(self.body(t).get("lean", 0.0))
        c, s = math.cos(-lean), math.sin(-lean)
        out = {}
        for k, rec in self.track.items():
            ox, oy = rec[i]
            bx, by = c * ox - s * oy, 0.5 * (s * ox + c * oy)   # into the body's frame; hair stretches little
            out[k] = (self.limit * math.tanh(bx / self.limit), self.limit * math.tanh(by / self.limit))
        return out


def frames_from(times, pose_at):
    """Samples pose_at(t) at the given times; each frame lasts until the next one."""
    out = []
    for i, t in enumerate(times[:-1]):
        out.append((pose_at(t), (times[i + 1] - t) * 1000))
    return out


def even(period, fps):
    n = int(round(period * fps))
    return [period * i / n for i in range(n + 1)]


def bump(t, start, length):
    """0 -> 1 -> 0 over [start, start + length], smooth."""
    u = (t - start) / length
    return math.sin(math.pi * u) ** 2 if 0 <= u <= 1 else 0.0


def smooth_ramp(t, start, length):
    """0 before start, 1 after start + length, smooth in between."""
    u = min(1.0, max(0.0, (t - start) / length))
    return u * u * (3 - 2 * u)


# ---------------------------------------------------------------- the clips

def blink(frames):
    frames += [(dict(eyes=(0.5, 0.5)), 40), (dict(eyes=("closed", "closed")), 70), (dict(eyes=(0.5, 0.5)), 50)]


def idle(rig):
    """Mostly still, which the app breathes for her. Blinks, a breeze through her hair,
    and now and then a little wave."""
    f = [(dict(), 2200)]
    blink(f)
    f.append((dict(), 1400))

    # A breeze from the left lifts both falls of hair and lets them go.
    def breeze(t):
        b = bump(t, 0.0, 1.5)
        return {"L": (900 * b, -250 * b), "R": (1100 * b, -200 * b)}
    hair = Hair(rig, lambda t: {}, breeze, period=4.0, stiffness=70, damping=5.5)
    times = even(2.0, 8)
    f += frames_from(times, lambda t: dict(hair=hair.at(t)))
    f.append((dict(), 1200))
    blink(f)
    f.append((dict(), 110))
    blink(f)
    f.append((dict(), 1000))

    # Wave hello: up, two waggles, down.
    def wave(t):
        up = smooth_ramp(t, 0.0, 0.25) * (1 - smooth_ramp(t, 1.35, 0.25))
        return up * (13 + 6 * math.sin(2 * math.pi * 2.0 * (t - 0.25)))
    times = even(1.6, 10)
    f += frames_from(times, lambda t: dict(eyes=("happy", "happy") if 0.2 < t < 1.45 else ("open", "open"),
                                           hand=wave(t)))
    f.append((dict(), 1600))
    blink(f)
    f.append((dict(), 800))
    return f


def happy_dance(rig):
    """Shown during every built-in dance move, which adds its own body motion. Two beats
    at 120 BPM: she sings on one and grins on the other, pumps her hand, and her hair
    bounces as if she were bobbing."""
    period = 1.0
    bob = lambda t: dict(dy=-10 * abs(math.sin(2 * math.pi * t / period)), lean=3 * math.sin(2 * math.pi * t / period))
    hair = Hair(rig, bob, period=period)
    times = even(period, 12)

    def at(t):
        beat = t / (period / 2)
        return dict(eyes=("happy", "happy"), mouth="sing" if int(beat) % 2 == 0 else "grin",
                    hand=10 * math.sin(math.pi * (beat % 1)) ** 2, hair=hair.at(t))
    return frames_from(times, at)


def serenade(rig):
    """Four beats: a slow sway, eyes closed, singing, with the hair swinging behind."""
    period = 2.0

    def body(t):
        p = 2 * math.pi * t / period
        dip = math.sin(math.pi * ((t / 0.5) % 1)) ** 2
        return dict(lean=6 * math.sin(p), dx=10 * math.sin(p), dy=-6 * dip, squash=0.025 * (1 - dip))
    hair = Hair(rig, body, period=period)

    def at(t):
        beat = int(t / 0.5)
        eyes = ("closed", "closed") if beat < 3 else ("happy", "happy")
        mouth = "sing" if beat % 2 == 0 else "smile"
        return dict(eyes=eyes, mouth=mouth, hand=7 + 7 * math.sin(2 * math.pi * t / period + 0.6),
                    hair=hair.at(t), **body(t))
    return frames_from(even(period, 10), at)


def hair_flip(rig):
    """Four beats: wind up, whip right, whip left, hop. All about the hair."""
    period = 2.0

    def body(t):
        lean = (-3 * bump(t, 0.0, 0.5) + 11 * bump(t, 0.5, 0.42) - 11 * bump(t, 1.0, 0.42))
        squash = 0.06 * bump(t, 0.05, 0.45) + 0.07 * bump(t, 1.5, 0.12) + 0.05 * bump(t, 1.88, 0.12)
        dy = -46 * math.sin(math.pi * min(1, max(0, (t - 1.6) / 0.3))) if 1.6 <= t <= 1.9 else 0.0
        return dict(lean=lean, squash=squash, dy=dy, dx=8 * bump(t, 0.5, 0.42) - 8 * bump(t, 1.0, 0.42))
    hair = Hair(rig, body, period=period, stiffness=95, damping=5.0, gain=0.4)

    def at(t):
        if t < 0.45:
            eyes, mouth = ("open", "open"), "grin"
        elif t < 1.45:
            eyes, mouth = (("happy", "open") if t < 0.95 else ("open", "happy")), "grin"
        else:
            eyes, mouth = ("happy", "happy"), "sing"
        return dict(eyes=eyes, mouth=mouth, hand=14 * bump(t, 1.5, 0.45), hair=hair.at(t), **body(t))
    return frames_from(even(period, 12), at)


def wave_hello(rig):
    """Four beats: two little hops, waving all the while."""
    period = 2.0

    def body(t):
        hop = 0.0
        for start in (0.0, 1.0):
            u = (t - start) / 0.42
            if 0 <= u <= 1:
                hop = math.sin(math.pi * u)
        land = sum(bump(t, s, 0.14) for s in (0.4, 1.4))
        return dict(dy=-30 * hop, squash=-0.03 * hop + 0.06 * land, lean=-2 + 4 * math.sin(math.pi * t))
    hair = Hair(rig, body, period=period)

    def at(t):
        hop = body(t)["dy"] < -15
        return dict(eyes=("happy", "happy"), mouth="sing" if hop else "grin",
                    hand=12 + 7 * math.sin(2 * math.pi * 2.5 * t), hair=hair.at(t), **body(t))
    return frames_from(even(period, 10), at)


def dangle(rig):
    """Picked up: wide eyes, a little "o", hand flailing, hair fluttering."""
    period = 0.6

    def flutter(t):
        p = 2 * math.pi * t / period
        return {"L": (1800 * math.sin(p), 600 * math.sin(2 * p)), "R": (-1800 * math.sin(p + 0.8), 600 * math.sin(2 * p + 1))}
    hair = Hair(rig, lambda t: dict(squash=-0.04), flutter, period=period, stiffness=140, damping=7)
    return frames_from(even(period, 15), lambda t: dict(
        eyes=("wide", "wide"), mouth="o", hand=6 + 12 * math.sin(2 * math.pi * 2 * t / period),
        squash=-0.04, hair=hair.at(t)))


def sleep(rig):
    """Dozing, tipped to one side. The app adds the breathing and the Zs."""
    return [(dict(eyes=("closed", "closed"), mouth="smile", hand=-5, lean=6, squash=0.05,
                  hair={"L": (-12, 5), "R": (-14, 6)}), 1000)]


CLIPS = {
    # key: (file, menu name or None, frames)
    "idle": ("idle.webp", None, idle),
    "dance": ("dance.webp", "Sing Along", happy_dance),
    "dance_serenade": ("dance_serenade.webp", "Serenade", serenade),
    "dance_hair_flip": ("dance_hair_flip.webp", "Hair Flip", hair_flip),
    "dance_wave": ("dance_wave.webp", "Wave Hello", wave_hello),
    "drag": ("drag.webp", None, dangle),
    "sleep": ("sleep.png", None, sleep),
}


def main():
    rig = Rig()
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    print("feet at", [round(float(v), 1) for v in rig.feet], "-> anchor", rig.anchor)
    manifest = {"name": "Lyra", "height": 160, "facing": "right", "removeBackground": False, "clips": {}}
    sheet_rows = []
    old = json.loads((PACK / "character.json").read_text())["clips"] if (PACK / "character.json").exists() else {}
    for key, (file, name, make) in CLIPS.items():
        clip = {"file": file, "anchor": old.get(key, {}).get("anchor", rig.anchor)}
        if name:
            clip["name"] = name
        manifest["clips"][key] = clip
        if only and key not in only:
            continue
        frames = make(rig)
        images = [to_image(rig.pose(**spec)) for spec, _ in frames]
        # Keep only the part of the canvas the clip uses: the app decodes every pixel of
        # every frame when the pack loads, so empty margins would only slow that down.
        boxes = [im.getbbox() for im in images]
        x0, y0 = max(0, min(b[0] for b in boxes) - 2), max(0, min(b[1] for b in boxes) - 2)
        x1 = min(images[0].width, max(b[2] for b in boxes) + 2)
        y1 = min(images[0].height, max(b[3] for b in boxes) + 2)
        images = [im.crop((x0, y0, x1, y1)) for im in images]
        clip["anchor"] = [round(rig.anchor[0] - x0, 1), round(rig.anchor[1] - y0, 1)]
        # Whole 10 ms steps (what GIF and most viewers keep), rounded on the running total
        # so a clip stays exactly as long as it should be: on the beat.
        ends = np.round(np.cumsum([ms for _, ms in frames]) / 10) * 10
        durations = [int(max(20, d)) for d in np.diff(np.concatenate([[0], ends]))]
        path = PACK / file
        if len(images) == 1:
            images[0].save(path, optimize=True)
        else:
            images[0].save(path, save_all=True, append_images=images[1:], duration=durations, loop=0,
                           lossless=False, quality=90, alpha_quality=100, method=6)
        sheet_rows.append((key, images))
        print(f"{file}: {len(images)} frames, {sum(durations) / 1000:.2f}s, {path.stat().st_size // 1024} KB")

    (PACK / "character.json").write_text(json.dumps(manifest, indent=2) + "\n")

    if "--sheet" in sys.argv:
        cell = 150
        cols = min(30, max(len(im) for _, im in sheet_rows))
        rows = sum((len(im) + cols - 1) // cols for _, im in sheet_rows)
        sheet = Image.new("RGBA", (cols * cell, rows * cell), (40, 44, 64, 255))
        r = 0
        for _, images in sheet_rows:
            for i, im in enumerate(images):
                t = im.copy()
                t.thumbnail((cell, cell), Image.LANCZOS)
                sheet.alpha_composite(t, ((i % cols) * cell + (cell - t.width) // 2,
                                          (r + i // cols) * cell + (cell - t.height) // 2))
            r += (len(images) + cols - 1) // cols
        sheet.save(HERE / "sheet.png")


if __name__ == "__main__":
    main()
