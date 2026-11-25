# How Mochi was made

Mochi started as one small photo. The app never reads this folder (its name starts with
`_`); it is here so the animations can be changed and rebuilt.

| File | What it is |
| --- | --- |
| `cutout.png` | The character, redrawn sharp at four times the photo's size and cut out of its background. |
| `cut_out.py` | How `cutout.png` was made from the photo. |
| `make_frames.py` | Builds every animation and `character.json` from `cutout.png`. |

## Rebuilding the animations

```bash
pip install numpy pillow opencv-python-headless
python3 make_frames.py
```

It takes about half a minute and overwrites the clips and `character.json` in the folder
above. Then right-click the mate and choose **Character > Reload characters**.
`python3 make_frames.py --sheet` also saves `sheet.png` with every frame on one page.
Running it twice gives the same files, byte for byte.

## How it works

**The picture.** The photo is small and soft, with JPEG blocks in it. `cut_out.py` first
has Real-ESRGAN redraw it at four times the size, which is where the clean edges and
crisp eyes come from, then has BiRefNet find the character, and then tidies what the
background left behind: a bit of pavement in the corner where each ear meets the head, a
spur where a crack touched the cheek, and the top of the head, which the photo cuts off.
The places it tidies are listed near the end of the script; they belong to this photo.
The colours are the photo's own.

**The rig.** `make_frames.py` takes the cut-out apart into a body, two ears and two
feet. The ears and feet sit behind the body. Each one stays attached along the line
where it joins the body and bends away from there, like skin, so it can swing a long way
without a gap or a crease opening; the ears also curl along their length. The head tilts
and nods on the neck, and the whole mate can squash, stretch, lean and jump. With nothing
moved, the parts add back up to the cut-out exactly.

**The face.** Blinks, closed eyes, happy `^ ^` eyes, wide eyes, three mouths and a blush
are painted over the face. Where an eye is hidden, the skin is filled in from all round
it, so no patch shows.

**The ears.** A clip does not pose the ears frame by frame. It says where they should
be, and a spring carries them there, pushed about by how the head is moving. That is why
they trail behind a hop, float at the top of it and flop on landing.

## The clips

| Clip | When the app shows it |
| --- | --- |
| `idle.webp` | Standing. Blinks, flicks an ear, tilts its head for a moment. |
| `walk.webp` | Wandering: a waddle from foot to foot. |
| `dance.webp` | During all 15 built-in dance moves, which add their own body motion. Also listed as **Happy Ears**. |
| `dance_bunny_hop.webp`, `dance_ear_wave.webp` | Their own entries under **Dance move**. Clip dances get no motion from the app, so the hops and sways are drawn in. |
| `drag.webp` | Being carried. |
| `fall.webp` | Dropping through the air. |
| `sleep.webp` | Napping. The app adds the breathing and the Zs. |

Sitting has no clip of its own; the app squashes the idle clip, which suits Mochi.

Frames are not free: while a clip is in use, the app has every frame of it unpacked in
memory. It unpacks a clip the first time the mate needs it and lets go of it again after
a minute without being shown. So the idle clip counts most, because it is there the
whole time (about 30 MB), with the clips for whatever the mate has been doing lately on
top. `make_frames.py` prints the total for all the clips when it finishes (about 90 MB).
Three things keep it down: the frames are saved at 1.1 times the photo's size (`OUT`),
which the sharp picture can afford; each clip is cropped to what it uses; and a frame is
held for as long as nothing has visibly moved, so standing still costs one frame, not
hundreds.

## Changing things

Each clip is a short function near the end of `make_frames.py` (`idle`, `walk`,
`happy_ears`, `bunny_hop`, `ear_wave`, `carried`, `falling`, `asleep`). It is given the
time in seconds and returns a pose. A pose can set:

- `eyes`: a pair, each `"open"`, `"closed"`, `"happy"`, `"wide"`, or a number from 0 to
  1 for an eyelid part way down
- `mouth`: `None` (as in the photo), `"smile"`, `"o"` or `"grin"`
- `blush`: 0 to 1
- `ears`: degrees each ear tip should be lifted (negative droops it), and `bend`:
  degrees of extra curl at the tip. The spring adds its own swing to both.
- `feet`: for each foot, degrees swung and pixels lifted
- `head`: degrees tilted (positive tips right), pixels right, pixels down
- `squash` (positive is shorter and wider), `lean` (degrees, positive tips right), and
  `dx`, `dy` for the whole mate (negative `dy` is up)

Distances are in pixels of the original photo. `CLIPS` lists each clip's length, how
many frames a second to sample it at, and whether it is a calm one. The clip must end as
it began, because it loops. To add a dance, write another function and add a line to
`CLIPS`; any key starting with `dance_` appears under **Dance move**.

The ears' springiness is set by `EAR_HZ`, `EAR_DAMPING`, `EAR_PUSH` and `EAR_CURL`, just
above the clips.

## Rebuilding the cut-out

Only needed to start again from the photo, or from a different one.

```bash
pip install numpy pillow opencv-python-headless onnxruntime ncnn
python3 cut_out.py photo.png MODELS_DIR cutout.png
```

`MODELS_DIR` is a folder holding the two models; the top of `cut_out.py` says where to
download them. A different photo will need its own list of places to tidy, and the
outlines at the top of `make_frames.py` (where the ears and feet join the body) redrawn
to fit.
