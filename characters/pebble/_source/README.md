# How Pebble is made

Pebble is a baby penguin, an original character of DeskDancer's own, and it is drawn by a
script: a soft cartoon with thick dark lines, flat colours and one hard-edged shadow on
each part. No picture is read, so every frame of every clip is drawn fresh, which is why
Pebble can turn round, sit down and lie on its belly. The app never reads this folder (its
name starts with `_`); it is here so the animations can be changed and rebuilt.

| File | What it is |
| --- | --- |
| `make_frames.py` | Draws Pebble, and builds every animation and `character.json`. |

## Rebuilding the animations

```bash
pip install numpy pillow
python3 make_frames.py
```

It takes a few minutes and overwrites the clips and `character.json` in the folder above.
Then right-click the mate and choose **Character > Reload characters**.
`python3 make_frames.py --sheet` also saves `sheet.png` with every frame on one page, and
`python3 make_frames.py dance_bubbles walk` rebuilds only the clips named. Running it twice
gives the same files, byte for byte. To look at a change quickly, `PEBBLE_SS=2 python3
make_frames.py walk` draws rougher edges several times faster; build without it before
keeping the result.

## How it works

**Two balls.** A chick is mostly head: the head is a wide round ball, and the body under
it a plump one whose top is hidden behind the head. Everything painted on them is laid out
in degrees round the ball, as places are on a globe: the cream face, the pink cheeks, the
eyes, the tummy and the scarf. The ball is turned before it is drawn, so when Pebble looks
round, nods or spins, what is painted on it slides round and goes out of sight behind the
edge as it should. The face is wide, so it is painted in narrow upright strips: a patch
that is partly round the back is cut off at the ball's edge, which only works for a
narrow one.

**The face.** A dark slate cap comes down to a cream face whose top edge dips a little
between the eyes. The eyes are big, dark and glossy, with a warmer crescent along the
bottom, a large shine and a small one. They blink, widen, shut in sleep (curving down),
smile (`^ ^`) and screw up (`> <`), and the pupils can look about. Below them are two pink
cheeks, soft and without a line. The beak is a small peach dome cut in two by the mouth;
open, the lower half swings down on a hinge and shows the mouth and a tongue. On top of the
head is a tuft of down: three wisps that stand up from the crown and curl over.

**The scarf.** A coral knitted scarf goes round the neck, a little lower in front than at
the back, with a pale stripe round it. One end hangs down the chest on the near side, with
a fringe.

**Flippers.** Short and slate, each hangs from a shoulder under the scarf and turns with
the body, so one that points at us looks shorter. They are not posed frame by frame: a clip
says where they should be, and a spring carries them there, pushed about by how the body
moves, so they lag behind a hop and flap when it lands.

**Feet.** A foot is a stubby webbed fan, worked out as a solid thing, slice by slice from
heel to toe, so it looks right seen from the front, the side or behind, lifted or with its
toes tipped up. Above each foot the top of the leg is a round lump low on the body.

**Lines and light.** Every part has a line round it in a soft dark plum rather than black.
The light comes from up and to the left: each part is one flat colour with one darker
shape for its shadow, and a paler one where the light catches it. Everything is drawn
hard-edged at four times the saved size and averaged down, which is where the smooth edges
come from.

## The clips

| Clip | When the app shows it |
| --- | --- |
| `idle.webp` | Standing, as in the picture. Blinks, glances round at us (its eyes go first and its head follows), shakes a flipper, wags its tail, and now and then puffs out its chest, beak in the air. |
| `walk.webp` | Wandering: a waddle. Its weight rolls over the foot on the floor while the other swings past, heel up first and toes last. A foot on the floor goes back exactly as fast as the app moves the mate forward, so it does not slide. |
| `sit.webp` | Sitting with its feet out in front. Blinks, looks about and waggles its toes. |
| `sleep.webp` | Dozing where it sits, head nodding, with a bubble at its beak that swells as it breathes out. The app adds the breathing and the Zs. |
| `dance.webp` | During all 15 built-in dance moves, which add their own body motion: eyes shut in a smile, beak open in song, flippers flapping to the beat, feet tapping. Also listed as **Happy Flap**. |
| `dance_bubbles.webp` | **Bubbles**, four beats: a deep breath, chest out; a stream of bubbles from its beak that drift up and away; then they burst one after another and it hops for joy. |
| `dance_pirouette.webp` | **Pirouette**, four beats: it winds up, spins twice round on one foot with its flippers flung out, and lands with them in the air in a shower of sparkles. |
| `dance_belly_slide.webp` | **Belly Slide**, four beats: a little jump, down on its belly, and it slides one way and back with its feet kicking in the air, then pushes itself upright. |
| `action_take_a_bow.webp` | **Take a Bow**, an action, played once through in four seconds: it puffs out its chest, sweeps a flipper across itself and bows low, and straightens up with a hop. |
| `drag.webp` | Being carried: eyes wide, beak open, flippers beating, feet pedalling, a nervous drop of sweat. |
| `fall.webp` | Dropping through the air: flippers up, eyes screwed shut, feet trailing. |

