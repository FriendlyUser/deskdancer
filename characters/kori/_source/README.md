# How Kori was made

Kori is an ice cube drawn by a script, an original character made for this project. There
is no picture behind it: every frame of every clip is drawn fresh, which is why it can turn
round, melt into a puddle and freeze back up. The app never reads this folder (its name
starts with `_`); it is here so the animations can be changed and rebuilt.

| File | What it is |
| --- | --- |
| `make_frames.py` | Draws Kori, and builds every animation and `character.json`. |

## Rebuilding the animations

```bash
pip install numpy pillow
python3 make_frames.py
```

It takes about a minute and overwrites the clips and `character.json` in the folder above.
Then right-click the mate and choose **Character > Reload characters**.
`python3 make_frames.py --sheet` also saves `sheet.png` with every frame on one page, and
`python3 make_frames.py dance_meltdown walk` rebuilds only the clips named. Running it
twice gives the same files, byte for byte.

## How it works

**The cube.** Kori is a real box in three dimensions: its eight corners are turned about its
upright axis and looked at from a little above, with no perspective, so its top shows as
well as its front and, standing still, a little of one side. Each face that shows is filled
with a gradient whose brightness depends on which way the face points, so when the cube
turns round the light moves across it. The outline round the whole cube is rounded off at
the corners, the edges where two faces meet are drawn as lines of white light, and a faint
frosted rim runs just inside the outline. Everything is drawn hard-edged at four times the
saved size and averaged down, which is where the smooth edges come from.

**The ice.** Inside the front are two slanting glints, a hairline crack and a few trapped air
bubbles, all clipped to the front so they turn with it. Now and then a broader glint sweeps
right across it, and drops of meltwater swell at a bottom corner, let go and fall.

**The face.** The eyes and mouth are drawn on the front of the cube, so they turn and
foreshorten with it, and go away round the back when it spins. The eyes are beads with
two shines; they blink, widen, close, squeeze shut (`> <`), smile (`^ ^`) and swirl when it
is dizzy. The mouth can smile, open, grin, make a little "o", a `:3`, a flat line, or a
zigzag for chattering teeth. Pink cheeks sit either side.

**Arms and legs.** The arms are stubby tubes with round hands that come out of the middle of
each side. Each arm sticks out from its own side of the cube in three dimensions, so as that
side turns towards us the arm points at us and looks shorter. An arm is drawn in front when
its side faces partly towards us and behind when it faces away; one on a side turned right
round to us, which would lie across the cube like a sticker, goes behind for that moment.
Like Domo's, the arms are not posed frame by frame: a clip says where they should be, and a
spring carries them there, pushed about by how the cube moves. The legs are two short
stubs under the front half of the cube, which swing and lift to walk. Sitting, two round
soles stick out in front instead.

**Melting.** Every point of the cube goes through a warp before it is drawn: as it melts, the
cube sinks towards the floor, spreads out more the lower down a point is, and its sides
bulge, while its corners round off further and a puddle spreads underneath. The face
shrinks only a little and stays on the body, and the arms melt in once it is half way.

**Lights and flakes.** Sparkles are four-pointed stars edged in blue, so they show on a light
desktop as well as a dark one. Snowflakes are six-armed, and a sneeze blows out a little
cloud of frost.

## The clips

| Clip | When the app shows it |
| --- | --- |
| `idle.webp` | Standing. Blinks, a glint sweeps across its front, it glances to one side, a drop of meltwater swells and falls, and now and then it shivers, teeth chattering. |
| `walk.webp` | Wandering: a waddle from foot to foot on its stubby legs, arms swinging. |
| `sit.webp` | Sitting on a little puddle with its feet out in front. Blinks, waggles its feet, and lets a drip fall now and then. |
| `sleep.webp` | Dozing where it sits, eyes shut, slowly melting a little into its puddle. The app adds the breathing and the Zs. |
| `dance.webp` | During all 15 built-in dance moves, which add their own body motion: both arms up and waving, a big grin, a glint on the beat and a sparkle off a corner. Also listed as **Cool Moves**. |
| `dance_ice_skate.webp` | **Ice Skate**, four beats: it glides off one way on one foot with its arms out like wings, glides back the other way, then spins right round on the spot in a flurry of sparkles and lands with its arms up. |
| `dance_meltdown.webp` | **Meltdown**, four beats: it starts to sweat and drip, sinks down into a puddle grinning dizzily, then freezes back into a cube all at once with a burst of sparkles and a bounce. |
| `dance_brr.webp` | **Brr!**, two beats: a shiver from top to toe, teeth chattering, then a big breath in and a sneeze that blows out a puff of frost and a flurry of snowflakes. |
| `drag.webp` | Being carried: eyes wide, a little "o", arms flailing, legs pedalling, a nervous drip. |
| `fall.webp` | Dropping through the air, arms up. |

Clip dances get no motion from the app, so the glides, hops and bounces are drawn in. At the
usual 120 BPM, Ice Skate and Meltdown loop in two seconds and Brr! in one.

The app keeps every frame of a clip it is showing unpacked in memory. `make_frames.py`
prints the total when it finishes (about 130 MB for every clip at once; standing about, Kori
holds only its idle clip, 26 MB). A frame is held for as long as nothing has visibly moved,
and each clip is cropped to what it uses. On disk the pack is under 3 MB.

## Changing things

Each clip is a short function near the end of `make_frames.py` (`idle`, `walk`, `sitting`,
`asleep`, `cool_moves`, `ice_skate`, `meltdown`, `brr`, `carried`, `falling`). It is given the
time in seconds and returns a pose. A pose can set:

- `eyes`: a pair, each `"open"`, `"wide"`, `"happy"`, `"closed"`, `"squint"`, `"dizzy"`, or a
  number from 0 to 1 for how far shut; `look`: how far the face moves right and down
- `mouth`: `"smile"`, `"open"`, `"grin"`, `"o"`, `"cat"`, `"flat"` or `"chatter"`
- `arms`: degrees each arm is lifted from hanging straight down (90 is straight out to the
  side). The spring adds its own swing.
- `legs`: for each leg, degrees swung outwards and how far it is lifted
- `seated`: `True` to sit it down
- `yaw`: degrees it has turned round, on top of the little turn it always has
- `melt`: 0 is a cube, 1 a puddle with a face; `puddle`: how big the puddle under it is
- `shine`: where the sweeping glint has got to, from 0 to 1 (off below -0.9)
- `drips`: drops of meltwater, each (which bottom corner, -1 or 1, how far through its fall
  from 0 to 1)
- `fx`: sparkles `("spark", x, y, size, angle)`, snowflakes `("flake", x, y, size, angle)` and
  puffs of frost `("puff", x, y, radius, opacity)`, in units
- `squash` (positive is shorter and wider), `lean` (degrees, positive tips right), and `dx`,
  `dy` for the whole mate (negative `dy` is up)

Distances are in units: standing, Kori is about 280 tall. `CLIPS` lists each clip's length,
how many frames a second to sample it at, and whether it is a calm one. The clip must end
as it began, because it loops. To add a dance, write another function and add a line to
`CLIPS`; any key starting with `dance_` appears under **Dance move**.

The size of the cube, the camera, the face and the colours are the constants at the top:
`S`, `HH`, `LEGS`, `PITCH`, `YAW`, `ROUND`, `EYES`, `MOUTH`, `CHEEKS`, `ICE_LIT`, `ICE_DARK`,
`INK` and the rest. `OUT` sets how large the frames are saved.
