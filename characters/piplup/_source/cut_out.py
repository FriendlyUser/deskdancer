#!/usr/bin/env python3
"""Cuts the character off the pink background (and its thin white sticker border).

    python3 cut_out.py up4.png cutout4.png

Background = light pink / white pixels reached from the image border. Raindrops and
sparkles are separate islands and are dropped by keeping the biggest piece. Edge pixels
are un-mixed from the white border towards the nearby solid art colour so the dark
outline keeps its antialiasing without a white fringe.
"""
import sys

import cv2
import numpy as np
from PIL import Image


def main(src, dst):
    rgb = np.asarray(Image.open(src).convert("RGB"), np.float32) / 255
    h, w, _ = rgb.shape
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    light = (r >= 240 / 255) & (g >= 212 / 255) & (b >= 235 / 255)

    _, labels = cv2.connectedComponents(light.astype(np.uint8), connectivity=4)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    bg = np.isin(labels, border[border != 0])

    # Keep only the biggest non-background piece (drops raindrops and sparkles).
    count, lab, stats, _ = cv2.connectedComponentsWithStats((~bg).astype(np.uint8), connectivity=8)
    biggest = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    fg = lab == biggest
    bg = ~fg

    # Edge pixels: how far each is from white, towards the colour of the solid art nearby.
    dist_in = cv2.distanceTransform(fg.astype(np.uint8), cv2.DIST_L2, 5)
    dist_out = cv2.distanceTransform(bg.astype(np.uint8), cv2.DIST_L2, 5)
    solid = (dist_in > 4).astype(np.float32)
    weight = cv2.GaussianBlur(solid, (0, 0), 5) + 1e-6
    art = cv2.GaussianBlur(rgb * solid[..., None], (0, 0), 5) / weight[..., None]
    white = np.array([1.0, 0.99, 1.0], np.float32)
    toward = white - art
    away = white - rgb
    norm = (toward * toward).sum(axis=2)
    alpha = np.where(norm > 0.04, (away * toward).sum(axis=2) / np.maximum(norm, 1e-6), 1)
    alpha = np.clip(alpha, 0, 1)
    alpha = np.clip((alpha - 0.04) / 0.92, 0, 1)
    alpha = np.where(solid > 0, 1, alpha)
    alpha = np.where(bg & (dist_out > 2.5), 0, alpha)

    unmixed = (rgb - (1 - alpha[..., None]) * white) / np.maximum(alpha[..., None], 1e-3)
    t = np.clip((alpha - 0.35) / 0.5, 0, 1)[..., None]
    colour = np.clip(art + (unmixed - art) * t, 0, 1)
    colour = np.where(solid[..., None] > 0, rgb, colour)

    out = np.dstack([colour, alpha])
    Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGBA").save(dst)
    ys, xs = np.nonzero(alpha > 0.01)
    print(f"saved {dst} {w}x{h}; art bbox x {xs.min()}..{xs.max()} y {ys.min()}..{ys.max()}")


if __name__ == "__main__":
    main(*sys.argv[1:])