Clip dances get no motion from the app, so the hops, spins and slides are drawn in. At the
usual 120 BPM the three dances loop in two seconds and Happy Flap in one.

The app keeps every frame of a clip it is showing unpacked in memory. `make_frames.py`
prints the total when it finishes: about 290 MB for every clip but the action at once, but
standing about, Pebble holds only its idle clip, about 50 MB, and each of the others is read
when it is needed and dropped a minute after it was last shown. The action is never
unpacked at all: the app reads its frames from the file as it shows them. A frame is held
for as long as nothing has moved, and each clip is cropped to what it uses. The frames are
drawn about 430 pixels tall, so Pebble stays sharp up to 300% on the Settings window's size
list. The walk, the dances and the bow are drawn at 30 frames a second, standing and
sitting at 20 and the nap at 12. On disk the pack is about 5.5 MB.

## Changing things

Each clip is a short function near the end of `make_frames.py` (`idle`, `walk`, `sitting`,
`asleep`, `happy_flap`, `bubbles`, `pirouette`, `belly_slide`, `take_a_bow`, `carried`,
`falling`). It is given the time in seconds and returns a pose. A pose can set:

- `eyes`: a pair, each `"open"`, `"wide"`, `"happy"`, `"closed"`, `"squint"`, or a number
  from 0 to 1 for how far shut; `look`: degrees the pupils are turned right and down
- `beak`: 0 is shut, 1 wide open
- `turn`, `nod`, `tilt`: degrees the head is turned to the right, nodded down and tipped
  over; `bob`: how far it is moved, in units
- `yaw`: degrees the whole of it is turned round (360 is once round); `twist`: the body
  turned without the head; `sway`: the body rolled to one side; `puff`: chest out, 0 to 1
- `flippers`: degrees each is lifted from hanging straight down, its right one (the nearer,
  as it stands) and then its left (90 is straight out to the side; `flap(n)` is `n` more
  than they hang at rest). The spring adds its own swing. `sweep`: degrees each is swung
  forwards
- `feet`: for each foot, right and then left, how far it is moved along the floor, how high
  it is lifted, how much further it is turned out, and how far its toes are tipped up
- `hips`: the body moved over its feet, right and down, in units, while the feet stay
  where they are put; `seated`: 1 to sit it down
- `tail`: degrees it is wagged
- `fx`: bubbles `("bubble", x, y, radius, how solid)`, a bubble bursting `("pop", x, y,
  radius, how far its bits have flown)`, sparkles `("spark", x, y, size, angle)`, a drop
  `("drop", x, y, size, angle)` and lines of speed `("dash", x, y, width, length)`, in units
- `squash` (positive is shorter and wider), `lean` (degrees, positive tips right), and `dx`,
  `dy` for the whole mate (negative `dy` is up)

Distances are in units: standing, Pebble is about 320 tall, and y = 0 is the floor. `CLIPS`
lists each clip's length, how many frames a second to sample it at, and whether it is a
calm one. A clip that loops must end as it began. To add a dance, write another function
and add a line to `CLIPS`; a key starting with `dance_` appears under **Dance move**, and
one starting with `action_` under **Actions**.

If the walk is changed, keep `STRIDE` and `STEP` in step with each other: a foot on the
floor travels `4 * STRIDE / STEP` units a second, which has to be the 176 or so that the app
moves a walking mate (0.55 of its height).

The sizes of the balls, where everything on them is, the flippers, the feet and the colours
are the constants at the top of the script, each with a note beside it. `OUT` sets how
large the frames are saved.
