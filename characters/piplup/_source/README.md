# How Piplup was made

Piplup started as one fan drawing whose watermark reads **@ros…** (the rest of the handle
is cut off in the copy received). Please keep this credit with the pack. Piplup is a
Pokémon and belongs to Nintendo, Creatures and Game Freak, who had no part in this pack.
The app never reads this folder (its name starts with `_`).

| File | What it is |
| --- | --- |
| `original.png` | The drawing as received (247 x 298), on its pink background with the watermark. |
| `cut_out.py` | Takes the character off the pink background and its thin white sticker border. |
| `straighten.py` | Stands the cut-out upright on a level floor. |

`idle.png` in the folder above is the result at twice the original size. It is a single
still: the app adds the breathing, waddle, sitting, napping and dance moves itself.

## Rebuilding

```bash
pip install numpy pillow opencv-python-headless onnx onnxruntime
curl -LO https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth
python3 -c "from PIL import Image; Image.open('original.png').convert('RGB').save('rgb.png')"
python3 ../../lyra/_source/upscale.py rgb.png RealESRGAN_x4plus_anime_6B.pth up4.png
python3 cut_out.py up4.png cutout4.png
python3 straighten.py cutout4.png straight4.png
```

Then halve `straight4.png` (premultiplied, area filter) and save it as `../idle.png`.

## How it works

**Cut-out.** The light pink and white reached from the edges of the picture is background.
The raindrops and sparkles are separate islands, so only the biggest piece is kept. Edge
pixels are un-mixed from the white sticker border towards the colour of the solid art
next to them, which keeps the dark outline smooth with no white fringe on a dark desktop.

**Straightening.** The drawing was tilted, with one foot higher than the other. Three
smooth steps fix that without redrawing anything: the whole figure is turned 3.6° so the
head sits above the point between the feet, a slight vertical shear brings both soles to
the same floor line, and the inside of the head is turned a further 4° about its centre
so the eyes are level. The head is a circle, so its outline does not move when it turns.
