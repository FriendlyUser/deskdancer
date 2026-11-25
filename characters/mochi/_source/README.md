# How Mochi was made

Mochi started as one photo. The app never reads this folder (its name starts with `_`);
it is here so the animations can be changed and rebuilt.

| File | What it is |
| --- | --- |
| `cutout.png` | The character cut out of the photo, on a transparent background. |
| `cut_out.py` | How `cutout.png` was made: a background-removal model (BiRefNet). |
| `make_frames.py` | Builds every animation and `character.json` from `cutout.png`. |

## Rebuilding

```bash
pip install numpy pillow opencv-python-headless
python3 make_frames.py
```

It takes a few minutes and overwrites the clips and `character.json` in the folder
above. Then right-click the mate and choose **Character > Reload characters**.
`python3 make_frames.py --sheet` also saves `sheet.png` with every frame on one page.

## How it works

`make_frames.py` splits the picture into the head and body plus one layer per ear. The
ears turn about their roots behind the head, so they can twitch, flap and droop without
leaving a gap. The face is repainted for blinks, closed eyes, happy `^ ^` eyes, wide
eyes and an open mouth. Every clip is drawn on the same canvas with the feet in the same
place, and `character.json` pins that point (`anchor`) so nothing jumps between clips.

| Clip | When the app shows it |
| --- | --- |
| `idle.webp` | Standing, and while walking (the app adds the waddle). Blinks and ear twitches. |
| `dance.webp` | During all 15 built-in dance moves, which add their own body motion. Also listed as **Happy Ears**. |
| `dance_bunny_hop.webp`, `dance_ear_wave.webp` | Their own entries under **Dance move**. Clip dances get no motion from the app, so the hops and sways are drawn in. |
| `drag.webp` | Being carried, and falling. |
| `sleep.png` | Napping. The app adds breathing and the Zs. |

Sitting has no clip of its own; the app squashes the idle picture, which suits Mochi.

## Changing things

Each clip is a short function near the end of `make_frames.py` (`idle`, `happy_ears`,
`bunny_hop`, `ear_wave`, `dangle`, `sleep`) that returns a list of `(pose, milliseconds)`.
A pose can set:

- `eyes`: a pair, each `"open"`, `"closed"`, `"happy"`, `"wide"`, or a number from 0 to
  1 for an eyelid part way down
- `mouth`: `None` (as in the photo), `"smile"` or `"o"`
- `ears`: degrees each ear tip is lifted (negative droops it)
- `squash` (positive is shorter and wider), `lean` (degrees, positive tips right),
  `dx`, `dy` (pixels of the original photo; negative `dy` is up)

To add a dance, write another function and add a line to `CLIPS`; any key starting with
`dance_` appears under **Dance move**.
