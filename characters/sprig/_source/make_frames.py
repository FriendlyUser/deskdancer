#!/usr/bin/env python3
"""Builds Sprig's animations from one cut-out drawing.

    python3 make_frames.py              # writes the clips and character.json into the pack
    python3 make_frames.py --sheet      # also saves sheet.png, every frame on one page
    python3 make_frames.py idle drag    # only rebuilds the clips named

It takes a minute or two for everything; the Spin Attack is most of it.

The drawing is treated as a puppet with a few working parts:

- Face. Each eye can blink part way, close, smile (^ ^), widen or narrow under a frown;
  the mouth can be open (as drawn), shout, smile with the lips closed, set in a firm line
  or make a small "o". Eyes and mouth are painted out with skin that blends in from all
  round their edge, then redrawn. From behind, the face is hair.
- Sword arm. The forearm, hand and sword are one layer that turns at the elbow. What the
  arm covered in the drawing (the cap, its long tail and the shield behind him) is
  painted in, outlines and all, so the arm can go anywhere.
- Cap. The long tail of the cap is bent by a smooth warp that is zero where it leaves his
  head and grows towards the tip. A damped spring drives it from the body's own motion,
  so it lags, flops and overshoots.
- Legs. Each leg is its own layer, cut along the tunic's hem and drawn behind it, so the
  legs can swing to walk and kick, and tuck up under the tunic when he bends his knees.
- Waist. Swaying turns his head and shoulders and bends the body smoothly down to his
  hips, which stay put.
- Body. Lean, squash and hops, all about the point between the feet, and a turn about
  his own upright axis for the Spin Attack, seen from a little above.
- Effects. The blade can glow, sparkles can be scattered about, and a spinning blade
  leaves a ring of light behind it.

Every clip is drawn on the same canvas with the feet in the same place, then trimmed to
the part it uses so the pack loads quickly; character.json records where the feet are in
each clip (anchor), so clips never jump. Coordinates are pixels of cutout.png. Needs
numpy, pillow and opencv-python-headless. This folder starts with "_", so the app does
not load anything from it.
"""
import json
import math
import multiprocessing
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
PACK = HERE.parent

X0, Y0, X1, Y1 = -560, -180, 1190, 1170    # canvas, in cutout pixels: room for the sword to go all the way round
W, H = X1 - X0, Y1 - Y0
OUT = 0.44                                  # saved size, relative to cutout.png
SS = 4                                      # supersampling for painted strokes

# ---- where things are, in cutout pixels

# Eyes. Each area is drawn just round the eye and its lashes, inside the hair that
# frames it; EYE_REACH is how far round the eye the skin is repainted.
EYE_L_AREA = [(146, 452), (155, 436), (166, 421), (179, 409), (196, 405), (213, 411), (227, 422), (238, 434),
              (246, 446), (245, 464), (240, 482), (232, 497), (219, 507), (203, 513), (184, 513), (166, 505),
              (154, 491), (147, 472)]
EYE_R_AREA = [(306, 443), (314, 421), (326, 402), (344, 387), (372, 378), (405, 378), (436, 384), (458, 395),
              (463, 403), (457, 422), (453, 450), (447, 476), (443, 494), (428, 500), (368, 500), (350, 488),
              (338, 466), (326, 453)]
EYE_REACH = 10
MOUTH_AREA = [(250, 524), (300, 511), (347, 514), (347, 562), (320, 582), (284, 582), (254, 548)]
MOUTH_TOP = (300, 521)                      # middle of the top lip, which a shout opens down from

# Closed, smiling and frowning eyes are drawn as strokes, (points, widths).
CLOSED = {
    "L": ([(244, 462), (229, 475), (209, 482), (187, 481), (167, 473), (152, 460)], [3, 6, 8, 8.5, 7, 3.5]),
    "R": ([(314, 452), (338, 469), (368, 477), (400, 476), (428, 467), (452, 451)], [3.5, 6.5, 8.5, 9.5, 8, 4]),
}
CLOSED_FLICK = {
    "L": [([(154, 461), (144, 455), (136, 446)], [5, 3.5, 1.2])],
    "R": [([(448, 454), (460, 448), (470, 438)], [5.5, 4, 1.2])],
}
HAPPY = {
    "L": ([(152, 482), (163, 461), (182, 447), (205, 444), (226, 452), (243, 469)], [3, 6.5, 8.5, 8.5, 6.5, 3]),
    "R": ([(318, 474), (336, 449), (364, 434), (396, 431), (425, 439), (450, 458)], [3.5, 7, 9.5, 9.5, 8, 4]),
}
HAPPY_FLICK = {
    "L": [([(156, 475), (146, 471), (138, 463)], [4.5, 3, 1.2])],
    "R": [([(446, 452), (458, 450), (468, 442)], [5, 3.5, 1.2])],
}
# Narrowed eyes: the upper lid comes down to this line, slanting towards the nose, and
# the lashes go with it.
LID = {
    "L": ([(148, 450), (172, 449), (198, 451), (224, 457), (248, 466)], [4, 8, 9.5, 9, 4]),
    "R": ([(311, 452), (336, 438), (366, 427), (400, 419), (432, 414), (462, 412)], [4.5, 9, 10.5, 10.5, 9, 4]),
}
# A frown: brows slanting down to the nose, drawn over the hair as the drawing's own
# brow is.
FROWN = {
    "L": ([(168, 396), (190, 402), (213, 411), (236, 424)], [3, 6, 7, 5]),
    "R": ([(318, 404), (342, 391), (370, 380), (400, 372), (424, 370)], [5, 7.5, 7, 5.5, 2.5]),
}

# The sword arm: forearm, hand and sword, cut out whole. It turns about ELBOW; ROOT is a
# disc of bracer at the elbow, under the arm, so no gap opens there when it turns, and
# SLEEVE is the bit of tunic at his shoulder that stays over the arm's root.
ARM = [(460, 614), (480, 610), (500, 602), (520, 594), (535, 588), (545, 592), (552, 598), (570, 598), (582, 594),
       (588, 580), (596, 566), (606, 558), (618, 552), (624, 540), (624, 515), (630, 506), (640, 504), (655, 511),
       (670, 518), (684, 524), (693, 521), (697, 510), (692, 500), (680, 494), (665, 488), (650, 478), (648, 472), (652, 466), (670, 437), (690, 405), (711, 371), (722, 350), (750, 300),
       (798, 222), (846, 142), (858, 140), (858, 100), (850, 20), (820, 15), (760, 50), (722, 78), (718, 85),
       (673, 260), (658, 282), (638, 322), (618, 362), (603, 402), (598, 440), (597, 446), (580, 443), (560, 433),
       (545, 423), (533, 420), (528, 426), (530, 436), (545, 444), (560, 455), (572, 463), (578, 472), (566, 480),
       (556, 492), (545, 505), (535, 512), (520, 518), (495, 527), (470, 537), (458, 544), (456, 560), (456, 590)]
ELBOW = (468, 582)
ROOT_R = 27
SLEEVE = [(420, 540), (457, 543), (455, 562), (455, 592), (459, 618), (420, 632)]
# The blade, for the glow. Its outline is inside ARM; the blade is the pale part of it.
BLADE = [(596, 452), (604, 400), (640, 318), (672, 258), (718, 82), (762, 52), (820, 18), (852, 22), (858, 138),
         (836, 142), (720, 360), (686, 414), (650, 474)]
