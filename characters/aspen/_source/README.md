# How Aspen was made

Aspen is a leaf drawn by a script, an original character made for this project. There is no
picture behind it: every frame of every clip is drawn fresh. The app never reads this folder
(its name starts with `_`); it is here so the animations can be changed and rebuilt.

| File | What it is |
| --- | --- |
| `make_frames.py` | Draws Aspen, and builds every animation and `character.json`. |

## Rebuilding the animations

```bash
pip install numpy pillow
python3 make_frames.py
```

It takes about three minutes and overwrites the clips and `character.json` in the folder
above. Then right-click the mate and choose **Character > Reload characters**.
`python3 make_frames.py --sheet` also saves `sheet.png` with every frame on one page, and
`python3 make_frames.py dance_whirl walk` rebuilds only the clips named. Running it twice
gives the same files.

## How it works

**The blade.** Aspen's body is the blade of a leaf: round at the bottom, widest a third of
the way up, and drawn out to a point, with the little teeth along its edge that an aspen
leaf has. It is not a fixed shape. It is built along its midrib, and the midrib is a line
that can bow over to either side and curl at the tip, with the blade's width set off across
it all the way up. So the leaf bends the way a leaf does, as a whole and without creasing,
and the face, which sits low down where the midrib hardly moves, stays the shape it is.

**Turning.** The blade is a sheet folded back a little along its midrib, and it can be turned
about the midrib in three dimensions. Seen from in front, each half is as wide as the cosine
of how far it is turned away, so as Aspen spins the two halves narrow one after the other,
one of them goes edge on while the other still shows, and then the back comes round: paler,
with no face, and with every vein and the midrib standing out. Each half is lit by how
squarely it faces the light, which comes from the left, so even standing still the left
half is a shade lighter than the right, and that is what shows the fold. The eyes and
cheeks narrow with the half they are on; the arms, the legs and the stalk turn with the
leaf.

**Colour.** The blade is lighter towards its tip and deeper at its edge, with veins and a
shine painted on. A pose can set its season, from 0, green, through yellow-green, gold and
orange to 1, red. A leaf turns from its edge and its tip inwards, and so does this one:
part of the way there, its edge is already orange while there is still green along the
midrib. The arms, legs, stalk and outline turn with it.

**The face, arms, legs and stalk.** The eyes are beads with two shines; they blink, widen,
close, squeeze shut (`> <`), smile (`^ ^`) and swirl. The mouth can smile, open, grin, make a
little "o", a `:3`, a flat line, or a wavy one. The arms are stubby tubes that hang from
behind the blade, the legs are two short stubs, and sitting, two round soles stick out in
front instead. The stalk sticks out behind like a tail, curled up at the end, where a woody
knob shows where it came off its twig. Aspen faces right, so the stalk is on the left.

**Springs and the breeze.** A clip says where the arms, the bow of the blade, the curl of its
tip and the stalk should be, and springs carry them there, pushed about by how Aspen moves.
So the blade is left behind when Aspen sets off, its tip flops when it lands, and the stalk
bobs. On top of that a breeze stirs the blade all the time. It is made of waves that fit a
whole number of times into the clip being drawn, so every clip loops without a jump.

**Things round it.** Wind is drawn as white streaks that end in a curl. There are little
leaves in any season's colour, drops of water, four-pointed sparkles, and a ladybird that
can walk on the blade or fly.

## The clips

| Clip | When the app shows it |
| --- | --- |
| `idle.webp` | Standing, stirring in the breeze. Blinks, glances to one side, and is caught by a gust that bows it right over, which it rather enjoys. |
| `walk.webp` | Wandering: a waddle from foot to foot on its stubby legs, arms swinging, the blade bowing back and the stalk bobbing behind. |
| `sit.webp` | Sitting with its feet out in front. A ladybird climbs up the edge of the leaf while Aspen watches it, opens its wings and flies off, and Aspen waggles its feet. |
| `sleep.webp` | Dozing where it sits, eyes shut, its tip drooped right over, with a drop of dew swelling on the end of it until it falls. The app adds the breathing and the Zs. |
| `dance.webp` | During all 15 built-in dance moves, which add their own body motion: both arms up and waving, a big grin, the blade swishing from side to side, and a little leaf flicked off its tip on every beat. Also listed as **Rustle**. |
| `dance_whirl.webp` | **Whirl**, eight beats: the wind gets up and Aspen crouches, then lets it take it. Up it goes, spinning round twice like a leaf off a tree and showing its pale back, and then it drifts down the way leaves do, swinging from side to side, to land with a bounce. |
| `dance_autumn.webp` | **Autumn**, eight beats: a cold gust makes Aspen shiver, and it turns, gold creeping in from its edge and its tip, then orange, then red, while it watches itself go. It shows off its colours with two hops in a shower of falling leaves, then shakes itself and is green again, the red flying off it in a ring of little leaves. |
| `dance_raindrops.webp` | **Raindrops**, eight beats: three drops land on the tip of the leaf, one on each beat, each bobbing it, and then a great big one that sits there and bows the whole blade over. Aspen wobbles under it, takes aim, and flicks it off into the air, where it bursts. |
| `drag.webp` | Being carried: eyes wide, a little "o", arms flailing, legs pedalling, the blade flapping. |
| `fall.webp` | Dropping through the air, arms up, the tip and the stalk streaming up behind and fluttering. |

