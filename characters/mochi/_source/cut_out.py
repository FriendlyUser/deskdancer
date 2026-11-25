#!/usr/bin/env python3
"""Cuts the character out of a photo and saves it with a transparent background.

    python3 cut_out.py photo.png BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx cutout.png

The model is BiRefNet (MIT licence), as packaged by the rembg project:
https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx
Needs numpy, pillow, opencv-python-headless and onnxruntime.
"""
import sys

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image


def main(photo_path, model_path, out_path):
    photo = Image.open(photo_path).convert("RGB")
    w, h = photo.size

    # BiRefNet wants a 1024x1024 ImageNet-normalised image and returns logits.
    session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    x = np.asarray(photo.resize((1024, 1024), Image.LANCZOS), np.float32) / 255
    x = (x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    logits = session.run(None, {session.get_inputs()[0].name: x.transpose(2, 0, 1)[None].astype(np.float32)})[0][0, 0]
    mask = cv2.resize((1 / (1 + np.exp(-logits))).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    alpha = np.clip((mask - 0.03) / 0.94, 0, 1)

    # Keep only the biggest blob, so specks of background do not come along.
    count, labels, stats, _ = cv2.connectedComponentsWithStats((alpha > 0.5).astype(np.uint8))
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    keep = cv2.dilate((labels == biggest).astype(np.uint8), np.ones((5, 5), np.uint8))
    alpha *= cv2.GaussianBlur(keep.astype(np.float32), (0, 0), 1.0)

    # Edge pixels still carry some of the old background colour. Pull their colour from
    # the solid inside of the character instead, so the outline looks clean on any desktop.
    rgb = np.asarray(photo, np.float32) / 255
    solid = cv2.erode((alpha > 0.97).astype(np.float32), np.ones((3, 3), np.uint8))
    weight = cv2.GaussianBlur(solid, (0, 0), 4) + 1e-6
    inside = cv2.GaussianBlur(rgb * solid[..., None], (0, 0), 4) / weight[..., None]
    edge = (1 - solid)[..., None] * (1 - alpha[..., None] ** 2)
    rgb = rgb * (1 - edge) + inside * edge

    out = np.dstack([rgb, alpha])
    Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA").save(out_path)
    print(f"saved {out_path} ({w}x{h})")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
