# How Sprig was made

Sprig started as one drawing, commissioned and paid for by the owner of this project, who
holds the rights to it. The app never reads this folder (its name starts with `_`); it is
here so the animations can be changed and rebuilt.

Sprig is fan art of a Nintendo character. Nintendo had no part in this pack.

| File | What it is |
| --- | --- |
| `original.png` | The drawing as received (429 x 541). |
| `upscale.py` | Enlarges it 4x with Real-ESRGAN's anime model, which sharpens the line art. Runs without PyTorch. |
| `cut_out.py` | Takes him off the white background and saves `cutout.png`. |
| `cutout.png` | The result, at twice the original size, on a transparent background. |
| `make_frames.py` | Builds every animation and `character.json` from `cutout.png`. |

## Rebuilding

To change the animations, only the last step is needed:

```bash
pip install numpy pillow opencv-python-headless
python3 make_frames.py
```

It takes a minute or two and overwrites the clips and `character.json` in the folder
above. Then right-click the mate and choose **Character > Reload characters**.
`python3 make_frames.py --sheet` also saves `sheet.png` with every frame on one page, and
`python3 make_frames.py idle dance_spin_attack` rebuilds only the clips named.

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
desktop. The blade is nearly white as well, but it is outlined all the way round, so the
fill never gets into it. The right boot was cropped off at the bottom of the original, so
the end of its sole is drawn back in.

**Face.** The eyes and mouth are painted out with skin that blends in from all round their
edges, then redrawn: blinks squeeze the drawn eye shut, closed and smiling (`^ ^`) eyes are
drawn as tapered lash strokes, and narrowed eyes bring the upper lid down across the iris
under a pair of frowning brows. The open mouth as drawn can stretch into a shout or purse
into a little "o", and there are a closed smile and a firm line. Seen from behind, partway
through a spin, the face is painted over in the colours of his hair with a few strands
drawn through it.

**Sword arm.** The forearm, hand and sword are cut out in one piece and turn at the elbow,
so the sword can be raised overhead, held out level or planted in the ground. The cut
follows the arm's outline and takes the ink just outside it too, so no sliver of outline is
left behind. What the arm covered is painted in: the cap and its long tail carry on in
their own greens, the shield on his back in its brown, and the outlines that ran under the
arm (the cap's edge, the bottom of its tail, the shield's edge, the tip of his ear) are
drawn back in. Where the arm meets his shoulder, a disc of bracer sits under it and the
sleeve lies over it, so the elbow never comes apart.

**Cap.** The long tail of the cap is bent by a smooth warp that does nothing where it leaves
his head and grows towards the tip. It hangs on a damped spring, so when he leans, hops or
spins the tail is left behind, swings back and settles. Every clip is run through the
spring a few times before it is recorded, so the loops are seamless.

**Legs.** Each leg is its own layer, cut along the tunic's hem (found column by column as the
first row of stocking under it) and drawn behind the tunic, with a plain stretch of
stocking carrying on up out of sight. So the legs can swing to walk and kick, and tuck up
under the tunic when he bends his knees, which is how he kneels.

**Waist.** Swaying bends him at the waist: his head and shoulders turn as one piece, his hips
stay put, and the body bends smoothly in between. The sword arm goes round with his
shoulders.

**Spin Attack.** The turn is a real one about his upright axis, seen from a little above.
The body and the sword arm are drawn separately and turned apart: the body is never seen
quite edge on (his head is round), while the sword swings fully round from his shoulder,
in front of him on the near side and behind him on the far side. Each frame is the average
of many moments of the turn, like a camera shutter, so the faster he spins the more he
blurs. The ring of light is the ellipse the point of the blade sweeps out: a white-hot
rim edged in deep blue, a paler band inside it with a couple of streaks of speed, brightest
where the blade is and fading behind it. The far side of the ring is drawn behind him. The
blade's glow is a pale halo inside a wider blue one, so it shows on a light desktop as well
as a dark one.

Every clip is drawn on the same canvas with the feet in the same place, then trimmed to
the part it uses, which keeps the pack quick to load. `character.json` records where the
feet are in each clip (`anchor`), so nothing jumps between clips.

| Clip | When the app shows it |
| --- | --- |
| `idle.webp` | Standing (the app adds the breathing). Blinks, a breeze through the tail of his cap, a tilt of the head, and now and then a flourish: the sword dips and comes up high with a glint. |
| `walk.webp` | Wandering along the floor: one stride, with his legs stepping, a small bob, the sword riding along and the cap bouncing. The app adds no motion of its own to a walk clip. |
| `sit.webp` | Kneeling, with the point of his sword stuck in the ground beside him. Blinks, and a contented moment. |
| `dance.webp` | During all 15 built-in dance moves, which add their own bounces, leans and spins, and which is when the app sends up its music notes. The sword punches up on each beat and comes back down between them; he cheers on one beat and grins on the next, sways at the waist, and his cap bounces. Also listed as **Sword Pump**. |
| `dance_spin_attack.webp` | **Spin Attack**, his special move, under **Dance move**. Four beats at the default 120 BPM. He drops into a crouch with the sword low at his side and it charges, glowing brighter and pulsing while sparks gather on it and he trembles with the effort. Then he spins round twice with the sword held out level and a shout, leaving a ring of light, and comes out of it facing us with the sword held high in a shower of sparks. Clip dances get no motion from the app, so the crouch and the hop are drawn in. |
| `drag.webp` | Being carried, and falling: wide eyes, a little "o", legs kicking, the sword waving and the cap fluttering. |
| `sleep.png` | Napping on his heels, leaning on his planted sword, head lolling. The app adds the breathing and the Zs. |

## Changing things

Each clip is a short function near the end of `make_frames.py` (`idle`, `walk`, `sit`,
`sword_pump`, `spin_attack`, `dangle`, `sleep`) that returns a list of `(pose, milliseconds)`.
A pose can set:

- `eyes`: a pair, each `"open"`, `"closed"`, `"happy"`, `"wide"`, `"narrow"`, or a number
  from 0 to 1 for an eye part way shut; `frown`: `True` for slanting brows
- `mouth`: `"open"` (as drawn), `"shout"`, `"smile"`, `"firm"` or `"o"`
- `arm`: degrees the sword arm turns at the elbow; positive lowers the sword on our right,
  about 60 holds it out level and about 145 points it at the ground, negative raises it
  overhead. `planted`: `True` to hide whatever of the sword goes below the floor.
- `glow`: how brightly the blade shines, 0 (not at all) to 1.5
- `cap`: how far the tip of the cap's tail moves, `(dx, dy)`. Clips usually get this from a
  `Cap` spring driven by the body's motion.
- `sway`: degrees his head and shoulders tip, bending at the waist (positive is right)
- `legs`: a pair, degrees each leg swings back (far leg, near leg; negative is forward)
- `lift`: a pair, how far each foot is raised, in pixels of `cutout.png`
- `crouch`: 0 to 1, how far his knees are bent; at 1 he is kneeling
- `lean` (degrees, positive tips the whole of him right), `squash` (positive is shorter
  and wider), `dx`, `dy` (pixels of `cutout.png`; negative `dy` is up)
- `turn`: degrees he has turned about his upright axis, and `smear`: how many degrees of
  the turn each frame blurs over
- `fx`: lights to draw, a list of `("sparkles", [(x, y, size, angle), ...])` and
  `("ring", ...)` (see `ring_args`), in canvas pixels

To add a dance, write another function and add a line to `CLIPS`; any key starting with
`dance_` appears under **Dance move**.
