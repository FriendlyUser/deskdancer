#!/usr/bin/env python3
"""Turns a small, blurry photo of the character into a clean cut-out, four times larger.

    python3 cut_out.py photo.png MODELS_DIR cutout.png

Two models do the work, both free to use, and MODELS_DIR must hold their files:

  realesrgan-x4plus-anime.param / .bin   Real-ESRGAN (BSD licence). Redraws the picture at
      four times the size, sharp and free of JPEG blocks. They are in the "models" folder of
      https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-ubuntu.zip
  BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx   BiRefNet (MIT licence). Finds the character.
      https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx

Needs numpy, pillow, opencv-python-headless, onnxruntime and ncnn (all from pip).
"""
import sys
from pathlib import Path

import cv2
import ncnn
import numpy as np
import onnxruntime as ort
from PIL import Image

SCALE = 4


def upscale(rgb, models):
    """Real-ESRGAN, on the CPU. rgb is float 0..1; returns the same, four times the size."""
    net = ncnn.Net()
    net.opt.use_vulkan_compute = False
    net.load_param(str(models / "realesrgan-x4plus-anime.param"))
    net.load_model(str(models / "realesrgan-x4plus-anime.bin"))
    pad = 16                                    # mirrored border, so the picture's edges come out clean
    padded = np.pad(rgb, ((pad, pad), (pad, pad), (0, 0)), mode="reflect")
    planes = np.ascontiguousarray(padded.transpose(2, 0, 1), dtype=np.float32)
    ex = net.create_extractor()
    ex.input("data", ncnn.Mat(planes).clone())  # clone: a Mat only borrows the numpy buffer
    _, out = ex.extract("output")
    big = np.array(out).transpose(1, 2, 0)
    return np.clip(big[pad * SCALE:-pad * SCALE, pad * SCALE:-pad * SCALE], 0, 1)


def find_character(rgb, models):
    """BiRefNet's opinion of which pixels are the character, 0..1, same size as rgb."""
    h, w = rgb.shape[:2]
    session = ort.InferenceSession(str(models / "BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx"),
                                   providers=["CPUExecutionProvider"])
    x = cv2.resize(rgb, (1024, 1024), interpolation=cv2.INTER_AREA)
    x = (x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    logits = session.run(None, {session.get_inputs()[0].name: x.transpose(2, 0, 1)[None].astype(np.float32)})[0][0, 0]
    return cv2.resize((1 / (1 + np.exp(-logits))).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)


def disc(radius):
    k = int(round(radius)) * 2 + 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def soften(mask):
    """A hard yes/no mask as a soft-edged amount to remove, a little wider than the mask."""
    wide = cv2.dilate(mask.astype(np.uint8), disc(2)).astype(np.float32)
    return np.clip(cv2.GaussianBlur(wide, (0, 0), 1.0) * 1.6, 0, 1)


def spot(shape, x, y, radius):
    """A round spot given in photo pixels: 1 in the middle, fading to 0 at its rim so that
    whatever is done inside it leaves no step where it stops."""
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    return np.clip((1 - np.hypot(xx - x * SCALE, yy - y * SCALE) / (radius * SCALE)) / 0.35, 0, 1)


def drop_leaks(rgb, alpha, leaks):
    """In the tight corner where an ear meets the head, a little pavement gets taken for
    character. Within each spot, whatever touches the outside and is darker than the skin
    there is not character: the really dark part is removed, and the paler fringe it leaves
    along the outline is marked to be repainted, which keeps the outline where it is. Also
    returns those marks."""
    dirty = np.zeros(alpha.shape, bool)
    for x, y, radius, darkest_skin in leaks:
        # Both bars ease off towards the rim of the spot, so nothing stops at a hard line.
        here = spot(alpha.shape, x, y, radius)
        inside = alpha > 0.5
        value = rgb.max(-1)
        _, labels = cv2.connectedComponents((((value < 0.45 + (darkest_skin - 0.45) * here) & inside) | ~inside).astype(np.uint8))
        fringe = inside & (labels == labels[0, 0])
        leak = fringe & (value < 0.45 + (0.62 - 0.45) * here)
        alpha = alpha * (1 - soften(leak))
        # Removing it leaves slots and ledges a pixel or two deep. Close the slots, then
        # round the outline off.
        solid = (alpha > 0.5).astype(np.uint8)
        closed = cv2.morphologyEx(solid, cv2.MORPH_CLOSE, disc(SCALE * 1.25)).astype(np.float32)
        rounded = np.clip((cv2.GaussianBlur(np.maximum(alpha, closed), (0, 0), 3.0) - 0.5) / 0.3 + 0.5, 0, 1)
        blend = np.clip(here * 3, 0, 1)
        alpha = alpha * (1 - blend) + rounded * blend
        dirty |= cv2.dilate((fringe | ((closed > 0) & (solid == 0))).astype(np.uint8), disc(5)).astype(bool)
    return alpha, dirty


def trim_spurs(alpha, spurs):
    """Where something bright in the background touched the character it leaves a spur on
    the outline. Within each spot, knock off anything narrower than half the spot."""
    solid = (alpha > 0.5).astype(np.uint8)
    for x, y, radius in spurs:
        opened = cv2.morphologyEx(solid, cv2.MORPH_OPEN, disc(radius * SCALE * 0.5))
        here = spot(alpha.shape, x, y, radius)
        alpha = alpha * (1 - soften((solid == 1) & (opened == 0) & (here > 0)) * here)
    return alpha


def heal(rgb, alpha, spurs):
    """A spur also leaves a streak of the wrong colour running into the character. Fill each
    spot from the skin around it: every pixel in the spot becomes the average of its
    neighbours, ignoring anything outside the character, until it settles."""
    kernel = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], np.float32)
    for x, y, radius in spurs:
        cx, cy, r = int(x * SCALE), int(y * SCALE), int(radius * SCALE)
        ys, xs = slice(cy - r - 8, cy + r + 8), slice(cx - r - 8, cx + r + 8)
        valid = (alpha[ys, xs] > 0.5).astype(np.float32)
        hole = (spot(alpha.shape, x, y, radius)[ys, xs] > 0) & (valid > 0)
        known = valid * ~hole
        patch = rgb[ys, xs].copy()
        guess = (cv2.GaussianBlur(patch * known[..., None], (0, 0), r / 2)
                 / (cv2.GaussianBlur(known, (0, 0), r / 2)[..., None] + 1e-6))
        patch[hole] = guess[hole]
        for _ in range(600):
            total = cv2.filter2D(patch * valid[..., None], -1, kernel, borderType=cv2.BORDER_REPLICATE)
            count = cv2.filter2D(valid, -1, kernel, borderType=cv2.BORDER_REPLICATE)[..., None]
            patch[hole] = (total / np.maximum(count, 1e-6))[hole]
        soft = cv2.GaussianBlur(hole.astype(np.float32), (0, 0), 1.5)[..., None]
        rgb[ys, xs] = rgb[ys, xs] * (1 - soft) + patch * soft
    return rgb


