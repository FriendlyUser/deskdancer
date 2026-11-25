#!/usr/bin/env python3
"""Stands the cut-out upright on a level floor.

    python3 straighten.py cutout4.png straight4.png

Three smooth geometric steps, all on the drawing's own pixels:
  1. turn the whole figure so the head sits straight above the point between the feet;
  2. a slight vertical shear so both feet (and the belly) are level;
  3. turn the inside of the head about its own centre so the eyes are level. The head is
     a circle, so its outline does not move; the turn fades out just past the outline.
"""
import sys

import cv2
import numpy as np
from PIL import Image

# Measured on cutout4.png (4x the original drawing).
HEAD_C = np.array([511.2, 384.2])
HEAD_R = 327.5
EYES = np.array([[380.2, 472.7], [727.9, 390.1]])
DOTS = np.array([[424.4, 827.5], [693.5, 801.6]])
FEET = np.array([[385.1, 1084.4], [723.2, 1036.8]])
SOLES = np.array([[385.0, 1146.0], [723.0, 1090.0]])   # lowest point under each foot
PAD = 80


def rot(p, c, deg):
    """Visual clockwise turn (y points down)."""
    t = np.radians(deg)
    d = p - c
    return c + np.stack([d[..., 0] * np.cos(t) - d[..., 1] * np.sin(t),
                         d[..., 0] * np.sin(t) + d[..., 1] * np.cos(t)], -1)


def angle(pair):
    d = pair[1] - pair[0]
    return np.degrees(np.arctan2(d[1], d[0]))


def plan():
    feet_mid = FEET.mean(0)
    v = HEAD_C - feet_mid
    turn = np.degrees(np.arctan2(-v[0], -v[1]))          # cw degrees that put the head on top
    pivot = feet_mid

    def step1(p):
        return rot(p, pivot, turn)

    s = step1(SOLES)
    k = -(s[1, 1] - s[0, 1]) / (s[1, 0] - s[0, 0])       # shear that levels the soles
    axis_x = step1(HEAD_C)[0]

    def step2(p):
        q = p.copy()
        q[..., 1] = q[..., 1] + k * (q[..., 0] - axis_x)
        return q

    hc = step2(step1(HEAD_C))
    e = step2(step1(EYES))
    head_turn = -angle(e)
    return dict(turn=turn, pivot=pivot, k=k, axis_x=axis_x, head_c=hc, head_turn=head_turn,
                step1=step1, step2=step2)


def main(src, dst):
    P = plan()
    print(f"body turn {P['turn']:.2f} deg cw, shear {P['k']:.4f}, head turn {P['head_turn']:.2f} deg")
    img = np.asarray(Image.open(src).convert("RGBA"), np.float32) / 255
    img[..., :3] *= img[..., 3:]                                   # premultiply
    h, w, _ = img.shape
    img = cv2.copyMakeBorder(img, PAD, PAD, PAD, PAD, cv2.BORDER_CONSTANT, value=0)
    off = np.array([PAD, PAD], float)

    H, W = h + 2 * PAD, w + 2 * PAD
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float64)
    q = np.stack([xs, ys], -1) - off                               # output, in cutout coords

    # Undo step 3: head turn, weighted by distance from the head centre.
    hc = P["head_c"]
    r = np.hypot(q[..., 0] - hc[0], q[..., 1] - hc[1])
    wgt = np.clip((HEAD_R + 30 - r) / 60, 0, 1)
    wgt = wgt * wgt * (3 - 2 * wgt)
    d = q - hc
    t = np.radians(-P["head_turn"]) * wgt
    q = hc + np.stack([d[..., 0] * np.cos(t) - d[..., 1] * np.sin(t),
                       d[..., 0] * np.sin(t) + d[..., 1] * np.cos(t)], -1)
    # Undo step 2: shear.
    q[..., 1] = q[..., 1] - P["k"] * (q[..., 0] - P["axis_x"])
    # Undo step 1: body turn.
    q = rot(q, P["pivot"], -P["turn"])

    q = q + off
    out = cv2.remap(img, q[..., 0].astype(np.float32), q[..., 1].astype(np.float32),
                    cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    out = np.clip(out, 0, 1)
    a = out[..., 3:]
    out[..., :3] = np.where(a > 1e-4, out[..., :3] / np.maximum(a, 1e-4), 0)
    out = np.clip(out, 0, 1)

    yy, xx = np.nonzero(out[..., 3] > 0.004)
    out = out[yy.min() - 4:yy.max() + 3, xx.min() - 4:xx.max() + 5]
    Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGBA").save(dst)

    # Report where the landmarks ended up.
    def fwd(p):
        p = P["step2"](P["step1"](p))
        return p
    e = fwd(EYES)
    e = rot(e, hc, P["head_turn"])
    print("eyes", angle(e).round(2), "dots", angle(fwd(DOTS)).round(2),
          "soles", angle(fwd(SOLES)).round(2), "feet", angle(fwd(FEET)).round(2))
    print(f"saved {dst} {out.shape[1]}x{out.shape[0]}")


if __name__ == "__main__":
    main(*sys.argv[1:])