HILT = (590, 490)                           # where the blade leaves the guard
TIP = (826, 40)

# What the arm hides, painted in when it moves. The cap and its tail are behind most of
# it: CAP_BEHIND is where the cap carries on underneath, between its right-hand edge
# under the blade and the lower edge of its tail under the hand. Under the root of the
# arm is the shield on his back. Everything else under the arm is empty.
CAP_BEHIND = [(500, 380), (560, 300), (640, 240), (660, 268), (676, 300), (694, 336), (713, 374), (740, 440),
              (760, 600), (700, 650), (618, 563), (596, 551), (572, 540), (548, 532), (522, 529), (500, 533),
              (470, 541), (450, 520), (470, 440)]
SHIELD_BEHIND = [(440, 541), (470, 541), (500, 533), (522, 529), (513, 560), (512, 600), (514, 650), (440, 650)]
# The outlines that run under the arm, (points, width).
HIDDEN_EDGES = [
    ([(652, 252), (662, 272), (677, 302), (694, 336), (713, 374), (718, 386)], 5.5),    # cap's right edge
    ([(626, 570), (618, 563), (596, 551), (572, 540), (548, 532), (522, 529), (500, 533)], 5.0),  # cap tail's lower edge
    ([(512, 616), (512, 590), (513, 562), (516, 538)], 4.5),                            # shield's right edge
    ([(545, 417), (541, 429), (536, 441)], 3.5),                                        # tip of the ear
]

# The cap's long tail swings from about CAP_ROOT and is freest at CAP_TIP. CAP_TAIL is
# the part of the drawing that is tail (with the cap painted in under the arm).
CAP_TAIL = [(548, 400), (600, 330), (662, 270), (712, 372), (742, 450), (762, 560), (784, 690), (740, 700),
            (690, 665), (618, 563), (580, 545), (548, 520)]
CAP_ROOT, CAP_TIP = (585, 440), (760, 685)

# Legs. Each one is cut out below the tunic's hem, which is found column by column, and
# turns about a hip just under the hem. The far leg (left on screen) is drawn behind the
# near one, and both behind the tunic, so they can swing and tuck up under it.
LEG_BOX = {"far": (140, 318), "near": (318, 500)}         # columns of each leg
HEM_SEARCH = (835, 920)                                    # rows the hem is found in
HIP = {"far": (238, 872), "near": (393, 872)}
LEG_HIDDEN = 70                             # how far up the part under the tunic is painted
CROUCH = 84                                 # how far he sinks when his knees are fully bent

# Swaying bends him at the waist. Everything above SWAY_TOP_Y turns as one piece about
# SWAY_PIVOT, nothing below SWAY_BOTTOM_Y moves, and the body bends smoothly in between.
SWAY_TOP_Y, SWAY_BOTTOM_Y = 640, 860
SWAY_PIVOT = (320, 860)

# The face, for the back of his head in a spin: skin inside FACE becomes hair.
FACE = [(118, 400), (170, 330), (300, 300), (430, 330), (478, 400), (470, 520), (420, 575), (330, 600),
        (230, 590), (150, 545), (115, 480)]

# Strands of hair drawn over the back of his head.
BACK_STRANDS = [
    ([(190, 380), (180, 440), (172, 500), (178, 550)], [2, 4, 4, 1.5]),
    ([(255, 370), (250, 450), (246, 530), (252, 585)], [2, 4.5, 4.5, 1.5]),
    ([(325, 368), (330, 450), (334, 530), (326, 590)], [2, 4.5, 4.5, 1.5]),
    ([(395, 380), (408, 450), (414, 520), (404, 565)], [2, 4, 4, 1.5]),
]

INK = (0.14, 0.10, 0.06)
MOUTH_INK = (0.47, 0.17, 0.15)
MOUTH_IN = (0.94, 0.62, 0.56)
GLOW = (0.55, 0.86, 1.0)                    # the charged blade, and the ring it leaves
DEEP = (0.22, 0.52, 1.0)                    # the blue at the edge of the light
SPARK = (0.92, 0.98, 1.0)


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


def stroke(points, widths, closed=False):
    """A smooth tapering line through the points (Catmull-Rom), as coverage."""
    pts = np.array(points, np.float64)
    wd = np.broadcast_to(np.array(widths, np.float64), (len(pts),)).copy()
    if closed:
        pts = np.vstack([pts, pts[:1]])
        wd = np.append(wd, wd[0])
    dense, dw = catmull(pts, wd)

    def draw(c, px):
        for (x, y), r in zip(dense, dw / 2):
            cv2.circle(c, px(x, y), max(1, int(round(r * SS * 16))), 255, -1, cv2.LINE_8, shift=4)
    return coverage(draw)


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


def over(top, under):
    return top + under * (1 - top[..., 3:])


def membrane_fill(img, hole, valid, steps=1500):
    """Fills `hole` with colours that blend smoothly between the `valid` pixels round its
    edge (every filled pixel becomes the average of its usable neighbours). Pixels that
    are neither are left out, so outlines next to the hole do not bleed into it."""
    ys, xs = np.nonzero(hole)
    y0, y1, x0, x1 = max(0, ys.min() - 3), ys.max() + 4, max(0, xs.min() - 3), xs.max() + 4
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
    for _ in range(steps):
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


def compose(m2, m1):
    """The 2x3 matrix that applies m1, then m2."""
    a = np.vstack([m1, [0, 0, 1]])
    b = np.vstack([m2, [0, 0, 1]])
    return (b @ a)[:2]


def unpremultiply(img):
    a = img[..., 3:]
    rgb = np.where(a > 1e-4, img[..., :3] / np.maximum(a, 1e-4), 0)
    return np.dstack([np.clip(rgb, 0, 1), np.clip(a, 0, 1)])


