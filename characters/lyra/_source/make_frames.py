#!/usr/bin/env python3
"""Builds Lyra's animations from one cut-out drawing.

    python3 make_frames.py              # writes the clips and character.json into the pack
    python3 make_frames.py --sheet      # also saves sheet.png, every frame on one page
    python3 make_frames.py idle drag    # only rebuilds the clips named

It takes about a minute for everything.

The drawing is treated as a puppet with a few working parts:

- Face. Each eye can blink part way, close, smile (^ ^) or widen; the mouth can grin (as
  drawn), sing, smile with the lips closed, or make a small "o". Eyes and mouth are
  painted out with skin that blends in from all round their edge, then redrawn.
- Hair. The two long falls of hair are bent by a smooth warp that is zero over the face
  and body and grows towards the tips, so they swing and bounce without tearing. A
  damped spring drives them from the body's own motion, so they lag and overshoot.
- Hand. The open hand bends at the wrist to wave; the sash behind it is repainted so
  nothing shows through when it lifts.
- Arm. To play the lute, the whole of that arm swings across her body until the fingers
  lie on the strings, and a flap of her shawl hangs where the arm was. It strums by
  swinging at the elbow and flicking at the wrist.
- Legs. Each leg is its own layer behind the skirt, so the legs can swing to walk and
  kick, and tuck up under the skirt when she bends her knees or sits on her heels.
- Waist. Swaying turns her head and shoulders and bends the torso smoothly down to her
  hips, which stay put.
- Body. Lean, squash and hops, all about the point between the feet.

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
        (197, 792), (207, 807), (224, 815), (233, 815), (235, 824), (243, 832), (253, 832), (263, 831), (278, 834),
        (296, 829), (308, 820), (310, 804)]
WRIST = (302, 798)
HAND_AXIS = (-1.0, -0.08)                   # from the wrist towards the fingertips
BEND_FROM, BEND_TO = 2, 30
# What the thumb hides: the top of the sash, and its outline on the left.
SASH_UNDER = [(261, 840), (275, 796), (314, 796), (314, 840)]
SASH_EDGE = ([(256, 846), (262, 832), (267, 818), (272, 806), (276, 796)], [5.5, 5.5, 5.5, 5.5, 5.5])

# Playing the lute. The arm with the open hand does the strumming. It is cut out whole:
# ARM outlines fingers, glove, thumb, cuff and the bare forearm up to her vest, and ELBOW is
# the middle of its inner end. In the drawing the shawl's border runs along the top of the
# arm and cloth along the bottom, so the arm has no outline of its own there; ARM_TOP,
# ARM_BOTTOM and THUMB_EDGE are where it is given one.
ARM = [(203, 765), (214, 760), (232, 763), (247, 771), (266, 774), (283, 775), (290, 771), (295, 766.5),
       (300, 760.5), (305, 755.5), (310, 750), (315, 745), (320, 740.5), (324, 737.5), (328, 734), (333, 730.5),
       (337, 729.5), (337.5, 740), (338.5, 755), (339.5, 768), (340, 778.5), (336, 782), (331, 785.5),
       (326, 787.5), (321.5, 788.5), (316, 793.5), (310, 799.5), (305, 803.5), (303, 808), (302, 815),
       (300, 822), (296, 829), (278, 834), (263, 831), (253, 832), (243, 832), (235, 824), (233, 815),
       (224, 815), (207, 807), (197, 792), (196, 778)]
ELBOW = (338.5, 755)
ARM_TOP = [(247, 771), (266, 774), (283, 775), (290, 771), (295, 766.5), (300, 760.5), (310, 750), (320, 740.5),
           (328, 734), (337, 729.5)]
ARM_BOTTOM = [(296, 829), (300, 822), (302, 815), (303, 808), (305, 803.5), (310, 799.5), (316, 793.5),
              (321.5, 788.5), (331, 785.5), (340, 778.5)]
THUMB_EDGE = [(243, 832), (253, 832), (263, 831), (278, 834), (296, 829)]
# Where the arm goes to play: the elbow at her side, the arm swung round it until the
# forearm crosses her body, the wrist part straightened so the fingers reach the strings.
# It is drawn a little larger there, being in front of her now. A strum swings the arm
# STRUM_SWING degrees either way about the elbow and the wrist STRUM_FLICK degrees.
STRUM_ELBOW = (338, 772)
STRUM_TURN = -161.0
STRUM_UNBEND = 22.0
STRUM_SCALE = 1.15
STRUM_SWING = 4.5
STRUM_FLICK = 9.0
# With the arm gone from her side, the shawl that lay along it hangs there in a flap. FLAP
# is the forearm and cuff it takes the place of; SHAWL_TIP is the shawl's border beyond
# that, along the glove and fingers, which goes; FLAP_END is the outline that closes the
# flap and FLAP_FOLD a crease down it. OVER_ARM is the flap with the outlines round it,
# which lie over the arm where it comes out from underneath.
FLAP = [(283, 775), (290, 771), (295, 766.5), (300, 760.5), (305, 755.5), (310, 750), (315, 745), (320, 740.5),
        (324, 737.5), (328, 734), (333, 730.5), (337, 729.5), (337.5, 740), (338.5, 755), (339.5, 768),
        (340, 778.5), (336, 782), (331, 785.5), (326, 787.5), (321.5, 788.5), (316, 793.5), (310, 799.5),
        (305, 803.5), (297, 800), (289, 792), (284, 783)]
SHAWL_TIP = [(232, 790), (240, 778), (252, 770), (264, 765), (276, 765), (284, 767), (287, 779), (283, 778),
             (266, 777), (247, 774), (240, 792)]
FLAP_END = ([(284, 771), (281, 780), (284, 790), (292, 799), (303, 806)], [5, 5.5, 5.5, 5.5, 5])
FLAP_FOLD = ([(312, 752), (318, 766), (322, 782)], [1.5, 3, 1.5])
OVER_ARM = [(270, 760), (300, 742), (322, 722), (342, 722), (343.5, 760), (344, 784), (322, 800), (300, 815),
            (278, 800)]

# Legs. Each outline follows the skirt's hem where the leg goes under it and runs through
# empty background elsewhere; LEG_SPLIT is the line between the two, down the gap that
# separates them. The far leg (left on screen) is drawn behind the near one, and both
# behind the skirt, so they can swing and tuck up under it. They turn about points just
# under the hem, which keeps them from sliding sideways where they meet it. The slit of
# thigh that shows between two panels of the skirt is left as part of the skirt.
LEG_SPLIT = [(418, 967), (412, 971), (407.5, 976), (406.5, 990), (409, 998), (412, 1006), (414.5, 1012),
             (416.5, 1022), (421, 1030), (421, 1040), (425, 1048), (425, 1085)]
LEG_FAR = [(314, 1085), (314, 965), (322, 950), (335, 946), (345, 943.5), (351, 943), (357, 941.5),
           (366, 934), (376, 926), (383, 932), (392, 941), (400, 949), (408, 956), (414, 962)]
LEG_NEAR = [(422.5, 964), (427, 955), (434, 945.5), (441, 938.5), (449, 936), (460, 940), (470.5, 945),
            (472.5, 950.5), (477, 951), (483, 955.5), (489, 958.5), (496, 963), (590, 963), (590, 1085)]
HIP = {"far": (378, 925), "near": (452, 925)}
LEG_TOP = {"far": (352, 412), "near": (423, 487)}      # columns where each leg carries on up under the skirt
LEG_HIDDEN = 70                             # how far up that hidden part is painted
CROUCH = 66                                 # how far she sinks when her knees are fully bent

# Swaying bends her at the waist. Everything above SWAY_TOP_Y turns as one piece about
# SWAY_PIVOT, nothing below SWAY_BOTTOM_Y moves, and the torso bends smoothly in between.
SWAY_TOP_Y, SWAY_BOTTOM_Y = 650, 850
SWAY_PIVOT = (430, 850)

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

        # The arm that strums, with the outlines it lacks, and what shows at her side when
        # it has gone: the sash under where the hand was, and a flap of the shawl, in the
        # shawl's own colours, where the forearm was.
        def colour_of(box, wanted):
            (bx0, by0), (bx1, by1) = to_canvas(box[0], box[1]), to_canvas(box[2], box[3])
            px = rgb[by0:by1, bx0:bx1].reshape(-1, 4)
            px = px[px[:, 3] > 0.95][:, :3]
            return np.median(px[wanted(px)], axis=0)
        cloth = colour_of((300, 690, 345, 728), lambda c: (c[:, 0] > 0.6) & (c[:, 1] < 0.4))
        maroon = colour_of((286, 745, 330, 775), lambda c: (c[:, 0] > 0.25) & (c[:, 0] < 0.6) & (c[:, 1] < 0.15))
        arm_mask = poly_mask(ARM, 0.7)
        outline = np.maximum.reduce([stroke(ARM_TOP, [4.5] * len(ARM_TOP)), stroke(ARM_BOTTOM, [4.5] * len(ARM_BOTTOM)),
                                     stroke(THUMB_EDGE, [4.0] * len(THUMB_EDGE))])
        self.arm = paint(self.base * arm_mask[..., None], outline, maroon * 0.75)
        self.arm_gone = np.clip(arm_mask + poly_mask(SHAWL_TIP, 0.7), 0, 1)
        flap = poly_mask(FLAP, 0.7)
        shaded = cloth * 0.82 + maroon * 0.18                   # it hangs in her shadow
        self.arm_behind = np.dstack([np.broadcast_to(shaded, (H, W, 3)) * flap[..., None], flap])
        self.arm_behind = self.under + self.arm_behind * (1 - self.under[..., 3:])
        self.flap_ink = (np.maximum(stroke(*FLAP_END), stroke(*FLAP_FOLD) * 0.7), maroon)
        self.over_arm = poly_mask(OVER_ARM, 0.7)

        # Legs: each layer is the drawn leg plus a plain stretch of stocking carrying on up
        # behind the skirt, so no gap opens at the hem when it swings. The layers reach a
        # couple of pixels past their outlines (under the skirt, and under each other), which
        # keeps the soft edges solid where they overlap.
        self.legs_mask = poly_mask(LEG_FAR + LEG_SPLIT[:1] + LEG_NEAR, 0.6)
        far = np.minimum(poly_mask(LEG_FAR + LEG_SPLIT, 0.6), self.legs_mask)
        exact = {"far": far, "near": self.legs_mask - far}
        self.leg, self.leg_outline = {}, {}
        for name in ("far", "near"):
            hard = exact[name] > 0.5
            contours, _ = cv2.findContours((hard & (a > 0.5)).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            self.leg_outline[name] = max(contours, key=cv2.contourArea)[:, 0, :].astype(np.float64)
            wide = cv2.dilate(exact[name], np.ones((5, 5), np.uint8))
            layer = self.base * wide[..., None]
            leg_px = rgb[hard & (a > 0.95)][:, :3]
            dark = leg_px[leg_px.max(axis=1) < 0.42]
            stocking = np.median(dark, axis=0)
            outline = np.median(dark[dark.sum(axis=1) < np.percentile(dark.sum(axis=1), 10)], axis=0)
            hidden = np.zeros((H, W), np.float32)
            colour = np.zeros((H, W, 3), np.float32)
            x_from, x_to = (v - X0 for v in LEG_TOP[name])
            for x in range(x_from, x_to + 1):
                top = int(np.nonzero(hard[:, x])[0].min())
                edge = min(x - x_from, x_to - x) < 4
                colour[top - LEG_HIDDEN:top + 3, x] = outline if edge else stocking
                hidden[top - LEG_HIDDEN:top + 3, x] = 1
            hidden = cv2.GaussianBlur(hidden, (0, 0), 0.7)
            colour = cv2.GaussianBlur(colour, (0, 0), 0.9)
            self.leg[name] = layer + np.dstack([colour * hidden[..., None], hidden]) * (1 - layer[..., 3:])

        self.sway_w = smoothstep((SWAY_BOTTOM_Y - Y0 - yy) / (SWAY_BOTTOM_Y - SWAY_TOP_Y))

    def hand_pose(self, img, lift):
        """lift: degrees the fingertips rise (negative lowers them)."""
        if abs(lift) < 1e-3:
            return img
        out = self.under + img * (1 - self.under_mask[..., None])
        moved = self.bend_wrist(self.hand, lift)
        return moved + out * (1 - moved[..., 3:])

    def bend_wrist(self, layer, lift):
        """Bends a layer at the wrist: lift is degrees the fingertips rise, as drawn."""
        xx, yy = self.grid
        px, py = to_canvas(*WRIST)
        vx, vy = xx - px, yy - py
        ax, ay = np.array(HAND_AXIS) / np.hypot(*HAND_AXIS)
        phi = np.radians(lift) * smoothstep(((vx * ax + vy * ay) - BEND_FROM) / (BEND_TO - BEND_FROM))
        c, s_ = np.cos(phi), np.sin(phi)
        mx = (px + vx * c + vy * s_).astype(np.float32)
        my = (py - vx * s_ + vy * c).astype(np.float32)
        return cv2.remap(layer, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT).clip(0, 1)

    def strum_pose(self, img, strum, flick):
        """Her arm across her body with the hand on the lute. strum: where the hand is on
        its way across the strings, from -1 (above them) to 1 (below). flick: the same for
        the wrist alone."""
        body = img * (1 - self.arm_gone[..., None])
        body = body + self.arm_behind * (1 - body[..., 3:])
        body = paint(body, *self.flap_ink)
        # Straightening the wrist lowers the fingertips as drawn; turned round to the lute,
        # that raises them, so a flick downwards is a little less straightening.
        arm = self.bend_wrist(self.arm, -(STRUM_UNBEND - STRUM_FLICK * flick))
        ex, ey = to_canvas(*ELBOW)
        arm = transform(arm, about(ex, ey, STRUM_TURN + STRUM_SWING * strum, STRUM_SCALE,
                                   dx=STRUM_ELBOW[0] - ELBOW[0], dy=STRUM_ELBOW[1] - ELBOW[1]))
        out = arm + body * (1 - arm[..., 3:])
        over = body * self.over_arm[..., None]
        return over + out * (1 - over[..., 3:])

    def hair_pose(self, img, hair):
        """hair: {"L": (dx, dy), "R": (dx, dy)}, how far each fall's tip moves."""
        if all(abs(v) < 1e-3 for d in hair.values() for v in d):
            return img
        xx, yy = self.grid
        dx = sum(self.hair_w[k] * hair[k][0] for k in hair)
        dy = sum(self.hair_w[k] * hair[k][1] for k in hair)
        return cv2.remap(img, (xx - dx).astype(np.float32), (yy - dy).astype(np.float32), cv2.INTER_CUBIC,
                         borderMode=cv2.BORDER_CONSTANT).clip(0, 1)

    def legs_pose(self, img, legs, lift, crouch):
        """legs: degrees each leg swings back (far, near; negative is forward, the way she
        faces). lift: pixels each foot is raised. crouch: 0..1, how far the knees are bent,
        which tucks both legs up under the skirt."""
        if not (any(legs) or any(lift) or crouch):
            return img
        under = None
        for name, deg, up in (("near", legs[1], lift[1]), ("far", legs[0], lift[0])):
            hx, hy = to_canvas(*HIP[name])
            layer = transform(self.leg[name], about(hx, hy, deg, dy=-up - crouch * CROUCH))
            under = layer if under is None else under + layer * (1 - under[..., 3:])
        body = img * (1 - self.legs_mask[..., None])
        return body + under * (1 - body[..., 3:])

    def foot_drop(self, name, deg):
        """How far below its resting level the lowest point of a leg ends up when the leg is
        turned by deg (negative if it rises). Raising the leg by this much keeps the foot on
        the floor: on its heel when the leg is forward, on its toes when it is back."""
        hx, hy = to_canvas(*HIP[name])
        pts = self.leg_outline[name]
        c, s_ = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        return float((hy + (pts[:, 0] - hx) * s_ + (pts[:, 1] - hy) * c).max() - pts[:, 1].max())

    def sway_pose(self, img, deg):
        """deg: how far the head and shoulders tip, bending at the waist (positive is right)."""
        if abs(deg) < 1e-3:
            return img
        xx, yy = self.grid
        px, py = to_canvas(*SWAY_PIVOT)
        vx, vy = xx - px, yy - py
        phi = np.radians(deg) * self.sway_w
        c, s_ = np.cos(phi), np.sin(phi)
        return cv2.remap(img, (px + vx * c + vy * s_).astype(np.float32), (py - vx * s_ + vy * c).astype(np.float32),
                         cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT).clip(0, 1)

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

    def pose(self, eyes=("open", "open"), mouth="grin", hand=0.0, strum=None, flick=0.0, hair=None, sway=0.0,
             legs=(0.0, 0.0), lift=(0.0, 0.0), crouch=0.0, lean=0.0, squash=0.0, dx=0.0, dy=0.0):
        img = self.face.get(tuple(eyes), mouth)
        # She either plays, with that arm across her body, or holds the hand out as drawn.
        img = self.hand_pose(img, hand) if strum is None else self.strum_pose(img, strum, flick)
        img = self.legs_pose(img, legs, lift, crouch)
        if hair:
            img = self.hair_pose(img, hair)
        img = self.sway_pose(img, sway)
        if lean or squash or dx or dy or crouch:
            img = transform(img, self.body_matrix(lean, squash, dx, dy, crouch))
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

    body(t) gives the body pose (lean, sway, crouch, dx, dy...) at time t; push(t) an extra force
    per side (a breeze, a flutter). The clip is a loop, so the spring is run for a few
    turns first and the last one is kept, which makes the loop seamless."""

    def __init__(self, rig, body, push=None, period=1.0, stiffness=110.0, damping=6.0, gain=1.0, limit=34.0):
        self.body, self.push = body, push or (lambda t: {"L": (0, 0), "R": (0, 0)})
        self.period, self.limit = period, limit
        dt = 1 / 480
        steps = int(round(period / dt))
        def where(t, k):
            return rig.place(HAIR_TIPS[k], **body(t))

        self.track = {}
        for k in HAIR_TIPS:
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
        pose = self.body(t)
        lean = math.radians(pose.get("lean", 0.0) + 0.8 * pose.get("sway", 0.0))
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

OPEN, SHUT, HAPPY_EYES, WIDE = ("open", "open"), ("closed", "closed"), ("happy", "happy"), ("wide", "wide")


def blink(frames, **held):
    """Adds a blink; `held` is the rest of the pose she keeps while she does it."""
    for eyes, ms in (((0.5, 0.5), 40), (SHUT, 70), ((0.5, 0.5), 50)):
        frames.append((dict(held, eyes=eyes), ms))


def idle(rig):
    """Mostly still, which the app breathes for her. Blinks, a breeze through her hair, a
    tilt of the head as if listening, and now and then a wave."""
    f = [(dict(), 2200)]
    blink(f)
    f.append((dict(), 1400))

    # A breeze from the left lifts both falls of hair and lets them go.
    def breeze(t):
        b = bump(t, 0.0, 1.5)
        return {"L": (900 * b, -250 * b), "R": (1100 * b, -200 * b)}
    hair = Hair(rig, lambda t: {}, breeze, period=4.0, stiffness=70, damping=5.5)
    f += frames_from(even(2.0, 8), lambda t: dict(hair=hair.at(t)))
    f.append((dict(), 1200))
    blink(f)
    f.append((dict(), 110))
    blink(f)
    f.append((dict(), 900))

    # She tips her head and shoulders to one side, holds it, and comes back.
    for sway, ms in ((1.6, 60), (3.6, 60), (4.5, 1100), (3.0, 60), (1.2, 60)):
        f.append((dict(sway=sway, hair={"L": (-1.5 * sway, 0), "R": (-1.5 * sway, 0)}), ms))
    f.append((dict(), 1000))

    # Wave hello: up, three waggles, down, leaning a little towards the hand.
    def wave(t):
        up = smooth_ramp(t, 0.0, 0.25) * (1 - smooth_ramp(t, 1.25, 0.25))
        return dict(hand=up * (20 + 9 * math.sin(2 * math.pi * 2.0 * (t - 0.25))), sway=-2.5 * up,
                    eyes=HAPPY_EYES if 0.2 < t < 1.35 else OPEN)
    f += frames_from(even(1.5, 10), wave)
    f.append((dict(), 1600))
    blink(f)
    f.append((dict(), 800))
    return f


def walk(rig):
    """One stride (two steps). With a walk clip the app adds no motion of its own, so the
    bob and the lean are drawn in. The legs swing from under the skirt; each foot stays
    planted on the floor while it travels back (heel first, then toes) and is picked up
    as it comes forward, and the body dips when both feet are down."""
    period, swing, step = 0.4, 18.0, 11.0

    def body(t):
        p = 2 * math.pi * t / period
        s, c = math.sin(p), math.cos(p)
        dy = 2.5 - 5 * c * c
        legs = (swing * s, -swing * s)
        height = (step * max(0.0, -c), step * max(0.0, c))      # of each foot above the floor
        lift = tuple(h + rig.foot_drop(name, deg) + dy for name, deg, h in zip(("far", "near"), legs, height))
        return dict(legs=legs, lift=lift, dy=dy, lean=2.5, sway=1.5 * s)
    hair = Hair(rig, body, period=period, stiffness=160, damping=8)
    return frames_from(even(period, 20), lambda t: dict(
        hand=5 + 6 * math.sin(2 * math.pi * t / period), hair=hair.at(t), **body(t)))


def sit(rig):
    """Settled on her heels with her skirt round her: blinks, and a contented moment."""
    held = dict(crouch=1.0, hand=-5)
    f = [(held, 2000)]
    blink(f, **held)
    f.append((held, 1500))
    f.append((dict(held, sway=1.0), 60))
    f.append((dict(held, sway=2.2, eyes=HAPPY_EYES, mouth="smile"), 1300))
    f.append((dict(held, sway=1.0), 60))
    f.append((held, 1200))
    blink(f, **held)
    f.append((held, 600))
    return f


def strum_along(rig):
    """Shown during every built-in dance move, which adds its own bounces, leans and spins,
    so her feet stay still here. This is when the app sends up its music notes, so she plays
    her lute. Two beats at 120 BPM: her hand crosses the strings downwards on each beat and
    comes back up between them, she sings on one beat and grins on the other, sways at the
    waist, and her hair bounces along."""
    period = 1.0

    def body(t):
        return dict(sway=3.5 * math.sin(2 * math.pi * t / period))
    # The hair also feels a bounce the clip does not draw, standing in for the app's.
    hair = Hair(rig, lambda t: dict(body(t), dy=-10 * abs(math.sin(2 * math.pi * t / period))), period=period)

    def stroke_at(phase):
        """Where the hand is, -1 above the strings to 1 below: it passes them going down as
        each beat starts. A little quicker through the strings than a plain swing."""
        swing = math.sin(2 * math.pi * phase)
        return math.copysign(abs(swing) ** 0.8, swing)

    def at(t):
        beat = t / (period / 2)
        # The wrist follows the arm a moment behind, which is what makes it a strum.
        return dict(eyes=HAPPY_EYES, mouth="sing" if int(beat) % 2 == 0 else "grin",
                    strum=stroke_at(beat), flick=stroke_at(beat - 0.14), hair=hair.at(t), **body(t))
    return frames_from(even(period, 16), at)


def serenade(rig):
    """Four beats: a slow sway from the hips with her head following, eyes closed,
    singing, sinking a little on each beat, and one unhurried strum of the lute to each."""
    period = 2.0

    def body(t):
        p = 2 * math.pi * t / period
        dip = math.sin(math.pi * ((t / 0.5) % 1)) ** 2
        return dict(lean=4 * math.sin(p), sway=5 * math.sin(p - 0.6), dx=8 * math.sin(p), crouch=0.22 * (1 - dip))
    hair = Hair(rig, body, period=period)

    def stroke_at(phase):
        """Down across the strings in the first third of a beat, then slowly back up."""
        phase %= 1
        return -1 + 2 * (smooth_ramp(phase, 0.0, 0.3) - smooth_ramp(phase, 0.45, 0.55))

    def at(t):
        beat = int(t / 0.5)
        return dict(eyes=SHUT if beat < 3 else HAPPY_EYES, mouth="sing" if beat % 2 == 0 else "smile",
                    strum=stroke_at(t / 0.5), flick=stroke_at(t / 0.5 - 0.08), hair=hair.at(t), **body(t))
    return frames_from(even(period, 12), at)


def hair_flip(rig):
    """Four beats: wind up, whip right, whip left, hop. All about the hair."""
    period = 2.0

    def body(t):
        whip = bump(t, 0.5, 0.42) - bump(t, 1.0, 0.42)
        hop = math.sin(math.pi * (t - 1.6) / 0.3) if 1.6 <= t <= 1.9 else 0.0
        return dict(lean=-2 * bump(t, 0.0, 0.5) + 6 * whip, sway=-3 * bump(t, 0.0, 0.5) + 8 * whip, dx=8 * whip,
                    crouch=0.3 * bump(t, 0.05, 0.45) + 0.35 * bump(t, 1.42, 0.2) + 0.3 * bump(t, 1.86, 0.14),
                    dy=-46 * hop, lift=(10 * hop, 10 * hop), legs=(9 * hop, -9 * hop))
    hair = Hair(rig, body, period=period, stiffness=95, damping=5.0, gain=0.4)

    def at(t):
        if t < 0.45:
            eyes, mouth = OPEN, "grin"
        elif t < 1.45:
            eyes, mouth = (("happy", "open") if t < 0.95 else ("open", "happy")), "grin"
        else:
            eyes, mouth = HAPPY_EYES, "sing"
        return dict(eyes=eyes, mouth=mouth, hand=18 * bump(t, 1.5, 0.45), hair=hair.at(t), **body(t))
    return frames_from(even(period, 12), at)


def wave_hello(rig):
    """Four beats: two little hops with a kick, waving all the while."""
    period = 2.0

    def body(t):
        hop = 0.0
        for start in (0.0, 1.0):
            u = (t - start) / 0.42
            if 0 <= u <= 1:
                hop = math.sin(math.pi * u)
        bend = sum(bump(t, start, 0.16) for start in (0.4, 0.84, 1.4, 1.84))    # landing, then gathering
        return dict(dy=-30 * hop, crouch=0.28 * bend, lift=(9 * hop, 9 * hop), legs=(10 * hop, -10 * hop),
                    sway=3 * math.sin(math.pi * t), lean=-1.5 * math.sin(math.pi * t))
    hair = Hair(rig, body, period=period)

    def at(t):
        pose = body(t)
        return dict(eyes=HAPPY_EYES, mouth="sing" if pose["dy"] < -15 else "grin",
                    hand=18 + 10 * math.sin(2 * math.pi * 2.5 * t), hair=hair.at(t), **pose)
    return frames_from(even(period, 10), at)


def dangle(rig):
    """Picked up, and falling: wide eyes, a little "o", legs kicking, hand flapping, hair
    fluttering."""
    period = 0.6

    def flutter(t):
        p = 2 * math.pi * t / period
        return {"L": (1800 * math.sin(p), 600 * math.sin(2 * p)), "R": (-1800 * math.sin(p + 0.8), 600 * math.sin(2 * p + 1))}

    def body(t):
        p = 2 * math.pi * t / period
        return dict(squash=-0.04, legs=(12 * math.sin(p), -12 * math.sin(p)), sway=2.5 * math.sin(p + 1.0))
    hair = Hair(rig, body, flutter, period=period, stiffness=140, damping=7)
    return frames_from(even(period, 15), lambda t: dict(
        eyes=WIDE, mouth="o", hand=8 + 14 * math.sin(2 * math.pi * 2 * t / period), hair=hair.at(t), **body(t)))


def sleep(rig):
    """Dozing on her heels, head lolling to one side. The app adds the breathing and the Zs."""
    return [(dict(eyes=SHUT, mouth="smile", crouch=1.0, sway=6, lean=1, hand=-6,
                  hair={"L": (5, 6), "R": (7, 8)}), 1000)]


CLIPS = {
    # key: (file, menu name or None, frames)
    "idle": ("idle.webp", None, idle),
    "walk": ("walk.webp", None, walk),
    "sit": ("sit.webp", None, sit),
    "dance": ("dance.webp", "Strum Along", strum_along),
    "dance_serenade": ("dance_serenade.webp", "Serenade", serenade),
    "dance_hair_flip": ("dance_hair_flip.webp", "Hair Flip", hair_flip),
    "dance_wave": ("dance_wave.webp", "Wave Hello", wave_hello),
    "drag": ("drag.webp", None, dangle),
    "sleep": ("sleep.png", None, sleep),
}

RIG = None


def render(spec):
    return to_image(RIG.pose(**spec))


def render_all(specs):
    """Draws every frame, on all the processor's cores where the system can fork."""
    try:
        ctx = multiprocessing.get_context("fork")
    except ValueError:                                      # Windows: one at a time
        return [render(spec) for spec in specs]
    with ctx.Pool() as pool:
        return pool.map(render, specs, chunksize=2)


def main():
    global RIG
    cv2.setNumThreads(1)                                    # the frames are spread over cores instead
    RIG = rig = Rig()
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    print("feet at", [round(float(v), 1) for v in rig.feet], "-> anchor", rig.anchor)
    manifest = {"name": "Lyra", "height": 160, "facing": "right", "removeBackground": False, "clips": {}}
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