def round_off_top(rgb, alpha, rise):
    """The very top of the head is cut off by the top of the photo, which leaves it flat.
    Add `rise` rows above the picture and carry the outline on across the gap, leaving
    each side at the slope it arrives with."""
    reach = 3 * SCALE
    run, below = np.nonzero(alpha[0] > 0.5)[0], np.nonzero(alpha[reach] > 0.5)[0]
    rgb = np.vstack([np.repeat(rgb[:1], rise, axis=0), rgb])
    alpha = np.vstack([np.zeros((rise, alpha.shape[1]), np.float32), alpha])
    if len(run):
        x0, x1 = run[0], run[-1]
        m0 = reach / min(below[0] - x0, -1) * (x1 - x0)         # slope of the outline, left and right,
        m1 = reach / max(below[-1] - x1, 1) * (x1 - x0)         # scaled to the width of the gap
        yy, xx = np.mgrid[0:rise + reach, 0:alpha.shape[1]].astype(np.float32)
        u = np.clip((xx - x0) / (x1 - x0), 0, 1)
        curve = m0 * (u ** 3 - 2 * u ** 2 + u) + m1 * (u ** 3 - u ** 2)     # rows above the old top, negative
        curve *= min(1.0, (rise - 1.5) / -curve.min())
        cap = np.clip(yy - (rise + curve) + 0.5, 0, 1) * (xx >= x0) * (xx <= x1)
        alpha[:rise + reach] = np.maximum(alpha[:rise + reach], cap)
    return rgb, alpha


# Marks the background left on this particular photo, in pixels of the photo.
LEAKS = [(124, 41.5, 12, 0.76), (281.5, 80, 6, 0.80), (289, 87, 9, 0.84)]    # x, y, radius, brightness of the darkest skin there
SPURS = [(119.5, 114, 7)]                               # x, y, radius
# Rows added above the photo to finish the top of the head, in photo pixels. make_frames.py
# needs to know: it is TOP_PAD there.
TOP_PAD = 2


def main(photo_path, models_dir, out_path):
    models = Path(models_dir)
    photo = np.asarray(Image.open(photo_path).convert("RGB"), np.float32) / 255
    rgb = upscale(photo, models)
    mask = find_character(rgb, models)

    # Keep only the biggest blob, so specks of background do not come along.
    _, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 0.5).astype(np.uint8))
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    keep = cv2.dilate((labels == biggest).astype(np.uint8), np.ones((9, 9), np.uint8))
    mask = mask * cv2.GaussianBlur(keep.astype(np.float32), (0, 0), 2.0)

    # The mask's edge is a few pixels wide and sits right on the outline. Tighten it to a
    # crisp edge just inside the outline, so no background shows along it.
    alpha = np.clip((cv2.GaussianBlur(mask, (0, 0), 1.2) - 0.52) / 0.30, 0, 1)
    alpha = alpha * alpha * (3 - 2 * alpha)
    alpha, dirty = drop_leaks(rgb, alpha, LEAKS)
    alpha = trim_spurs(alpha, SPURS)

    # Edge pixels still carry some of the old background colour. Take their colour from
    # the solid inside of the character instead, so the outline is clean on any desktop.
    solid = cv2.erode(((alpha > 0.98) & ~dirty).astype(np.float32), np.ones((5, 5), np.uint8))
    weight = cv2.GaussianBlur(solid, (0, 0), 6) + 1e-6
    inside = cv2.GaussianBlur(rgb * solid[..., None], (0, 0), 6) / weight[..., None]
    edge = (1 - solid)[..., None]
    rgb = rgb * (1 - edge) + inside * edge

    rgb = heal(rgb, alpha, SPURS)
    rgb, alpha = round_off_top(rgb, alpha, TOP_PAD * SCALE)

    out = np.dstack([rgb, alpha])
    out[alpha < 1 / 255] = 0
    Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA").save(out_path, optimize=True)
    print(f"saved {out_path} ({out.shape[1]}x{out.shape[0]}), {SCALE}x the photo plus {TOP_PAD * SCALE} rows on top")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
