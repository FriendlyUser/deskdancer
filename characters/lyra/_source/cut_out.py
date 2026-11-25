#!/usr/bin/env python3
"""Cuts Lyra out of the upscaled drawing and saves her on a transparent background.

    python3 cut_out.py upscaled.png cutout.png

upscaled.png is original.png after upscale.py (4x). The drawing sits on plain white, so
no model is needed: the white is flood-filled in from the edges, and every edge pixel is
split into "how much of it is drawing" and "what colour the drawing is" by measuring how
far it sits from white towards the colour of the solid line art next to it. That keeps
the antialiasing and leaves no white fringe on a dark desktop.

Two repairs are made on the way. The hole inside the left earring hoop is background too,
although it is not connected to the edge. And the right shoe's sole was cropped off at the
bottom of the original picture, so its outline is drawn back in.

The result is saved at half the upscaled size (2x the original), which is what
make_frames.py works from. Needs numpy, pillow and opencv-python-headless.
"""
import sys

import cv2
import numpy as np
from PIL import Image

UP = 4                          # upscale factor of the input
PAD = 48                        # room added at the bottom, in input pixels, for the sole
EARRING_HOLE = (149, 327)       # a point inside the left earring's hole, in original pixels
WHITE_MIN = 235                 # a pixel is background-white if all channels reach this


def repair_sole(rgb, alpha, bottom):
    """The sole's outline runs off the bottom of the picture. Continue the silhouette on
    both sides along its own slope and round it off underneath, filled with outline ink."""
    h = bottom                                  # first padded row
    drawn = alpha > 0.5
    dark = drawn & (rgb.max(axis=2) < 0.3)
    rows = range(h - 8, h)
    lefts = np.array([np.nonzero(drawn[y])[0].min() for y in rows], float)
    rights = np.array([np.nonzero(drawn[y])[0].max() for y in rows], float)
    ys = np.array(list(rows), float)
    kl = np.polyfit(ys, lefts, 1)[0]            # x change per row on each side
    kr = np.polyfit(ys, rights, 1)[0]
    x0, x1 = lefts[-1], rights[-1]
    ink = np.median(rgb[h - 1, int(x0):int(x1) + 1][dark[h - 1, int(x0):int(x1) + 1]], axis=0)

    # Bottom edge as a function of x: a cubic from each side, leaving with the side's slope
    # and arriving flat at the lowest point.
    depth = 2.5 * UP                            # how far the outline reaches below the cut
    mid = (x0 + x1) / 2

    def edge(x):
        if x <= mid:
            u, s, half = (x - x0) / (mid - x0), 1 / max(kl, 0.2), mid - x0
        else:
            u, s, half = (x1 - x) / (x1 - mid), 1 / max(-kr, 0.2), x1 - mid
        # Hermite from (0, 0) with slope s*half/depth to (1, 1) with slope 0.
        m0 = min(s * half / depth, 3.0)
        return depth * ((u ** 3 - 2 * u ** 2 + u) * m0 + (-2 * u ** 3 + 3 * u ** 2))

    ss = 4
    xs = np.arange(int(x0) - 2, int(x1) + 3)
    cov = np.zeros((PAD * UP, len(xs)), np.float32)
    for i, x in enumerate(xs):
        acc = np.zeros(PAD * UP, np.float32)
        for k in range(ss):
            xx = x + (k + 0.5) / ss - 0.5
            if xx < x0 or xx > x1:
                continue
            e = edge(xx)
            yy = np.arange(PAD * UP) + 0.5
            acc += np.clip(e - (yy - 0.5), 0, 1)
        cov[:, i] = acc / ss
    region = rgb[h:h + PAD * UP, xs[0]:xs[-1] + 1]
    alpha = np.zeros(region.shape[:2], np.float32)
    region[:] = ink
    alpha[:] = cov
    return xs[0], alpha


