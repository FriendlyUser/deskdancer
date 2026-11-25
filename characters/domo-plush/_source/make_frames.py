#!/usr/bin/env python3
"""Draws Plush Domo and builds every animation in the pack.

    python3 make_frames.py            # writes the clips and character.json into the pack
    python3 make_frames.py --sheet    # also saves sheet.png, every frame on one page

Plush Domo is Domo made of fleece. His shape, the way his parts move and every clip come
straight from Domo's own script, characters/domo/_source/make_frames.py, which this one
loads. All that is here is a different painter: where Domo's fills each shape with one
flat colour and gives it a dark edge, this one covers it in curly fleece with a soft,
uneven edge and no outline, shades it so that it looks stuffed, sews on felt teeth and
gives him two glossy beads for eyes. It is still a flat drawing: nothing is modelled in
3D, and nothing is taken from a photo. The fleece is made here, from random numbers.

The fleece is fixed to each part, so it turns, leans and squashes with the part it is
on and never slides across it.

Needs numpy and pillow. This folder starts with "_", so the app does not load anything
from it.
"""
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
PACK = HERE.parent

# Domo's script: the shapes, the poses, the clips and the way a pack is built.
_spec = importlib.util.spec_from_file_location("domo", PACK.parent / "domo" / "_source" / "make_frames.py")
domo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(domo)

OUT, SS, W, H = domo.OUT, domo.SS, domo.W, domo.H
move, shift, stretch = domo.move, domo.shift, domo.stretch

# ---------------------------------------------------------------- colours, 0..1

FLEECE = np.array([138, 85, 51], np.float32) / 255
FELT = np.array([206, 32, 34], np.float32) / 255            # the inside of the mouth
TOOTH = np.array([246, 240, 228], np.float32) / 255
BEAD = np.array([15, 13, 14], np.float32) / 255
SHINE = np.array([255, 248, 232], np.float32) / 255
GLOW = np.array([122, 84, 56], np.float32) / 255            # the room, reflected low down in a bead
STITCH = np.array([38, 22, 15], np.float32) / 255
PLASTIC = np.array([238, 243, 246], np.float32) / 255
TEA = np.array([218, 182, 146], np.float32) / 255
PEARL = np.array([40, 26, 22], np.float32) / 255
STRAW = np.array([240, 224, 184], np.float32) / 255
GAS = np.array([208, 220, 142], np.float32) / 255

# ---------------------------------------------------------------- the fleece

TILE = 384                                 # the fleece repeats every this many saved pixels, further than any part is wide
# Each part takes its fleece from a different stretch of the cloth: how far its own space
# is moved across it, in units.
CUT_FROM = {"body": (0, 170), "arm_l": (150, -40), "arm_r": (-150, -40), "leg_l": (120, 130), "leg_r": (-120, 130),
            "foot_l": (60, 200), "foot_r": (-200, 200)}


def weave(seed=7):
    """The cloth all the fleece is cut from, as a picture that repeats without a seam. Red
    is how light each spot is, from half as light as plain fleece to half as light again;
    green is where the pile stands out or lies flat, which is what makes an edge uneven."""
    rng = np.random.default_rng(seed)
    ky, kx = np.fft.fftfreq(TILE)[:, None], np.fft.rfftfreq(TILE)[None, :]

    def blurred(noise, by):                # smoothed all the way round the tile, so that it still repeats
        return np.fft.irfft2(np.fft.rfft2(noise) * np.exp(-2 * (math.pi * by) ** 2 * (kx ** 2 + ky ** 2)), s=noise.shape)

    def evened(a):                         # centred, and scaled so that nearly all of it lies between -1 and 1
        a = a - a.mean()
        return np.clip(a / (2.6 * a.std()), -1, 1)

    grain = rng.random((TILE, TILE))
    curls = evened(blurred(grain, 1.5) - blurred(grain, 3.4))            # the little curls of the pile
    lit = evened(curls - np.roll(curls, (1, 1), (0, 1)))                 # each one catching the light on its upper left
    tone = evened(blurred(rng.random((TILE, TILE)), 9.0))                # slow changes across the cloth
    light = 1 + 0.20 * curls + 0.13 * lit + 0.05 * tone
    pile = evened(blurred(rng.random((TILE, TILE)), 1.3))
    tile = np.dstack([(light - 0.5) * 255, (pile + 1) * 127.5, np.zeros((TILE, TILE))])
    return Image.fromarray(np.tile(np.clip(tile + 0.5, 0, 255).astype(np.uint8), (2, 2, 1)), "RGB")


