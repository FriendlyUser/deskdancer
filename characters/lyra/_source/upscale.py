#!/usr/bin/env python3
"""Upscales a drawing 4x with Real-ESRGAN's anime model, without needing PyTorch.

    python3 upscale.py drawing.png RealESRGAN_x4plus_anime_6B.pth out.png

The weights (BSD-3-Clause) are at
https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth
The network (RRDBNet, 6 blocks) is rebuilt as an ONNX graph and run with onnxruntime,
in overlapping tiles so memory stays small. Needs numpy, pillow, onnx and onnxruntime.
"""
import pickle
import sys
import zipfile

import numpy as np
import onnx
import onnxruntime as ort
from onnx import TensorProto, helper, numpy_helper
from PIL import Image


def load_weights(path):
    """Reads a PyTorch zip checkpoint into numpy arrays. Only tensors are rebuilt; any
    other object in the pickle is refused, so the file cannot run code."""
    z = zipfile.ZipFile(path)
    prefix = z.namelist()[0].split("/")[0]
    dtypes = {"FloatStorage": np.float32, "HalfStorage": np.float16}

    def rebuild(storage, offset, size, stride, *_):
        arr = storage[offset:]
        if not size:
            return arr[:1].reshape(())
        return np.lib.stride_tricks.as_strided(arr, size, [s * arr.itemsize for s in stride]).copy()

    class Unpickler(pickle.Unpickler):
        def find_class(self, module, name):
            if (module, name) == ("torch._utils", "_rebuild_tensor_v2"):
                return rebuild
            if (module, name) == ("collections", "OrderedDict"):
                import collections
                return collections.OrderedDict
            if module == "torch" and name in dtypes:
                return name
            raise pickle.UnpicklingError(f"refusing {module}.{name}")

        def persistent_load(self, pid):
            _, kind, key, _, _ = pid
            return np.frombuffer(z.read(f"{prefix}/data/{key}"), dtypes[kind])

    with z.open(f"{prefix}/data.pkl") as f:
        state = Unpickler(f).load()
    return state.get("params_ema", state.get("params", state))


def build_model(w):
    nodes, inits = [], []
    count = [0]

    def name(base):
        count[0] += 1
        return f"{base}_{count[0]}"

    def conv(x, key):
        out = name(key)
        inits.append(numpy_helper.from_array(w[key + ".weight"].astype(np.float32), key + ".weight"))
        inits.append(numpy_helper.from_array(w[key + ".bias"].astype(np.float32), key + ".bias"))
        nodes.append(helper.make_node("Conv", [x, key + ".weight", key + ".bias"], [out], pads=[1, 1, 1, 1]))
        return out

    def lrelu(x):
        out = name("lrelu")
        nodes.append(helper.make_node("LeakyRelu", [x], [out], alpha=0.2))
        return out

    def cat(xs):
        out = name("cat")
        nodes.append(helper.make_node("Concat", xs, [out], axis=1))
        return out

    def axpy(a, x, y):          # a * x + y
        k = name("k")
        inits.append(numpy_helper.from_array(np.array(a, np.float32), k))
        m, out = name("mul"), name("add")
        nodes.append(helper.make_node("Mul", [x, k], [m]))
        nodes.append(helper.make_node("Add", [m, y], [out]))
        return out

    def up2(x):
        sc = name("scales")
        inits.append(numpy_helper.from_array(np.array([1, 1, 2, 2], np.float32), sc))
        out = name("up")
        nodes.append(helper.make_node("Resize", [x, "", sc], [out], mode="nearest"))
        return out

    def rdb(x, key):
        feats = [x]
        for i in range(1, 5):
            feats.append(lrelu(conv(cat(feats) if len(feats) > 1 else x, f"{key}.conv{i}")))
        return axpy(0.2, conv(cat(feats), f"{key}.conv5"), x)

    blocks = sorted({int(k.split(".")[1]) for k in w if k.startswith("body.")})
    feat = conv("input", "conv_first")
    x = feat
    for b in blocks:
        y = x
        for r in (1, 2, 3):
            y = rdb(y, f"body.{b}.rdb{r}")
        x = axpy(0.2, y, x)
    body = conv(x, "conv_body")
    s = name("sum")
    nodes.append(helper.make_node("Add", [feat, body], [s]))
    x = lrelu(conv(up2(s), "conv_up1"))
    x = lrelu(conv(up2(x), "conv_up2"))
    x = conv(lrelu(conv(x, "conv_hr")), "conv_last")
    nodes.append(helper.make_node("Identity", [x], ["output"]))
    graph = helper.make_graph(nodes, "rrdbnet",
                              [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, None, None])],
                              [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3, None, None])], inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=8)
    onnx.checker.check_model(model)
    return model.SerializeToString()


def upscale(img, session, tile=160, pad=16):
    h, w, _ = img.shape
    out = np.zeros((h * 4, w * 4, 3), np.float32)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            y0, x0 = max(0, y - pad), max(0, x - pad)
            y1, x1 = min(h, y + tile + pad), min(w, x + tile + pad)
            part = img[y0:y1, x0:x1].transpose(2, 0, 1)[None]
            res = session.run(None, {"input": part})[0][0].transpose(1, 2, 0)
            ty, tx = (y - y0) * 4, (x - x0) * 4
            th, tw = min(tile, h - y) * 4, min(tile, w - x) * 4
            out[y * 4:y * 4 + th, x * 4:x * 4 + tw] = res[ty:ty + th, tx:tx + tw]
            print(f"  tile {y},{x}", flush=True)
    return np.clip(out, 0, 1)


def main(src, weights, dst):
    model = build_model(load_weights(weights))
    opts = ort.SessionOptions()
    session = ort.InferenceSession(model, opts, providers=["CPUExecutionProvider"])
    img = np.asarray(Image.open(src).convert("RGB"), np.float32) / 255
    out = upscale(img, session)
    Image.fromarray((out * 255 + 0.5).astype(np.uint8)).save(dst)
    print(f"saved {dst} ({out.shape[1]}x{out.shape[0]})")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
