# How Lyra was made

Lyra started as one drawing, by **@thaissingarts**. Please keep this credit with the pack.
The artist's signature was taken off the white margin of the picture so that it would not
float beside her on the desktop. The app never reads this folder (its name starts with `_`);
it is here so the animations can be changed and rebuilt.

| File | What it is |
| --- | --- |
| `original.png` | The drawing as received (504 x 534), minus the signature. |
| `upscale.py` | Enlarges it 4x with Real-ESRGAN's anime model, which sharpens the line art. Runs without PyTorch. |
| `cut_out.py` | Takes her off the white background and saves `cutout.png`. |
| `cutout.png` | The result, at twice the original size, on a transparent background. |
| `make_frames.py` | Builds every animation and `character.json` from `cutout.png`. |

## Rebuilding

To change the animations, only the last step is needed:

```bash
pip install numpy pillow opencv-python-headless
python3 make_frames.py
```

It takes about five minutes and overwrites the clips and `character.json` in the folder
above. Then right-click the mate and choose **Character > Reload characters**.
`python3 make_frames.py --sheet` also saves `sheet.png` with every frame on one page, and
`python3 make_frames.py idle drag` rebuilds only the clips named.

To redo `cutout.png` from the original as well:

```bash
pip install onnx onnxruntime
curl -LO https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth
python3 upscale.py original.png RealESRGAN_x4plus_anime_6B.pth upscaled.png
python3 cut_out.py upscaled.png cutout.png
```

## How it works

**Cut-out.** The drawing is on plain white, so no model is needed: the white is filled in
from the edges, and each edge pixel is split into how much of it is drawing and what colour
that drawing is. That keeps the smooth edges without leaving a white fringe on a dark
desktop. The hole inside the left earring is background too and is cleared. The right shoe
was cropped off at the bottom of the original, so the end of its sole is drawn back in.

**Face.** The eyes and mouth are painted out with skin that blends in from all round their
edges, then redrawn: blinks squeeze the drawn eye shut, closed and smiling (`^ ^`) eyes
are drawn as tapered lash strokes, and there are singing, smiling and surprised mouths.

**Hair.** The two long falls of hair are bent by a smooth warp. The warp does nothing to
the face, body or lute and grows towards the tips, so the hair swings without tearing.
Each fall is a damped spring hung from her body: when she leans, hops or whips round, the
hair is left behind, swings back and settles. Every clip is run through the spring a few
times before it is recorded, so the loops are seamless.

**Hand.** The open hand bends at the wrist to wave. When it lifts, the top of the sash
behind it shows; that part is painted in by carrying the sash's own colours upwards, so
its folds and outline continue unbroken.

Every clip is drawn on the same canvas with the feet in the same place, then trimmed to
the part it uses, which keeps the pack quick to load. `character.json` records where the
feet are in each clip (`anchor`), so nothing jumps between clips.

| Clip | When the app shows it |
| --- | --- |
| `idle.webp` | Standing, and while walking (the app adds the breathing and the waddle). Blinks, a breeze through her hair, and now and then a little wave. |
| `dance.webp` | During all 15 built-in dance moves, which add their own body motion: happy eyes, singing on one beat and grinning on the next, her hand pumping and her hair bouncing. Also listed as **Sing Along**. |
| `dance_serenade.webp`, `dance_hair_flip.webp`, `dance_wave.webp` | Their own entries under **Dance move**: Serenade, Hair Flip and Wave Hello. Each is four beats at the default 120 BPM. Clip dances get no motion from the app, so the sways and hops are drawn in. |
| `drag.webp` | Being carried, and falling: wide eyes, a little "o", her hand flapping and her hair fluttering. |
| `sleep.png` | Napping. The app adds the breathing and the Zs. |

Sitting has no clip of its own; the app squashes the idle picture.

## Changing things

Each clip is a short function near the end of `make_frames.py` (`idle`, `happy_dance`,
`serenade`, `hair_flip`, `wave_hello`, `dangle`, `sleep`) that returns a list of
`(pose, milliseconds)`. A pose can set:

- `eyes`: a pair, each `"open"`, `"closed"`, `"happy"`, `"wide"`, or a number from 0 to 1
  for an eye part way shut
- `mouth`: `"grin"` (as drawn), `"sing"`, `"smile"` or `"o"`
- `hand`: degrees the fingertips lift at the wrist (negative lowers them)
- `hair`: how far the tip of each fall moves, `{"L": (dx, dy), "R": (dx, dy)}`. Clips
  usually get this from a `Hair` spring driven by the body's motion.
- `lean` (degrees, positive tips right), `squash` (positive is shorter and wider), `dx`,
  `dy` (pixels of `cutout.png`; negative `dy` is up)

To add a dance, write another function and add a line to `CLIPS`; any key starting with
`dance_` appears under **Dance move**.