Clip dances get no motion from the app, so the hops, the spin and the drifting down are
drawn in. At the usual 120 BPM each of the three dances lasts four seconds.

The app keeps every frame of a clip it is showing unpacked in memory, and as the breeze never
lets the blade keep quite still, every frame of Aspen's is a frame of its own.
`make_frames.py` prints the total when it finishes: about 254 MB for every clip at
once, though the app only unpacks a clip when it is wanted and lets go of it again
afterwards, so standing about Aspen holds only its idle clip, 20 MB, and the
largest dance is 71 MB while it plays. The clips run at 10 frames a second when
Aspen is standing, sitting or napping, and at 20 when it is moving, and each is cropped to
what it uses. On disk the pack is about 4 MB.

## Changing things

Each clip is a short function near the end of `make_frames.py` (`idle`, `walk`, `sitting`,
`asleep`, `rustle`, `whirl`, `autumn`, `raindrops`, `carried`, `falling`). It is given the
time in seconds and returns a pose. A pose can set:

- `eyes`: a pair, each `"open"`, `"wide"`, `"happy"`, `"closed"`, `"squint"`, `"dizzy"`, or a
  number from 0 to 1 for how far shut; `look`: how far the face moves right and down
- `mouth`: `"smile"`, `"open"`, `"grin"`, `"o"`, `"cat"`, `"flat"` or `"wobble"`
- `arms`: degrees each arm is lifted from hanging straight down (90 is straight out to the
  side), and `elbow`, how far each is bent; the spring adds its own swing
- `legs`: for each leg, degrees swung outwards and how far it is lifted; `seated`: `True` to
  sit it down
- `bend`: degrees the blade bows over to the right by the time it reaches its tip (negative
  is to the left); `curl`: degrees the tip curls over on top of that, 22 at rest and about
  100 asleep; `tail`: degrees the stalk droops, or below zero, perks up. Springs add to all
  three.
- `turn`: degrees the leaf is turned about its midrib. 90 is edge on, 180 shows its back.
- `season`: 0 for green to 1 for red
- `breeze`: how much the breeze stirs the blade, 1 as usual
- `fx`: wind `("gust", x, y, length, way, opacity)`, where `way` is 1 for blowing right and -1
  for left; little leaves `("leaflet", x, y, length, angle, season, opacity)`; drops of water
  `("drop", x, y, radius, how drawn out)`, `("drop-on", how far up the midrib, radius)` for
  one sitting on the blade and `("drop-tip", radius)` for one hanging off its tip; sparkles
  `("spark", x, y, size, angle)`; and the ladybird, `("ladybird-on", how far out from the
  midrib, how far up it, heading, size)` on the blade or
  `("ladybird", x, y, heading, size, wings)` in the air. `gusts()`, `burst()` and `shed()`
  make the usual ones.
- `squash` (positive is shorter and wider), `lean` (degrees, positive tips right), and `dx`,
  `dy` for the whole mate (negative `dy` is up)

Distances are in units: standing, Aspen is about 280 tall. `CLIPS` lists each clip's length
and how many frames a second to draw it at, which has to divide 500, the rate clips are
sampled at, so that a loop is exactly as long as it should be. The clip must end as it
began, because it loops. To add a dance, write another function and add a line to `CLIPS`;
any key starting with `dance_` appears under **Dance move**.

The size and shape of the blade, the face and the colours are the constants at the top:
`BLADE`, `HALF`, `FOLD`, `TIP`, `TOOTH`, `FACE`, `EYES`, `MOUTH`, `CHEEKS`, `TAIL`, `SEASONS`,
`INK` and the rest, and `profile()` is the outline of the blade. `OUT` sets how large the
frames are saved.