def main(src, dst):
    up = np.asarray(Image.open(src).convert("RGB"), np.float32) / 255
    h, w, _ = up.shape
    rgb = np.ones((h + PAD * UP, w, 3), np.float32)
    rgb[:h] = up

    # Background: near-white, reached from the border, plus the earring hole.
    white = (rgb.min(axis=2) >= WHITE_MIN / 255).astype(np.uint8)
    white[h:] = 1
    _, labels = cv2.connectedComponents(white, connectivity=4)
    bg_ids = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    hole = labels[EARRING_HOLE[1] * UP, EARRING_HOLE[0] * UP]
    assert hole != 0 and hole not in bg_ids, "earring hole not found"
    bg_ids.add(hole)
    bg = np.isin(labels, list(bg_ids))

    # Edge pixels: how far each is from white, towards the colour of the solid art nearby.
    dist_in = cv2.distanceTransform((~bg).astype(np.uint8), cv2.DIST_L2, 5)
    dist_out = cv2.distanceTransform(bg.astype(np.uint8), cv2.DIST_L2, 5)
    solid = (dist_in > 2.5 * UP / 2).astype(np.float32)
    weight = cv2.GaussianBlur(solid, (0, 0), 1.5 * UP) + 1e-6
    art = cv2.GaussianBlur(rgb * solid[..., None], (0, 0), 1.5 * UP) / weight[..., None]
    toward = 1 - art                                # white minus art colour
    away = 1 - rgb                                  # white minus pixel colour
    norm = (toward * toward).sum(axis=2)
    alpha = np.where(norm > 0.08, (away * toward).sum(axis=2) / np.maximum(norm, 1e-6), 1)
    alpha = np.clip(alpha, 0, 1)
    alpha = np.clip((alpha - 0.03) / 0.94, 0, 1)
    alpha = np.where(solid > 0, 1, alpha)
    alpha = np.where(bg & (dist_out > 2.5), 0, alpha)

    # Colour of edge pixels: what is left after taking the white back out, trusting it less
    # (and the nearby art more) the fainter the pixel is.
    unmixed = (rgb - (1 - alpha[..., None])) / np.maximum(alpha[..., None], 1e-3)
    t = np.clip((alpha - 0.35) / 0.5, 0, 1)[..., None]
    colour = np.clip(art + (unmixed - art) * t, 0, 1)
    colour = np.where(solid[..., None] > 0, rgb, colour)

    # The cropped sole.
    x_start, sole_alpha = repair_sole(colour, alpha, h)
    sh, sw = sole_alpha.shape
    alpha[h:h + sh, x_start:x_start + sw] = np.maximum(alpha[h:h + sh, x_start:x_start + sw], sole_alpha)
    # Soften the seam where the old picture ended.
    seam = slice(h - 2, h + 2)
    colour[seam, x_start:x_start + sw] = cv2.GaussianBlur(colour[h - 6:h + 6, x_start:x_start + sw], (0, 0), 1.0)[4:8]

    # Drop specks the flood fill left behind.
    count, lab, stats, _ = cv2.connectedComponentsWithStats((alpha > 0.5).astype(np.uint8), connectivity=8)
    keep = np.zeros(count, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= 60 * UP * UP / 4
    near = cv2.dilate(keep[lab].astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    alpha = np.where(near, alpha, 0)

    # Premultiply, halve, trim.
    pre = np.dstack([colour * alpha[..., None], alpha])
    half = cv2.resize(pre, (w // 2, (h + PAD * UP) // 2), interpolation=cv2.INTER_AREA)
    a = half[..., 3:]
    rgb_out = np.where(a > 1e-4, half[..., :3] / np.maximum(a, 1e-4), 0)
    out = np.dstack([np.clip(rgb_out, 0, 1), a])
    ys, xs = np.nonzero(out[..., 3] > 0.002)
    out = out[:ys.max() + 4]
    Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGBA").save(dst, optimize=True)
    print(f"saved {dst} ({out.shape[1]}x{out.shape[0]}), feet at y={ys.max()}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
