# How Domo was made

Domo is drawn by a script. There is no picture behind him: every frame of every clip is
drawn fresh from a short list of shapes, which is why any part of him can move. The app
never reads this folder (its name starts with `_`); it is here so the animations can be
changed and rebuilt.

| File | What it is |
| --- | --- |
| `make_frames.py` | Draws Domo, and builds every animation and `character.json`. |

Domo is the mascot of NHK, Japan's public broadcaster, and belongs to them. This pack is
a fan drawing made for this project; NHK had no part in it.

## Rebuilding the animations

```bash
pip install numpy pillow
python3 make_frames.py
```

It takes about twenty seconds and overwrites the clips and `character.json` in the folder
above. Then right-click the mate and choose **Character > Reload characters**.
`python3 make_frames.py --sheet` also saves `sheet.png` with every frame on one page.
Running it twice gives the same files, byte for byte.

## How it works

**The drawing.** Domo is a body, two arms, two legs, two eyes and a mouth, each a shape
listed near the top of `make_frames.py`. A part is filled dark and then filled again in
its own colour a little way in, which leaves an even dark edge all the way round it. The
arms and the standing legs are drawn first and the body over them, so they come out from
behind it. Everything is drawn hard-edged at four times the saved size and averaged down,
which is where the smooth edges come from.

**Standing and sitting.** Standing, the legs are two stubs that swing from the hip and
tuck up behind the body when lifted. Sitting, he comes down onto the floor with his legs
stuck out towards you, so what shows is the sole of each foot, and his hands rest beside
them.

**The face.** The eyes are beads with a shine along the top. A blink flattens them;
asleep and happy they are a curved line. The mouth is set by one number, how far open it
is. The teeth grow from the lips and stop short of the middle, so when the mouth shuts
the two rows meet point to point and still show.

**The arms.** Each arm is a tube that can lift and curl, with a round hand. A clip does
not pose the arms frame by frame. It says where they should be, and a spring carries them
there, pushed about by how the shoulders are moving. That is why they lag behind a stomp
and flop when he lands. They are drawn behind the body, so an arm lifted past about 135
degrees starts to disappear behind his head. A pose can bring an arm round in front of
the body instead, and can tell the spring to leave it alone, which is how he holds
something still.

**The cup and the cloud.** Two more things can be in a pose. A cup of bubble tea has a
lid, a straw, tea that goes down as he drinks and pearls in the bottom that go up the
straw one at a time. A cloud of gas is a handful of puffs that start small behind him,
drift off, grow and fade.

**Painters.** The script keeps what a pose is apart from how it is painted. It works out
where every shape goes and hands them, from the back to the front, to a painter. The one
here, `Flat`, fills each shape with one colour and gives it a dark edge. The Plush Domo
pack ([characters/domo-plush](../../domo-plush/_source/README.md)) loads this script and
swaps in a painter of its own, so the two characters share one set of shapes and clips.
A change to a clip here changes both, once each pack has been rebuilt.

## The clips

| Clip | When the app shows it |
| --- | --- |
| `idle.webp` | Standing. Blinks, glances to one side, snaps his teeth together twice, and waves if he is left standing long enough. |
| `walk.webp` | Wandering: a toddle from foot to foot, arms swinging. |
| `sit.webp` | Sitting. Blinks, and waggles his feet now and then. |
| `sleep.webp` | Napping where he sits, mouth opening a little with each breath. The app adds the breathing and the Zs. |
| `dance.webp` | During all 15 built-in dance moves, which add their own body motion. Also listed as **Happy Arms**. |
| `dance_chomp.webp`, `dance_stomp.webp` | Their own entries under **Dance move**, **Chomp** and **Monster Stomp**. Clip dances get no motion from the app, so the hops and stomps are drawn in. Each loops in one second, which is two beats at the usual 120 BPM. |
| `action_bubble_tea.webp` | **Bubble Tea** under **Actions**. He brings out a cup and gives it a shake, takes three long pulls at the straw, lowers it with a happy sigh and sways, then goes back for four more until the tea is all but gone. He peers in at the one pearl left at the bottom, shakes the cup, gives up with a glum sigh and puts it away. 8.6 seconds. |
| `action_fart.webp` | **Fart** under **Actions**. He glances one way and the other, strains, and nothing comes. He looks round behind him, puzzled, tries again harder and lets one go with a hop, looks relieved, wafts the cloud away for a good while, and then looks off into the distance as if nothing had happened. 7.3 seconds. |
| `drag.webp` | Being carried. |
| `fall.webp` | Dropping through the air. |

