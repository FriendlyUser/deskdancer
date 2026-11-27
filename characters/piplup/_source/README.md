# How Piplup was made

Piplup is drawn by a script. Its shape started from one picture of Piplup: its
measurements were taken from the picture, and nudged until the standing pose drawn here
lay on top of it. It is painted the way Piplup looks as a soft toy lit in 3D, after
pictures of it drawn that way: there is no line round anything, each part is one smooth
colour that goes darker and cooler where it turns away from the light, a band of pale
light runs along the top of its head, and one part lying over another throws a soft
shadow on it. Nothing is modelled in 3D and no picture is in the pack, so every frame of
every clip is drawn fresh, which is why Piplup can turn round, sit down and lie on its
belly. The app never reads this folder (its name starts with `_`); it is here so the
animations can be changed and rebuilt.

Piplup is a Pokémon and belongs to Nintendo, Creatures and Game Freak, who had no part in
this pack.

| File | What it is |
| --- | --- |
| `make_frames.py` | Draws Piplup, and builds every animation and `character.json`. |

## Rebuilding the animations

```bash
pip install numpy pillow
python3 make_frames.py
```

It takes a few minutes and overwrites the clips and `character.json` in the folder above.
Then right-click the mate and choose **Character > Reload characters**.
`python3 make_frames.py --sheet` also saves `sheet.png` with every frame on one page, and
`python3 make_frames.py dance_bubbles walk` rebuilds only the clips named. Running it twice
gives the same files, byte for byte. To look at a change quickly, `PIPLUP_SS=2 python3
make_frames.py walk` draws rougher edges several times faster; build without it before
keeping the result.

## How it works

**Two balls.** The head and the body are two balls, each fuller below its middle than a true
oval: the head wider than it is tall, the body a little taller than it is wide, with its top
hidden behind the head. Everything painted on them is laid out in degrees
round the ball, as places are on a globe: the white of the face, the pale crown between the
eyes, the eyes, the cape and the two white buttons. The ball is turned before it is drawn,
so when Piplup looks round, nods or spins, what is painted on it slides round and goes out
of sight behind the edge as it should. The face is tipped a little inside the head, as it is
in the picture, and we look down slightly on the chest.

**The face.** The white is three ovals drawn as one shape: one round each eye and one for
the chin. The eyes are tall ovals that stand upright in the tipped face, dark and glossy,
with the light caught softly low down in them, a pupil and a white shine. They blink,
widen, shut in sleep (curving down), smile (an arch, `^ ^`) and screw up (`> <`), and the
pupils can look about. Shut, an eye is a dark line, thickest in the middle and thinner
towards its round ends. The beak is a dome on the front of the head, cut in two by the
mouth; open, the lower half swings down on a hinge and shows the mouth and a tongue.

**The cape.** The dark blue round its shoulders is one line round the body: two scallops on
the chest with a notch between them, up over each shoulder, and well down its back.

**Flippers.** Each hangs from a shoulder high up under the head and turns with the body, so
one that points at us looks shorter. The near one is drawn larger and lit, with its dark
back showing along the top of its outer edge; the far one is smaller and in shade. They are
not posed frame by frame: a clip says where they should be, and a spring carries them
there, pushed about by how the body moves, so they lag behind a hop and flap when it lands.

**Feet.** A foot is a webbed fan, narrow and thick at the ankle, wide and thin at the toes,
with two lines running to the front edge between its three toes. It is worked out as a
solid thing, slice by slice from heel to toe, so it looks right seen from the front, the
side or behind, lifted or with its toes tipped up. The body's shadow lies across the ankle
and down the side away from the light. Above each foot the top of the leg is a round lump
low on the body, and where the nearer one sticks out, the body's own edge runs on a little
way under it as a fold.

**Light.** There are no lines. The light comes from up, to the left and in front. Each
pixel of a ball is lit by which way the ball faces there, worked out from where the pixel
is inside the ball's outline; the flat parts, the beak, the flippers, the tail and the
feet, are rounded off at their edges like cushions and lit the same way. Every colour is a
pair: what it is in full light, and what it goes as it turns away, which is darker and
cooler, so the white of the face goes lavender. Close to the outline it goes darker still,
more so on the side away from the light. Where the top of the head turns up, it catches a
band of pale light with a sharp edge, and the edges of the beak, the flippers and the tail
catch a little of it too. One part lying over another throws a soft shadow on it: the cape on the
body, the head on the cape, the beak on the face, the flippers on the body and the long
leaf of the tail on the short one. The line of the mouth, the fold over the nearer leg and
the lines between the toes are soft shadows too, and each button sits in a fine groove.
Everything is drawn hard-edged at four times the saved size and averaged down, which is
where the smooth edges come from.

**Liberties.** Seen three-quarters on, as it stands, a cartoon cheats: the shoulders and
feet are turned out a little further than they really are, the tail peeps out from behind,
the near flipper is larger than the far one and the eyes sit towards the near side of the
beak. The script takes the same liberties, each one strongest half way between facing us
and side on and gone when Piplup faces us squarely, so that it looks the same from either
side.

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
prints the total when it finishes: about 200 MB for every clip but the action at once, but
standing about, Piplup holds only its idle clip, 31 MB, and each of the others is read when
it is needed and dropped a minute after it was last shown. The action is never unpacked at
all: the app reads its frames from the file as it shows them. A frame is held for as long
as nothing has moved, and each clip is cropped to what it uses. The walk, the dances and the
bow are drawn at 30 frames a second, standing and sitting at 20 and the nap at 12. On disk
the pack is under 10 MB: smooth shading does not pack down as tightly as flat colour does,
but every frame is still saved without loss.

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

Distances are in units: standing, Piplup is about 300 tall, and y = 0 is the floor. `CLIPS`
lists each clip's length, how many frames a second to sample it at, and whether it is a
calm one. A clip that loops must end as it began. To add a dance, write another function
and add a line to `CLIPS`; a key starting with `dance_` appears under **Dance move**, and
one starting with `action_` under **Actions**.

If the walk is changed, keep `STRIDE` and `STEP` in step with each other: a foot on the
floor travels `4 * STRIDE / STEP` units a second, which has to be the 163 or so that the app
moves a walking mate (0.55 of its height).

The sizes of the balls, where everything on them is, the flippers, the feet, the colours
and the light are the constants at the top of the script, each with a note beside it.
`OUT` sets how large the frames are saved.