def smoothstep(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


def colour_of(rgb, box, wanted=None):
    """Median colour of the solid pixels in a box (cutout pixels), optionally only those
    `wanted` picks out."""
    (bx0, by0), (bx1, by1) = to_canvas(box[0], box[1]), to_canvas(box[2], box[3])
    px = rgb[by0:by1, bx0:bx1].reshape(-1, 4)
    px = px[px[:, 3] > 0.95][:, :3]
    if wanted is not None:
        px = px[wanted(px)]
    return np.median(px, axis=0)


# ---------------------------------------------------------------- the face

class Face:
    def __init__(self, base):
        self.base = base                                    # premultiplied, canvas sized
        rgb = unpremultiply(base)
        r, g, b, a = rgb[..., 0], rgb[..., 1], rgb[..., 2], rgb[..., 3]
        # Skin is pale cream, with blush; his hair is a deeper yellow, less blue in it.
        self.skin = (r > 0.88) & (g > 0.74) & (b > 0.62) & (r - b > 0.05) & (b > 0.81 * g) & (a > 0.95)
        hair = (r > 0.8) & (g > 0.7) & (b < 0.81 * g) & (r - b > 0.15) & (a > 0.95)

        def around(marks, reach):
            d = cv2.distanceTransform((~marks).astype(np.uint8), cv2.DIST_L2, 5)
            return d <= reach

        # What gets painted out: the eye (or mouth) and the soft shading round it, which
        # would otherwise be left as a smudge. Colours are only taken from clean skin.
        self.eye_mask = {}
        for side, area in (("L", EYE_L_AREA), ("R", EYE_R_AREA)):
            inside = poly_mask(area) > 0.5
            marks = inside & ~self.skin & ~hair
            self.eye_mask[side] = around(marks, EYE_REACH) & inside
        inside = poly_mask(MOUTH_AREA) > 0.5
        self.mouth_mask = around(inside & ~self.skin, 5) & inside
        clean = cv2.erode(self.skin.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0

        bare = base
        for side in "LR":
            bare = membrane_fill(bare, self.eye_mask[side], clean)
        self.bare_eyes = bare
        self.bare_mouth = membrane_fill(base, self.mouth_mask, clean)
        self.eye_box = {}
        for side in "LR":
            ys, xs = np.nonzero(self.eye_mask[side])
            self.eye_box[side] = (xs.min(), ys.min(), xs.max(), ys.max())

        # The back of his head: the face and everything on it become hair, in the colours
        # of the hair round it, with a few strands drawn through it. The outline of the
        # jaw stays, as the line of his hair at the nape.
        face = (poly_mask(FACE) > 0.5) & (a > 0.5)
        on_face = self.skin | self.eye_mask["L"] | self.eye_mask["R"] | self.mouth_mask
        on_face = cv2.morphologyEx(on_face.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)) > 0
        on_face &= face
        self.back = membrane_fill(base, on_face, hair & ~on_face, steps=800)
        hair_px = rgb[hair][:, :3]
        shade = np.median(hair_px[hair_px.sum(1) < np.percentile(hair_px.sum(1), 8)], axis=0)
        strands = np.maximum.reduce([stroke(pts, w) for pts, w in BACK_STRANDS]) * on_face
        self.back = paint(self.back, strands * 0.8, shade)
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
        # Part way shut, narrowed, or wide: the drawn eye itself, squeezed or enlarged.
        x0, y0, x1, y1 = self.eye_box[side]
        layer, _ = self.eye_layer(side)
        cx = (x0 + x1) / 2
        if state == "wide":
            m = about(cx, (y0 + y1) / 2, 0, 1.06, 1.1)
        elif state == "narrow":                             # the upper lid comes down
            pts, wid = LID[side]
            below = shape(np.array(pts + [(pts[-1][0] + 30, y1 + Y0 + 40), (pts[0][0] - 30, y1 + Y0 + 40)]))
            low = layer * below[..., None]
            return paint(low + bare * (1 - low[..., 3:]), stroke(pts, wid), INK)
        else:                                               # a number: how far shut
            m = about(cx, y1 - 0.12 * (y1 - y0), 0, 1.0 + 0.04 * state, 1 - 0.85 * state)
        moved = transform(layer, m)
        return moved + bare * (1 - moved[..., 3:])

    def draw_mouth(self, img, mouth):
        if mouth == "open":
            return img
        soft = cv2.GaussianBlur(self.mouth_mask.astype(np.float32), (0, 0), 0.8)[..., None]
        bare = img * (1 - soft) + self.bare_mouth * soft
        if mouth in ("shout", "o"):
            # The drawn mouth itself, opened wider and deeper, or pursed small.
            layer = self.base * soft
            cx, cy = to_canvas(*MOUTH_TOP)
            m = about(cx, cy, 0, 1.08, 1.2) if mouth == "shout" else about(cx, cy + 22, 0, 0.42, 0.72)
            moved = transform(layer, m)
            return moved + bare * (1 - moved[..., 3:])
        if mouth == "smile":
            cov = stroke([(266, 532), (282, 543), (301, 547), (320, 542), (335, 531)], [2.2, 4, 4.8, 4, 2.2])
            return paint(bare, cov, MOUTH_INK)
        if mouth == "firm":
            cov = stroke([(276, 543), (290, 540), (306, 541), (322, 537)], [2.4, 4.4, 4.4, 2.4])
            return paint(bare, cov, MOUTH_INK)
        raise ValueError(mouth)

    def get(self, eyes=("open", "open"), mouth="open", frown=False, back=False):
        key = (eyes, mouth, frown, back)
        if key not in self._cache:
            if back:
                img = self.back
            else:
                img = self.base
                img = self.draw_eye(img, "L", eyes[0])
                img = self.draw_eye(img, "R", eyes[1])
                img = self.draw_mouth(img, mouth)
                if frown:
                    cov = np.maximum(stroke(*FROWN["L"]), stroke(*FROWN["R"]))
                    img = paint(img, cov, INK)
            self._cache[key] = img
        return self._cache[key]


# ---------------------------------------------------------------- the rig

class Rig:
    def __init__(self):
        self.base = load_base()
        rgb = unpremultiply(self.base)
        a = rgb[..., 3]
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        self.grid = (xx, yy)

        # Feet, in cutout pixels: the bottom of the drawing, centred between the two soles.
        ys, xs = np.nonzero(a > 0.5)
        soles = xs[ys > ys.max() - 60]
        self.feet = ((soles.min() + soles.max()) / 2 + X0, float(ys.max()) + 1 + Y0)

        # ---- the sword arm, and what is behind it
        # The traced outline runs along the arm's own ink, so the ink just outside it is
        # taken too, or a sliver of it would be left behind when the arm moves.
        traced = poly_mask(ARM) > 0.5
        ink = (rgb[..., :3].max(-1) < 0.45) & (a > 0.3)
        reach = cv2.dilate(traced.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))) > 0
        grown = traced | (reach & ink)
        grown = cv2.dilate(grown.astype(np.uint8), np.ones((2, 2), np.uint8)) > 0
        arm_mask = cv2.GaussianBlur(grown.astype(np.float32), (0, 0), 0.6)
        self.arm = self.base * arm_mask[..., None]
        cap_px = (rgb[..., 1] > rgb[..., 0] + 0.02) & (rgb[..., 1] > rgb[..., 2] + 0.02) & (a > 0.95)
        hole = arm_mask > 0.02
        cap_in = (poly_mask(CAP_BEHIND) > 0.5) & hole
        shield_in = (poly_mask(SHIELD_BEHIND) > 0.5) & hole & ~cap_in
        # Under the arm, the cap carries on in its own colours, and so does the shield.
        cap_fill = membrane_fill(self.base, cap_in, cap_px & ~hole)
        shield_colour = colour_of(rgb, (462, 616, 508, 660), lambda c: c.max(1) > 0.45)
        behind = np.zeros_like(self.base)
        cap_soft = cv2.GaussianBlur(cap_in.astype(np.float32), (0, 0), 0.7)
        shield_soft = cv2.GaussianBlur(shield_in.astype(np.float32), (0, 0), 0.7)
        behind[..., :3] = cap_fill[..., :3] * cap_soft[..., None] + np.array(shield_colour) * shield_soft[..., None]
        behind[..., 3] = np.clip(cap_soft + shield_soft, 0, 1)
        behind[..., :3] = np.minimum(behind[..., :3], behind[..., 3:])
        cap_ink = colour_of(rgb, (600, 150, 650, 250), lambda c: c.max(1) < 0.45)
        for pts, width in HIDDEN_EDGES:
            behind = paint(behind, stroke(pts, width) * (hole | (behind[..., 3] > 0.5)), cap_ink)
        self.arm_gone = arm_mask
        self.behind = behind
        self.sleeve = poly_mask(SLEEVE, 0.6)
        # A disc of bracer at the elbow, under the arm, so it never comes apart there.
        ex, ey = to_canvas(*ELBOW)
        root = np.zeros((H, W), np.float32)
        cv2.circle(root, (int(ex), int(ey)), ROOT_R, 1.0, -1, cv2.LINE_AA)
        root = cv2.GaussianBlur(root, (0, 0), 0.7)
        bracer = colour_of(rgb, (470, 560, 520, 600), lambda c: c.max(1) < 0.45)
        self.arm = over(self.arm, np.dstack([np.broadcast_to(bracer, (H, W, 3)) * root[..., None], root]))
        # The blade's pale steel, for the glow.
        blade = (poly_mask(BLADE) > 0.5) & (rgb[..., :3].min(-1) > 0.72) & (a > 0.5)
        self.blade = cv2.GaussianBlur(blade.astype(np.float32), (0, 0), 1.0)
        # Halos round it, scaled so they are at full strength along the steel's edge.
        edge = cv2.dilate(blade.astype(np.uint8), np.ones((3, 3), np.uint8)) > blade
        self.halo = cv2.GaussianBlur(blade.astype(np.float32), (0, 0), 14)
        self.halo = np.clip(self.halo / np.median(self.halo[edge]), 0, 1)
        self.halo_wide = cv2.GaussianBlur(blade.astype(np.float32), (0, 0), 42)
        self.halo_wide = np.clip(self.halo_wide / np.median(self.halo_wide[edge]), 0, 1)

        # The body without the arm, before the face is drawn on: what the face
        # variants are made from.
        body = over(behind, self.base * (1 - arm_mask[..., None]))
        self.face = Face(body)

        # ---- the cap's tail
        tail = poly_mask(CAP_TAIL, 12)
        rx, ry = to_canvas(*CAP_ROOT)
        tx, ty = to_canvas(*CAP_TIP)
        ax, ay = tx - rx, ty - ry
        along = ((xx - rx) * ax + (yy - ry) * ay) / (ax * ax + ay * ay)
        self.cap_w = cv2.GaussianBlur(smoothstep(along) ** 1.3 * tail, (0, 0), 6)

        # ---- legs: cut along the hem, found column by column as the first row of
        # stocking under the tunic.
        lum = rgb[..., :3].mean(-1)
        sat = rgb[..., :3].max(-1) - rgb[..., :3].min(-1)
        tights = (lum > 0.6) & (lum < 0.85) & (sat < 0.12) & (a > 0.95)
        s0, s1 = (v - Y0 for v in HEM_SEARCH)
        self.leg, self.leg_outline = {}, {}
        legs_mask = np.zeros((H, W), np.float32)
        exact = {}
        for name, (c0, c1) in LEG_BOX.items():
            cx0, cx1 = c0 - X0, c1 - X0
            top = np.full(W, -1)
            for x in range(cx0, cx1):
                col = tights[s0:s1, x]
                run = np.convolve(col.astype(int), np.ones(5, int), "valid") == 5
                if run.any():
                    top[x] = s0 + int(np.argmax(run))
            have = np.nonzero(top >= 0)[0]
            # Columns of outline at the leg's sides have no stocking: they take the hem
            # of the nearest column that does, a little lower, so the tunic keeps them.
            for x in range(cx0, cx1):
                if top[x] < 0:
                    near = have[np.argmin(np.abs(have - x))]
                    top[x] = top[near] + 4
            m = np.zeros((H, W), np.float32)
            for x in range(cx0, cx1):
                m[top[x] - 1:, x] = 1
            m *= (a > 0.02)
            exact[name] = cv2.GaussianBlur(m, (0, 0), 0.5)
            legs_mask = np.maximum(legs_mask, exact[name])
        self.legs_mask = legs_mask
        for name in ("far", "near"):
            hard = exact[name] > 0.5
            contours, _ = cv2.findContours((hard & (a > 0.5)).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            self.leg_outline[name] = max(contours, key=cv2.contourArea)[:, 0, :].astype(np.float64)
            wide = cv2.dilate(exact[name], np.ones((3, 3), np.uint8))
            layer = self.base * wide[..., None]
            leg_px = rgb[hard & tights][:, :3]
            stocking = np.median(leg_px, axis=0)
            outline = colour_of(rgb, (180, 880, 205, 940), lambda c: c.max(1) < 0.4)
            hidden = np.zeros((H, W), np.float32)
            colour = np.zeros((H, W, 3), np.float32)
            cols = np.nonzero(hard.any(axis=0))[0]
            top_rows = {x: int(np.nonzero(hard[:, x])[0].min()) for x in cols}
            # Only the stretch of leg that meets the hem carries on up under it.
            hem_cols = [x for x in cols if top_rows[x] < s1 - 10]
            x_from, x_to = min(hem_cols), max(hem_cols)
            for x in range(x_from, x_to + 1):
                t = top_rows.get(x, top_rows[min(hem_cols, key=lambda c: abs(c - x))])
                edge = min(x - x_from, x_to - x) < 4
                colour[t - LEG_HIDDEN:t + 3, x] = outline if edge else stocking
                hidden[t - LEG_HIDDEN:t + 3, x] = 1
            hidden = cv2.GaussianBlur(hidden, (0, 0), 0.7)
            colour = cv2.GaussianBlur(colour, (0, 0), 0.9)
            self.leg[name] = over(layer, np.dstack([colour * hidden[..., None], hidden]))

        self.sway_w = smoothstep((SWAY_BOTTOM_Y - Y0 - yy) / (SWAY_BOTTOM_Y - SWAY_TOP_Y))

    # ---- parts

    def cap_pose(self, img, cap):
        """cap: (dx, dy), how far the tip of the cap's tail moves."""
        if abs(cap[0]) < 1e-3 and abs(cap[1]) < 1e-3:
            return img
        xx, yy = self.grid
        return cv2.remap(img, (xx - self.cap_w * cap[0]).astype(np.float32), (yy - self.cap_w * cap[1]).astype(np.float32),
                         cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT).clip(0, 1)

    def legs_pose(self, img, legs, lift, crouch):
        """legs: degrees each leg swings back (far, near; negative is forward). lift: pixels
        each foot is raised. crouch: 0..1, how far the knees are bent, which tucks both
        legs up under the tunic."""
        if not (any(legs) or any(lift) or crouch):
            return img
        under = None
        for name, deg, up in (("near", legs[1], lift[1]), ("far", legs[0], lift[0])):
            hx, hy = to_canvas(*HIP[name])
            layer = transform(self.leg[name], about(hx, hy, deg, dy=-up - crouch * CROUCH))
            under = layer if under is None else over(under, layer)
        body = img * (1 - self.legs_mask[..., None])
        return over(body, under)

    def foot_drop(self, name, deg):
        """How far below its resting level the lowest point of a leg ends up when the leg is
        turned by deg (negative if it rises). Raising the leg by this much keeps the foot on
        the floor."""
        hx, hy = to_canvas(*HIP[name])
        pts = self.leg_outline[name]
        c, s_ = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        return float((hy + (pts[:, 0] - hx) * s_ + (pts[:, 1] - hy) * c).max() - pts[:, 1].max())

    def sway_pose(self, img, deg):
        if abs(deg) < 1e-3:
            return img
        xx, yy = self.grid
        px, py = to_canvas(*SWAY_PIVOT)
        vx, vy = xx - px, yy - py
        phi = np.radians(deg) * self.sway_w
        c, s_ = np.cos(phi), np.sin(phi)
        return cv2.remap(img, (px + vx * c + vy * s_).astype(np.float32), (py - vx * s_ + vy * c).astype(np.float32),
                         cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT).clip(0, 1)

    def arm_matrix(self, arm, sway=0.0):
        """Where the arm layer goes: turned `arm` degrees at the elbow (positive lowers the
        sword to his left, our right), then carried round with his shoulders."""
        ex, ey = to_canvas(*ELBOW)
        m = about(ex, ey, arm)
        if sway:
            px, py = to_canvas(*SWAY_PIVOT)
            w = float(smoothstep((py - ey) / (SWAY_BOTTOM_Y - SWAY_TOP_Y)))
            m = compose(about(px, py, -sway * w), m)
        return m

    def arm_layer(self, arm, sway, glow):
        layer = self.arm
        if glow > 0:
            # The steel brightens and a halo spreads round it.
            g = np.clip(glow, 0, 1.5)
            lit = layer.copy()
            tint = self.blade[..., None] * min(g, 1) * lit[..., 3:]
            lit[..., :3] = lit[..., :3] * (1 - 0.35 * tint) + np.array(GLOW) * 0.35 * tint + 0.25 * tint
            lit[..., :3] = np.minimum(lit[..., :3], lit[..., 3:])
            near = np.clip(self.halo ** 1.5 * 0.95 * g, 0, 1)
            far = np.clip(self.halo_wide ** 1.2 * 0.75 * g, 0, 1)
            # A pale halo close to the steel inside a wider deep blue one: it shows on a
            # light desktop as well as a dark one.
            glow_layer = over(np.dstack([np.broadcast_to(GLOW, (H, W, 3)) * near[..., None], near]),
                              np.dstack([np.broadcast_to(DEEP, (H, W, 3)) * far[..., None], far]))
            layer = over(lit, glow_layer)
        return transform(layer, self.arm_matrix(arm, sway))

    def body_matrix(self, lean=0.0, squash=0.0, dx=0.0, dy=0.0, crouch=0.0, **_):
        fx, fy = to_canvas(*self.feet)
        return about(fx, fy, lean, 1 + 0.6 * squash, 1 - squash, dx, dy + crouch * CROUCH)

    def place(self, point, sway=0.0, **body):
        """Where a point of the drawing (cutout pixels) ends up on the canvas in a pose."""
        x, y = to_canvas(*point)
        px, py = to_canvas(*SWAY_PIVOT)
        w = float(smoothstep((py - y) / (SWAY_BOTTOM_Y - SWAY_TOP_Y)))
        c, s_ = math.cos(math.radians(sway * w)), math.sin(math.radians(sway * w))
        x, y = px + (x - px) * c - (y - py) * s_, py + (x - px) * s_ + (y - py) * c
        return self.body_matrix(**body) @ np.array([x, y, 1.0])

    def place_on_arm(self, point, arm=0.0, sway=0.0, **body):
        """Where a point of the arm layer (cutout pixels) ends up on the canvas."""
        x, y = to_canvas(*point)
        p = self.arm_matrix(arm, sway) @ np.array([x, y, 1.0])
        return self.body_matrix(**body) @ np.array([p[0], p[1], 1.0])

    def layers(self, eyes=("open", "open"), mouth="open", frown=False, back=False, arm=0.0, glow=0.0, cap=(0.0, 0.0),
               sway=0.0, legs=(0.0, 0.0), lift=(0.0, 0.0), crouch=0.0, lean=0.0, squash=0.0, dx=0.0, dy=0.0,
               planted=False, **_):
        """The body and the sword arm, each placed on the canvas but kept apart, so a turn
        can tell which is in front. With `planted`, the point of the sword is stuck in the
        ground: whatever of it reaches below the floor is not drawn."""
        body = self.face.get(tuple(eyes), mouth, frown, back)
        body = self.cap_pose(body, cap)
        body = self.legs_pose(body, legs, lift, crouch)
        body = self.sway_pose(body, sway)
        arm_img = self.arm_layer(arm, sway, glow)
        sleeve = body * self.sway_pose(self.sleeve[..., None].repeat(4, -1), sway)[..., :1]
        m = self.body_matrix(lean, squash, dx, dy, crouch)
        if lean or squash or dx or dy or crouch:
            body, arm_img, sleeve = transform(body, m), transform(arm_img, m), transform(sleeve, m)
        if planted:
            _, fy = to_canvas(*self.feet)
            floor = np.clip((fy - 6 - self.grid[1]) / 3, 0, 1)
            arm_img = arm_img * floor[..., None]
        return body, arm_img, sleeve

    def pose(self, **spec):
        fx_back, fx_front = effects(self, spec)
        body, arm_img, sleeve = self.layers(**spec)
        img = over(sleeve, over(arm_img, body))
        if fx_back is not None:
            img = over(img, fx_back)
        if fx_front is not None:
            img = over(fx_front, img)
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


# ---------------------------------------------------------------- effects

def sparkle(cx, cy, size, angle=0.0):
    """A four-pointed star as coverage, centred on canvas pixel (cx, cy)."""
    pts = []
    for i in range(8):
        r = size if i % 2 == 0 else size * 0.22
        t = math.radians(angle) + i * math.pi / 4
        pts.append((cx + X0 + r * math.cos(t), cy + Y0 + r * math.sin(t)))
    return shape(np.array(pts))


def glow_layer(cov, colour, blur=6.0, strength=0.8):
    """A soft-edged light: the shape itself in white-hot colour, with a coloured halo
    that deepens to blue at its edge."""
    halo = np.clip(cv2.GaussianBlur(cov, (0, 0), blur) * strength * 1.6, 0, 1)
    a = np.clip(np.maximum(cov, halo * 0.85), 0, 1)
    core = np.clip(cov, 0, 1)[..., None]
    edge = np.array(DEEP, np.float32) + (np.array(colour, np.float32) - np.array(DEEP, np.float32)) * halo[..., None]
    rgb = edge * (1 - core) + np.array(SPARK, np.float32) * core
    return np.dstack([rgb * a[..., None], a])


def effects(rig, spec):
    """The lights a pose asks for, as (behind him, in front of him), on the canvas."""
    back = front = None
    for kind, args in spec.get("fx", []):
        if kind == "sparkles":
            cov = np.zeros((H, W), np.float32)
            for x, y, size, ang in args:
                cov = np.maximum(cov, sparkle(x, y, size, ang))
            layer = glow_layer(cov, GLOW, 5, 1.0)
            front = layer if front is None else over(layer, front)
        elif kind == "ring":
            b, f = ring_layers(*args)
            back = b if back is None else over(back, b)
            front = f if front is None else over(f, front)
    return back, front


def ring_layers(cx, cy, rx, ry, start, end, width, fade=1.0):
    """The light a spinning blade leaves: an elliptical band swept from angle `start` to
    `end` (degrees, 0 is to our right, 90 nearest us), brightest at `end`, where the blade
    is now, and fading out behind it. The rim, where the point passes, is a white-hot line
    edged in deep blue; inside it the band is paler, with a couple of streaks of speed.
    The part on the far side of him is returned separately, to go behind him."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    u, v = (xx - cx) / rx, (yy - cy) / ry
    r = np.sqrt(u * u + v * v) + 1e-6
    # Distance in pixels from the ellipse r = k is about (r - k) / |grad r|.
    grad = np.sqrt((u / rx) ** 2 + (v / ry) ** 2) / r + 1e-9
    ang = np.degrees(np.arctan2(v, u))                     # 90 at the front, -90 at the back
    behind_by = (end - ang) % 360
    span = max(1e-3, end - start)
    along = np.clip(1 - behind_by / span, 0, 1) * (behind_by <= span)
    r_in = 1 - width

    def line(k, px):
        return np.clip(1 - np.abs((r - k) / grad) / px, 0, 1)
    band = np.clip((r - r_in) / width, 0, 1) ** 1.6 * (r <= 1)
    rim = line(1.0, 4.0)
    rim_glow = np.clip(1 - np.abs((r - 1.0) / grad) / 16.0, 0, 1) ** 2
    edge = np.maximum(line(1.0 + 10 * float(np.median(grad)), 3.5), line(1.0 - 10 * float(np.median(grad)), 2.5) * 0.6)
    speed = np.maximum(line(1 - width * 0.3, 2.0), line(1 - width * 0.58, 1.6)) * 0.7

    fade_a = along ** 1.3 * fade
    def layer_of(cov, colour):
        a = np.clip(cov * fade_a, 0, 1)
        return np.dstack([np.broadcast_to(np.array(colour, np.float32), (H, W, 3)) * a[..., None], a])
    pale = tuple(0.5 * g + 0.5 * d for g, d in zip(GLOW, DEEP))
    layer = layer_of(band * 0.5, pale)
    layer = over(layer_of(speed, SPARK), layer)
    layer = over(layer_of(rim_glow * 0.85, GLOW), layer)
    layer = over(layer_of(edge, DEEP), layer)
    layer = over(layer_of(rim, SPARK), layer)
    front_side = (np.sin(np.radians(ang)) > 0).astype(np.float32)
    front_side = cv2.GaussianBlur(front_side, (0, 0), 6)[..., None]
    return layer * (1 - front_side) * 0.75, layer * front_side


# ---------------------------------------------------------------- cap physics

class Cap:
    """The cap's tail is a damped spring hung from his head. When he moves, the tip is
    left behind and swings back, so it lags, overshoots and settles.

    body(t) gives the body pose (lean, sway, crouch, dx, dy...) at time t; push(t) an extra
    force (a breeze, a flutter). The clip is a loop, so the spring is run for a few turns
    first and the last one is kept, which makes the loop seamless."""

    def __init__(self, rig, body, push=None, period=1.0, stiffness=90.0, damping=5.0, gain=1.0, limit=60.0):
        self.body, self.push = body, push or (lambda t: (0, 0))
        self.period, self.limit = period, limit
        dt = 1 / 480
        steps = int(round(period / dt))

        def where(t):
            return rig.place(CAP_TIP, **{k: v for k, v in body(t).items() if k in ("sway", "lean", "squash", "dx", "dy", "crouch")})

        o, v = np.zeros(2), np.zeros(2)
        for _ in range(4):
            rec = []
            for i in range(steps):
                t = i * dt
                acc = (where(t + dt) - 2 * where(t) + where(t - dt)) / (dt * dt)
                f = np.array(self.push(t), float)
                v += (-stiffness * o - damping * v - gain * acc + f) * dt
                o += v * dt
                rec.append(o.copy())
        self.track = np.array(rec)

    def at(self, t):
        i = int(round((t % self.period) * 480)) % len(self.track)
        pose = self.body(t)
        lean = math.radians(pose.get("lean", 0.0) + 0.8 * pose.get("sway", 0.0))
        c, s = math.cos(-lean), math.sin(-lean)
        ox, oy = self.track[i]
        bx, by = c * ox - s * oy, 0.6 * (s * ox + c * oy)
        return (self.limit * math.tanh(bx / self.limit), self.limit * math.tanh(by / self.limit))


def frames_from(times, pose_at):
    """Samples pose_at(t) at the given times; each frame lasts until the next one."""
    return [(pose_at(t), (times[i + 1] - t) * 1000) for i, t in enumerate(times[:-1])]


def even(period, fps, start=0.0):
    n = max(1, int(round(period * fps)))
    return [start + period * i / n for i in range(n + 1)]


def bump(t, start, length):
    """0 -> 1 -> 0 over [start, start + length], smooth."""
    u = (t - start) / length
    return math.sin(math.pi * u) ** 2 if 0 <= u <= 1 else 0.0


def ramp(t, start, length):
    """0 before start, 1 after start + length, smooth in between."""
    u = min(1.0, max(0.0, (t - start) / length))
    return u * u * (3 - 2 * u)


# ---------------------------------------------------------------- the clips

OPEN, SHUT, HAPPY_EYES, WIDE, NARROW = ("open", "open"), ("closed", "closed"), ("happy", "happy"), ("wide", "wide"), \
    ("narrow", "narrow")


def blink(frames, **held):
    """Adds a blink; `held` is the rest of the pose he keeps while he does it."""
    for eyes, ms in (((0.5, 0.5), 40), (SHUT, 70), ((0.5, 0.5), 50)):
        frames.append((dict(held, eyes=eyes), ms))


def idle(rig):
    """Mostly still, which the app breathes for him. Blinks, a breeze through the cap, a
    tilt of the head, and now and then a twirl of the sword."""
    f = [(dict(), 2200)]
    blink(f)
    f.append((dict(), 1300))

    # A breeze lifts the tail of his cap and lets it go.
    def breeze(t):
        b = bump(t, 0.0, 1.4)
        return (900 * b, -420 * b)
    cap = Cap(rig, lambda t: {}, breeze, period=4.0, stiffness=60, damping=4.5)
    f += frames_from(even(2.0, 8), lambda t: dict(cap=cap.at(t)))
    f.append((dict(), 1000))
    blink(f)
    f.append((dict(), 110))
    blink(f)
    f.append((dict(), 900))

    # He tips his head and shoulders to one side, holds it, and comes back.
    for sway, ms in ((-1.5, 60), (-3.4, 60), (-4.2, 1100), (-2.8, 60), (-1.1, 60)):
        f.append((dict(sway=sway, cap=(2.5 * sway, 0)), ms))
    f.append((dict(), 1100))

    # A flourish: the sword dips, comes up high with a glint, and settles.
    def flourish(t):
        arm = 16 * bump(t, 0.0, 0.5) - 14 * bump(t, 0.35, 0.7)
        return dict(arm=arm, eyes=HAPPY_EYES if 0.45 < t < 1.05 else OPEN, sway=-1.5 * bump(t, 0.3, 0.8))
    cap2 = Cap(rig, flourish, period=1.4)
    tip_at = lambda t: rig.place_on_arm(TIP, **flourish(t))
    def flourish_pose(t):
        p = flourish(t)
        glint = bump(t, 0.6, 0.45)
        if glint > 0.05:
            x, y = tip_at(t)
            p["fx"] = [("sparkles", [(x - 12, y + 20, 52 * glint, 15 * t)])]
        return dict(p, cap=cap2.at(t))
    f += frames_from(even(1.4, 12), flourish_pose)
    f.append((dict(), 1500))
    blink(f)
    f.append((dict(), 800))
    return f


def walk(rig):
    """One stride (two steps). With a walk clip the app adds no motion of its own, so the
    bob and the lean are drawn in. The legs swing from under the tunic; each foot stays
    planted on the floor while it travels back and is picked up as it comes forward, and
    the body dips when both feet are down. The sword rides along, bobbing with his steps."""
    period, swing, step = 0.44, 17.0, 12.0

    def body(t):
        p = 2 * math.pi * t / period
        s, c = math.sin(p), math.cos(p)
        dy = 3 - 6 * c * c
        legs = (swing * s, -swing * s)
        height = (step * max(0.0, -c), step * max(0.0, c))
        lift = tuple(h + rig.foot_drop(name, deg) + dy for name, deg, h in zip(("far", "near"), legs, height))
        return dict(legs=legs, lift=lift, dy=dy, lean=2.5, sway=1.5 * s)
    cap = Cap(rig, body, period=period, stiffness=150, damping=7)
    return frames_from(even(period, 20), lambda t: dict(
        arm=4 + 4 * math.cos(4 * math.pi * t / period), cap=cap.at(t), **body(t)))


def sit(rig):
    """Kneeling, with the point of his sword stuck in the ground beside him: blinks, and a
    contented moment."""
    held = dict(crouch=1.0, arm=148, planted=True, cap=(10, 14))
    f = [(held, 2000)]
    blink(f, **held)
    f.append((held, 1500))
    f.append((dict(held, sway=-1.0), 60))
    f.append((dict(held, sway=-2.2, eyes=HAPPY_EYES, mouth="smile"), 1300))
    f.append((dict(held, sway=-1.0), 60))
    f.append((held, 1200))
    blink(f, **held)
    f.append((held, 600))
    return f


def sword_pump(rig):
    """Shown during every built-in dance move, which adds its own bounces, leans and spins,
    so his feet stay still here. Two beats at 120 BPM: the sword punches up on each beat
    and comes back down between them, he cheers on one beat and grins on the other, sways
    at the waist, and the tail of his cap bounces along."""
    period = 1.0

    def body(t):
        return dict(sway=-3.0 * math.sin(2 * math.pi * t / period))
    cap = Cap(rig, lambda t: dict(body(t), dy=-12 * abs(math.sin(2 * math.pi * t / period))), period=period)

    def at(t):
        beat = t / (period / 2)
        u = beat % 1
        # Up fast on the beat, down slowly after it.
        arm = -16 * (ramp(u, 0.0, 0.15) - ramp(u, 0.3, 0.6)) + 10 * ramp(u, 0.3, 0.6) * (1 - ramp(u, 0.85, 0.15))
        return dict(eyes=HAPPY_EYES, mouth="shout" if int(beat) % 2 == 0 and u < 0.6 else "open", arm=arm,
                    cap=cap.at(t), **body(t))
    return frames_from(even(period, 16), at)


# ---- the Spin Attack

SPIN_CHARGE_ARM = 90                        # sword held low at his side while it charges
SPIN_ARM = 62                               # sword out level for the spin
SPIN_TILT = 0.22                            # how far above him we look from: the sine of the angle


def spin_attack(rig):
    """Four beats (2 s at 120 BPM). He drops into a crouch with the sword low at his side,
    and it charges: the blade glows brighter and brighter while sparks gather on it. Then
    he spins round twice with the sword held out level, leaving a ring of light, and comes
    out of it facing us with the sword held high in a shower of sparks."""
    charge_end, spin_start, spin_end = 0.82, 0.92, 1.5
    turns = 2

    def turn_at(t):
        u = min(1.0, max(0.0, (t - spin_start) / (spin_end - spin_start)))
        # Quick out of the blocks, easing off at the end.
        return 360.0 * turns * (1 - (1 - u) ** 2.2) if t >= spin_start else 0.0

    def body(t):
        crouch = 0.42 * ramp(t, 0.0, 0.2) * (1 - ramp(t, 0.84, 0.12)) + 0.16 * bump(t, 1.48, 0.22)
        shake = 2.5 * math.sin(2 * math.pi * 23 * t) * ramp(t, 0.3, 0.4) * (1 - ramp(t, 0.8, 0.05))
        lean = 5 * ramp(t, 0.0, 0.2) * (1 - ramp(t, 0.82, 0.1)) - 3 * bump(t, 0.82, 0.16)
        hop = math.sin(math.pi * (t - 0.9) / 0.6) if 0.9 <= t <= 1.5 else 0.0
        return dict(crouch=crouch, dx=shake, lean=lean, dy=-16 * hop, sway=-3 * ramp(t, 0.05, 0.2) * (1 - ramp(t, 0.8, 0.1)))

    def arm_at(t):
        if t < spin_start:
            a = SPIN_CHARGE_ARM * ramp(t, 0.02, 0.2)
            return a + (SPIN_ARM - SPIN_CHARGE_ARM) * ramp(t, 0.8, 0.12)
        if t < spin_end:
            return SPIN_ARM
        return SPIN_ARM + (-16 - SPIN_ARM) * ramp(t, spin_end, 0.16) + 16 * ramp(t, 1.78, 0.22)

    def glow_at(t):
        g = 1.1 * ramp(t, 0.15, 0.62) + 0.3 * bump(t, 0.74, 0.12)
        g *= 1 + 0.18 * math.sin(2 * math.pi * 7 * t) * ramp(t, 0.2, 0.3) * (1 - ramp(t, 0.7, 0.1))
        g *= 1 - 0.55 * ramp(t, spin_end + 0.05, 0.4)
        return g

    # The cap's tail is flung out by the spin: a push away from the way he turns.
    def push(t):
        if spin_start <= t <= spin_end + 0.2:
            return (-2600 * math.sin(math.radians(turn_at(t))), -900)
        return (0, 0)
    cap = Cap(rig, body, push, period=2.0, stiffness=80, damping=5.0, limit=70)

    elbow = to_canvas(*ELBOW)

    def at(t):
        b = body(t)
        theta = turn_at(t)
        spec = dict(arm=arm_at(t), glow=glow_at(t), cap=cap.at(t), **b)
        if t < 0.18:
            spec.update(eyes=OPEN, mouth="firm")
        elif t < spin_start:
            spec.update(eyes=NARROW, frown=True, mouth="firm")
        elif t < spin_end:
            spec.update(eyes=NARROW, frown=True, mouth="shout")
        elif t < spin_end + 0.12:
            spec.update(eyes=OPEN, mouth="shout")
        else:
            spec.update(eyes=HAPPY_EYES, mouth="open")
        fx = []
        # Sparks drawn in to the blade while it charges.
        if 0.15 < t < spin_start:
            pts = []
            for k in range(7):
                u = ((t - 0.15) * 1.9 + k / 7) % 1
                along = 0.25 + 0.7 * ((k * 0.37) % 1)
                x, y = point_on_blade(rig, along, arm=arm_at(t), **b)
                ang = 2 * math.pi * ((k * 0.61) % 1)
                dist = 150 * (1 - u)
                pts.append((x + dist * math.cos(ang), y + dist * math.sin(ang), 26 * math.sin(math.pi * u) + 4, 45 * u))
            fx.append(("sparkles", pts))
        # The ring of light, from the start of the spin until it fades after.
        if t >= spin_start:
            fx.append(("ring", ring_args(rig, t, theta, spin_start, spin_end)))
        # A shower of sparks as he comes out of it.
        if spin_end - 0.05 < t < 2.0:
            u = (t - spin_end + 0.05) / 0.55
            tip = rig.place_on_arm(TIP, arm=arm_at(t), **b)
            pts = []
            for k in range(9):
                ang = 2 * math.pi * k / 9 + 0.4
                r = 40 + 260 * u ** 0.6 * (0.7 + 0.3 * ((k * 0.53) % 1))
                size = 38 * (1 - u) ** 1.2 * (0.6 + 0.4 * ((k * 0.71) % 1))
                if size > 2:
                    pts.append((tip[0] + r * math.cos(ang), tip[1] + r * math.sin(ang) + 40 * u * u, size, 30 * u + k * 10))
            if pts:
                fx.append(("sparkles", pts))
        spec["fx"] = fx
        spec["turn"] = theta
        # The blur covers what the turn sweeps through in half a frame at 30 a second.
        spec["smear"] = max(0.0, theta - turn_at(t - 1 / 60))
        return spec

    times = even(spin_start, 12)[:-1] + even(spin_end - spin_start, 30, spin_start)[:-1] + even(2.0 - spin_end, 12, spin_end)
    return frames_from(times, at)


def point_on_blade(rig, along, **pose):
    """A point `along` the blade from the guard (0) to the tip (1), on the canvas."""
    x = HILT[0] + (TIP[0] - HILT[0]) * along
    y = HILT[1] + (TIP[1] - HILT[1]) * along
    return rig.place_on_arm((x, y), **pose)


def ring_args(rig, t, theta, spin_start, spin_end):
    """The ring's ellipse round his upright axis at the height of the blade, the part of
    it swept so far, and how far it has faded."""
    pose = dict(arm=SPIN_ARM)
    tip = rig.place_on_arm(TIP, **pose)
    hilt = rig.place_on_arm(HILT, **pose)
    fx, _ = to_canvas(*rig.feet)
    rx = abs(tip[0] - fx) * 1.02
    ry = rx * SPIN_TILT
    cy = (tip[1] + hilt[1]) / 2 + 10
    width = 1 - abs(hilt[0] - fx) / rx * 0.9
    # The blade starts out to our right (angle 0) and comes round towards us.
    end = theta
    start = max(0.0, theta - 330)
    fade = 1.0 if t < spin_end else max(0.0, 1 - (t - spin_end) / 0.32)
    if t >= spin_end:
        start = min(end, start + 330 * (t - spin_end) / 0.32)
    return (fx, cy, rx, ry, start, end, width, fade)


def dangle(rig):
    """Picked up, and falling: wide eyes, a little "o", legs kicking, the sword waving and
    the cap fluttering."""
    period = 0.6

    def flutter(t):
        p = 2 * math.pi * t / period
        return (1800 * math.sin(p), 700 * math.sin(2 * p))

    def body(t):
        p = 2 * math.pi * t / period
        return dict(squash=-0.04, legs=(12 * math.sin(p), -12 * math.sin(p)), sway=2.5 * math.sin(p + 1.0))
    cap = Cap(rig, body, flutter, period=period, stiffness=140, damping=7)
    return frames_from(even(period, 15), lambda t: dict(
        eyes=WIDE, mouth="o", arm=10 + 14 * math.sin(2 * math.pi * 2 * t / period), cap=cap.at(t), **body(t)))


def sleep(rig):
    """Dozing on his heels, leaning on his planted sword, head lolling to one side. The app
    adds the breathing and the Zs."""
    return [(dict(eyes=SHUT, mouth="smile", crouch=1.0, sway=-6, lean=-1, arm=142, planted=True, cap=(14, 22)), 1000)]


CLIPS = {
    # key: (file, menu name or None, frames)
    "idle": ("idle.webp", None, idle),
    "walk": ("walk.webp", None, walk),
    "sit": ("sit.webp", None, sit),
    "dance": ("dance.webp", "Sword Pump", sword_pump),
    "dance_spin_attack": ("dance_spin_attack.webp", "Spin Attack", spin_attack),
    "drag": ("drag.webp", None, dangle),
    "sleep": ("sleep.png", None, sleep),
}

RIG = None


def render(spec):
    """Draws one frame. A turning pose is drawn as the two layers seen from the side, and
    blurred along the turn so it reads as fast."""
    spec = dict(spec)
    theta = spec.pop("turn", None)
    smear = spec.pop("smear", 0.0)
    if theta is None or (smear < 1 and (theta % 360) < 1e-3):
        return to_image(RIG.pose(**spec))
    return to_image(turned(RIG, spec, theta, smear))


def turned(rig, spec, theta, smear):
    """Draws a pose turned theta degrees about his upright axis, seen from a little above,
    averaged over the last `smear` degrees of the turn: a camera shutter open for that
    long. The pose itself is drawn once from the front and once from behind; only the
    turn changes from one sample to the next, which is cheap."""
    fx, fy = to_canvas(*rig.feet)
    fx_back, fx_front = effects(rig, spec)
    sides = {}
    # Where the elbow is once he has leant, crouched or hopped.
    ex, ey = to_canvas(*ELBOW)
    body_m = rig.body_matrix(**{k: spec.get(k, 0.0) for k in ("lean", "squash", "dx", "dy", "crouch")})
    elbow = body_m @ np.array([ex, ey, 1.0])
    samples = max(2, min(40, int(smear / 2.5) + 2))
    acc = None
    for k in range(samples):
        th = theta - smear * k / max(1, samples - 1)
        c, s = math.cos(math.radians(th)), math.sin(math.radians(th))
        back = c < 0
        if back not in sides:
            body, arm_img, sleeve = rig.layers(**dict(spec, back=back))
            sides[back] = (over(sleeve, body), arm_img)
        body, arm_img = sides[back]
        # The body is never seen edge on: his head is round, and he has some depth to him.
        bc = math.copysign(0.58 + 0.42 * abs(c), c)
        mb = np.array([[bc, 0, fx - bc * fx], [s * SPIN_TILT, 1, -s * SPIN_TILT * fx]], np.float64)
        body_t = transform(body, mb, cv2.INTER_LINEAR)
        # The arm is flat and swings right round: it turns about the elbow, which goes
        # where the body takes it.
        px, py = mb @ np.array([elbow[0], elbow[1], 1.0])
        ma = np.array([[c, 0, 0], [s * SPIN_TILT, 1, 0]], np.float64)
        ma[:, 2] = np.array([px, py]) - ma[:, :2] @ elbow
        arm_t = transform(arm_img, ma, cv2.INTER_LINEAR)
        # Towards us the arm is in front of him, away from us behind.
        img = over(arm_t, body_t) if s >= 0 else over(body_t, arm_t)
        acc = img if acc is None else acc + img
    img = acc / samples
    if fx_back is not None:
        img = over(img, fx_back)
    if fx_front is not None:
        img = over(fx_front, img)
    return img


def render_all(specs):
    """Draws every frame, on all the processor's cores where the system can fork."""
    try:
        ctx = multiprocessing.get_context("fork")
    except ValueError:                                      # Windows: one at a time
        return [render(spec) for spec in specs]
    with ctx.Pool() as pool:
        return pool.map(render, specs, chunksize=1)


def main():
    global RIG
    cv2.setNumThreads(1)                                    # the frames are spread over cores instead
    RIG = rig = Rig()
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    print("feet at", [round(float(v), 1) for v in rig.feet], "-> anchor", rig.anchor)
    manifest = {"name": "Sprig", "height": 165, "facing": "right", "removeBackground": False, "clips": {}}
    old = json.loads((PACK / "character.json").read_text())["clips"] if (PACK / "character.json").exists() else {}
    sheet_rows = []
    for key, (file, name, make) in CLIPS.items():
        clip = {"file": file, "anchor": old.get(key, {}).get("anchor", rig.anchor)}
        if name:
            clip["name"] = name
        manifest["clips"][key] = clip
        if only and key not in only:
            continue
        frames = make(rig)
        images = render_all([spec for spec, _ in frames])
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
                           lossless=False, quality=90, alpha_quality=100, method=4)
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