CLOTH = weave()


# ---------------------------------------------------------------- tools for the painter

def blur(a, by):
    """A picture of amounts from 0 to 1, smoothed."""
    im = Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8), "L")
    return np.asarray(im.filter(ImageFilter.GaussianBlur(by)), np.float32) / 255


def nudged(a, dx, dy):
    """The picture moved dx to the right and dy down, with nothing brought in at the sides."""
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = a[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)]
    return out


def step(a):
    """0 below 0, 1 above 1, gliding between."""
    a = np.clip(a, 0, 1)
    return a * a * (3 - 2 * a)


def depth(solid, over):
    """How far inside a shape each spot is: 0 on its edge, 1 from `over` pixels in."""
    return np.clip((blur(solid, over) - 0.5) * 2, 0, 1)


class Plush:
    """The painter. Domo's render() tells it what there is to draw, from the back to the
    front, in units and already in place. It keeps the picture as colour that has already
    been multiplied by how solid it is, which is what lets soft edges lie over one another."""

    def __init__(self):
        self.colour = np.zeros((H, W, 3), np.float32)
        self.solid = np.zeros((H, W), np.float32)
        self.pile = None                               # the body's pile and where it is, for the edge of the mouth

    # ---- what everything is built from

    def cover(self, shapes, room):
        """Where on the picture some shapes are, with `room` pixels to spare all round, and
        how much of each pixel there they cover."""
        px = [domo.Canvas.px(s) for s in shapes]
        both = np.concatenate(px) / SS
        x0, y0 = (max(int(math.floor(v)) - room, 0) for v in both.min(axis=0))
        x1, y1 = (min(int(math.ceil(v)) + room, limit) for v, limit in zip(both.max(axis=0), (W, H)))
        im = Image.new("L", ((x1 - x0) * SS, (y1 - y0) * SS), 0)
        pen = ImageDraw.Draw(im)
        for s in px:
            pen.polygon((np.rint(s) - (x0 * SS, y0 * SS)).astype(int).flatten().tolist(), fill=255)
        return (slice(y0, y1), slice(x0, x1)), np.asarray(im.reduce(SS), np.float32) / 255

    def lay(self, where, colour, solid):
        """Paints over part of the picture."""
        see = (1 - solid)[..., None]
        self.colour[where] = colour * solid[..., None] + self.colour[where] * see
        self.solid[where] = solid + self.solid[where] * (1 - solid)

    def shade(self, where, by):
        """Darkens what is already painted there, by an amount from 0 to 1 at each pixel."""
        self.colour[where] *= (1 - by)[..., None]

    def cloth(self, attach, name, where):
        """The fleece as it lies on a part: how light it is and how its pile stands, at each
        pixel of that part of the picture. `attach` is how the part's own space lies on the
        canvas, so the fleece goes wherever the part goes."""
        rows, cols = where
        to_units = shift(domo.X0, domo.Y0) @ stretch(1 / OUT, 1 / OUT) @ shift(cols.start, rows.start)
        to_cloth = shift(TILE, TILE) @ stretch(OUT, OUT) @ shift(*CUT_FROM[name])
        m = to_cloth @ np.linalg.inv(attach) @ to_units
        im = CLOTH.transform((cols.stop - cols.start, rows.stop - rows.start), Image.AFFINE,
                             (m[0, 0], m[0, 1], m[0, 2], m[1, 0], m[1, 1], m[1, 2]), Image.BILINEAR)
        a = np.asarray(im, np.float32)
        return a[..., 0] / 255 + 0.5, a[..., 1] / 127.5 - 1

    # ---- what render() asks for

    def fur(self, shapes, attach, name):
        where, solid = self.cover(shapes, 14)
        light, pile = self.cloth(attach, name, where)
        if name == "body":
            self.pile = where, pile
        # The edge follows the pile: out a little where it stands up, in where it lies flat.
        edge = step((blur(solid, 1.7) + 0.30 * pile - 0.5) / 0.36 + 0.5)
        # Stuffed: darker towards the edge all round, and lit from the upper left.
        glow = blur(solid, 5.0)
        lit = np.clip(nudged(glow, -3, -4) - glow, -1, 1)
        tone = (0.64 + 0.36 * depth(solid, 6.0) ** 0.8) * (1 + 0.6 * lit) * light
        self.shade(where, 0.34 * nudged(blur(solid, 3.0), 0, 2))        # the shadow it casts on what is behind
        self.lay(where, FLEECE * tone[..., None], edge)

    def crease(self, points):
        """A seam: the fleece is a little darker along it."""
        where, solid = self.cover([domo.ribbon(points, [2.2] * len(points))], 4)
        self.shade(where, 0.24 * blur(solid, 0.8))

    def eye(self, m, cx, cy, state):
        line = domo.eye_line(cx, cy, state)
        if line is not None:                               # shut: a line of dark stitching
            where, solid = self.cover([move(m, line)], 3)
            self.shade(where, 0.25 * blur(solid, 1.6))
            self.lay(where, np.broadcast_to(STITCH, solid.shape + (3,)), solid)
            return
        rx, ry, shut = domo.eye_size(state)
        middle, right, down = domo.Canvas.px(move(m, [(cx, cy), (cx + rx, cy), (cx, cy + ry)])) / SS
        reach = int(math.ceil(max(np.hypot(*(right - middle)), np.hypot(*(down - middle))))) + 6
        x0, y0 = int(middle[0]) - reach, int(middle[1]) - reach
        where = (slice(y0, y0 + 2 * reach + 1), slice(x0, x0 + 2 * reach + 1))
        ys, xs = np.mgrid[y0:y0 + 2 * reach + 1, x0:x0 + 2 * reach + 1].astype(np.float32) + 0.5
        # Each pixel, measured in the bead's own widths and heights from its middle.
        across = np.linalg.inv(np.stack([right - middle, down - middle], 1))
        u = across[0, 0] * (xs - middle[0]) + across[0, 1] * (ys - middle[1])
        v = across[1, 0] * (xs - middle[0]) + across[1, 1] * (ys - middle[1])
        far = np.hypot(u, v)
        size = (np.hypot(*(right - middle)) + np.hypot(*(down - middle))) / 2
        self.shade(where, 0.42 * np.exp(-((np.maximum(far - 1, 0) * size / 2.4) ** 2)) * (far > 1))    # sunk into the fleece
        open_ = 1 - min(shut / 0.6, 1.0)                    # the shine goes as the eye shuts
        colour = np.broadcast_to(BEAD, far.shape + (3,)).copy()
        rim = step((far - 0.62) / 0.36) * np.clip((u + v) / (far + 1e-6) / 1.414, 0, 1)      # low on the right
        colour += (GLOW - BEAD) * (0.5 * rim * open_)[..., None]
        soft = np.exp(-(((u + 0.30) / 0.42) ** 2 + ((v + 0.34) / 0.36) ** 2))
        colour += (SHINE - BEAD) * (0.5 * soft * open_)[..., None]
        spark = np.clip((0.17 - np.hypot(u + 0.34, v + 0.40)) * size + 0.5, 0, 1)
        colour += (SHINE - colour) * (spark * open_)[..., None]
        self.lay(where, colour, np.clip((1 - far) * size + 0.5, 0, 1))

    def mouth(self, m, wide):
        lip, rows = domo.mouth_shapes(m, wide)
        where, solid = self.cover([lip], 8)
        body, pile = self.pile
        pile = pile[where[0].start - body[0].start:where[0].stop - body[0].start,
                    where[1].start - body[1].start:where[1].stop - body[1].start]
        hole = step((blur(solid, 1.1) + 0.16 * pile - 0.5) / 0.5 + 0.5)       # the fleece is cut away, not quite evenly
        # Red felt, set back a little: in shadow under the top of the opening and round its sides.
        under = np.clip((nudged(blur(solid, 4.0), 0, 5) - 0.5) * 2, 0, 1)
        tone = (0.58 + 0.42 * under ** 0.7) * (0.9 + 0.1 * depth(solid, 3.0))
        felt = FELT * tone[..., None]
        teeth = [self.cover([row], 0) for row in rows]
        tooth = np.zeros_like(solid)
        for (rws, cls), part in teeth:                      # each row, brought onto the mouth's own patch
            y0, x0 = max(rws.start, where[0].start), max(cls.start, where[1].start)
            y1, x1 = min(rws.stop, where[0].stop), min(cls.stop, where[1].stop)
            if y1 > y0 and x1 > x0:
                into = (slice(y0 - where[0].start, y1 - where[0].start), slice(x0 - where[1].start, x1 - where[1].start))
                tooth[into] = np.maximum(tooth[into], part[y0 - rws.start:y1 - rws.start, x0 - cls.start:x1 - cls.start])
        tooth *= solid
        felt *= (1 - 0.34 * nudged(blur(tooth, 1.8), 1, 2))[..., None]          # the teeth's shadow on the felt
        white = TOOTH * (0.84 + 0.16 * depth(tooth, 1.6))[..., None]            # thick felt, rounded at its edges
        show = blur(tooth, 0.5)[..., None]
        self.lay(where, white * show + felt * (1 - show), hole)

    def cup(self, parts):
        where, solid = self.cover([parts["cup"], parts["lid"], parts["straw"]], 8)

        def on(shape):                                      # a shape's cover, on the whole cup's patch
            (rws, cls), part = self.cover([shape], 1)
            out = np.zeros_like(solid)
            y0, x0 = max(rws.start, where[0].start), max(cls.start, where[1].start)
            y1, x1 = min(rws.stop, where[0].stop), min(cls.stop, where[1].stop)
            if y1 > y0 and x1 > x0:
                out[y0 - where[0].start:y1 - where[0].start, x0 - where[1].start:x1 - where[1].start] = \
                    part[y0 - rws.start:y1 - rws.start, x0 - cls.start:x1 - cls.start]
            return out

        cup, tea, lid, straw = (on(parts[k]) for k in ("cup", "tea", "lid", "straw"))
        self.shade(where, 0.26 * nudged(blur(np.maximum(cup, lid), 2.5), 0, 2))
        # Where each pixel is across the cup, from -1 at its left side to 1 at its right.
        rows, cols = where
        ys, xs = np.mgrid[rows.start:rows.stop, cols.start:cols.stop].astype(np.float32) + 0.5
        back = np.linalg.inv(parts["space"]) @ shift(domo.X0, domo.Y0) @ stretch(1 / OUT, 1 / OUT)
        cx = back[0, 0] * xs + back[0, 1] * ys + back[0, 2]
        cy = back[1, 0] * xs + back[1, 1] * ys + back[1, 2]
        side = cx / (domo.CUP_BASE + (domo.CUP_RIM - domo.CUP_BASE) * np.clip(-cy / domo.CUP_TALL, 0, 1))
        round_ = 0.80 + 0.20 * np.sqrt(np.clip(1 - side ** 2, 0, 1))            # darker towards the sides: it is round
        gleam = 0.9 * np.exp(-((side + 0.52) / 0.13) ** 2) + 0.35 * np.exp(-((side - 0.70) / 0.08) ** 2)
        # Clear plastic: what is behind shows through, more so in the middle than at the sides.
        self.lay(where, np.broadcast_to(PLASTIC, solid.shape + (3,)), cup * (0.30 + 0.5 * (1 - depth(cup, 2.2))))
        self.lay(where, TEA * (round_ * (0.94 + 0.06 * depth(tea, 3.0)))[..., None], tea * 0.97)
        for pearl in parts["pearls"]:
            p = on(pearl)
            self.lay(where, PEARL * (1 + 0.5 * np.clip(nudged(p, -1, -1) - nudged(p, 1, 1), 0, 1))[..., None], p * 0.94)
        self.lay(where, np.broadcast_to(PLASTIC, solid.shape + (3,)), lid * (0.62 + 0.3 * (1 - depth(lid, 1.2))))
        self.lay(where, STRAW * (0.82 + 0.18 * depth(straw, 1.6))[..., None], straw)
        for pearl in parts["rising"]:
            self.lay(where, np.broadcast_to(PEARL, solid.shape + (3,)), on(pearl) * 0.7)
        self.lay(where, np.broadcast_to(np.float32(1.0), solid.shape + (3,)), cup * np.clip(gleam, 0, 1) * 0.55)

    def gas(self, puffs, solid):
        where, cover = self.cover(puffs, 12)
        cloud = blur(cover, 2.6)
        glow = blur(cover, 4.0)
        lit = np.clip(nudged(glow, -3, -4) - glow, -1, 1)                       # billowing: lit from the upper left
        self.lay(where, GAS * ((0.86 + 0.14 * depth(cover, 6.0)) * (1 + 0.5 * lit))[..., None], cloud * (0.82 * solid))

    def finish(self):
        """The picture, as the colour and how solid it is at each pixel."""
        colour = np.where(self.solid[..., None] > 1e-4, self.colour / np.maximum(self.solid[..., None], 1e-4), 0)
        return (np.clip(np.dstack([colour, self.solid]), 0, 1) * 255 + 0.5).astype(np.uint8)


def main():
    # Fleece is all fine detail, which would not pack down without loss. Saved like a photo.
    domo.build_pack(PACK, "Plush Domo", painter=Plush, sheet=HERE / "sheet.png" if "--sheet" in sys.argv else None,
                    lossless=False, quality=90, alpha_quality=100, method=4, use_sharp_yuv=True)


if __name__ == "__main__":
    main()