Bubble Tea and Fart are actions, not dances. The app plays an action once through at its
own speed, with no music notes and no dance floor, and then he goes back to standing
about. Pick one under **Actions** in the right-click menu (on Android, its button under
**Dance** in the settings); now and then he also does one by himself. They are never
part of a dance, a double-click's dance or the dance party. Because an action is not
looped, each starts and ends standing at rest, and `make_frames.py` keeps its last frame
where it is instead of joining it on to the first, as it does for a loop. The app plays
a clip whose key starts with `action` once unless `character.json` says otherwise.

Frames are not free. The app keeps the idle clip unpacked in memory the whole time, and
each other clip while it is being shown and for a minute afterwards. `make_frames.py`
prints the total for every clip when it finishes (about 198 MB, of which idle is 28,
Bubble Tea 46 and Fart 56; only one action is shown at a time). Three things keep it down:
each clip is cropped to what it uses; a frame is held for as long as nothing has visibly
moved, so standing still costs one frame, not hundreds; and the two long actions are drawn
at fewer frames a second than the dances. On disk the pack is about 1.5 MB, because flat
colour packs down well without any loss.

## Changing things

Each clip is a short function near the end of `make_frames.py` (`idle`, `walk`,
`sitting`, `asleep`, `happy_arms`, `chomp`, `stomp`, `bubble_tea`, `fart`, `carried`,
`falling`). It is given the time in seconds and returns a pose. A pose can set:

- `eyes`: a pair, each `"open"`, `"wide"`, `"happy"`, `"closed"`, or a number from 0 to 1
  for how far shut
- `look`: how far the face is moved right and down, for a glance
- `mouth`: 0 is teeth together, 1 is how he usually has it, and up to about 1.35 is a roar
- `arms`: degrees each arm is lifted from hanging straight down (90 is straight out to
  the side), and `bend`: degrees it curls along its length (positive curls the hand
  upwards). The spring adds its own swing to both.
- `legs`: for each leg, degrees swung outwards and how far it is lifted. Sitting, the
  first number tips the foot up instead.
- `seated`: `True` to sit him down
- `front`: for each arm, `True` to draw it in front of the body, and `loose`: for each
  arm, how much of the spring's swing it is allowed, from 1, all of it, down to 0, held
  exactly where the pose puts it
- `cup`: a cup of bubble tea, as where the middle of its base is (x, y), how far it is
  tipped, its size from 0 to 1, how full it is from 1 to 0, and how many pearls have gone
  up the straw (1.5 is one swallowed and another half way up)
- `gas`: a cloud of gas, by its age: 0 just let off, 1 gone
- `squash` (positive is shorter and wider), `lean` (degrees, positive tips right), and
  `dx`, `dy` for the whole mate (negative `dy` is up)

Distances are in units: standing, he is 300 tall. `CLIPS` lists each clip's length, how
many frames a second to sample it at, and whether it is a calm one. A clip must end as it
began: a dance because it loops, an action because he goes into it and comes out of it
standing. To add a dance, write another function and add a line to `CLIPS`; any key
starting with `dance_` appears under **Dance move**, and any starting with `action_`
under **Actions**.

Two helpers save working out angles by hand. `reach(side, x, y)` gives the lift and bend
that put a hand at a place, and `hand_at(side, lift, bend)` says where a hand is, which
is how the cup is kept in his grip.

The arms' springiness is set by `ARM_HZ`, `ARM_DAMPING`, `ARM_PUSH` and `ARM_CURL`, just
above the clips. His proportions and colours are the constants at the top: `BODY`,
`SHOULDER`, `LEG`, `EYES`, `MOUTH`, `FUR` and the rest, with the cup's and the cloud's
after them. `OUT` sets how large the frames are saved.
