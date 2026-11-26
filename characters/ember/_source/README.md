# How Ember was made

Ember is a ball of fire drawn by a script, an original character made for this project.
There is no picture behind it: every frame of every clip is drawn fresh. The app never reads
this folder (its name starts with `_`); it is here so the animations can be changed and
rebuilt.

| File | What it is |
| --- | --- |
| `make_frames.py` | Draws Ember, and builds every animation and `character.json`. |

## Rebuilding the animations

```bash
pip install numpy pillow
python3 make_frames.py
```

It takes about a minute and overwrites the clips and `character.json` in the folder above.
Then right-click the mate and choose **Character > Reload characters**.
`python3 make_frames.py --sheet` also saves `sheet.png` with every frame on one page, and
`python3 make_frames.py dance_fireworks walk` rebuilds only the clips named. Running it twice
gives the same files.

## How it works

**The ball.** Ember's body is a round ball lit from a hot yellow core, up and to the left of
its middle, out through orange to a deep red rim. Swirls of heat turn slowly inside it, and
a shine sits at the top left. A soft orange glow surrounds the ball and its flame. The glow
is drawn small, blurred and scaled up, so it has no edge, and its faintest fringe is cut
off so it doesn't make every frame bigger for nothing. Everything else is drawn hard-edged at
four times the saved size and averaged down, which is where the smooth edges come from.

**The flame.** Three tongues of fire stand on top of the ball: a tall one in the middle and a
shorter one leaning out on each side. Each tongue is wide low down and pointed at the tip,
with a lick of a curve running up it, and is drawn in four layers: red outside, then orange,
then yellow, then a white-hot core in the middle one, each running hotter towards its base.
The flame is drawn behind the ball, so it grows out of the top of Ember's head.

The flame never keeps still. Each tongue stretches, sways and wriggles on its own, made of
waves that fit a whole number of times into the clip being drawn, so every clip loops without
a jump. A pose can make it bigger or smaller and flicker more wildly. Fire rises, so the
flame stays upright when Ember leans, and its tips trail behind the top of Ember's head as
it moves.

**The face, arms and legs.** The eyes are beads with two shines; they blink, widen, close,
squeeze shut (`> <`), smile (`^ ^`) and swirl. The mouth can smile, open, grin, make a little
"o", a `:3`, a flat line, or a wavy "ow ow ow". The arms are stubby tubes that hang from
behind the ball. As with Domo and Kori, a clip says where they should be and a spring
carries them there, pushed about by how Ember moves, so they lag and flop. The legs are two
short stubs, and sitting, two round soles stick out in front instead.

**Sparks, embers, smoke.** Sparks are four-pointed stars, white-hot edged in orange; fireworks
come in colours. Embers are little glowing dots that drift up off the flame and go out.
Smoke is a grey puff.

## The clips

| Clip | When the app shows it |
| --- | --- |
| `idle.webp` | Standing, its flame flickering. Blinks, glances to one side, lets embers drift up, and now and then flares up happily. |
| `walk.webp` | Wandering: a waddle from foot to foot on its stubby legs, arms swinging, the flame trailing behind. |
| `sit.webp` | Sitting with its feet out in front, its flame calm. Blinks, waggles its feet, and lets an ember drift up now and then. |
| `sleep.webp` | Dozing where it sits, eyes shut, its flame burnt down to a little flicker with a wisp of smoke rising off it. The app adds the breathing and the Zs. |
| `dance.webp` | During all 15 built-in dance moves, which add their own body motion: both arms up and waving, a big grin, and the flame leaping on every beat with a spark off its tip. Also listed as **Happy Flames**. |
| `dance_flare_up.webp` | **Flare Up**, four beats: it crouches and its flame sinks low while it gathers itself, then it springs up and the flame roars into a tall column with a burst of sparks, blazes there for two beats, and settles back down with a bounce. |
| `dance_hot_potato.webp` | **Hot Potato**, two beats: hopping from foot to foot as if the floor were too hot, eyes squeezed shut, going "ow ow ow", with a puff of smoke from each foot as it lands. |
| `dance_fireworks.webp` | **Fireworks**, four beats: it winds up with its arms back and flings them up, and a spark shoots out of its flame into the sky, where it bursts into a ring of coloured sparkles. Ember watches with an "ooh", then a smaller one goes up and it cheers. |
| `drag.webp` | Being carried: eyes wide, a little "o", arms flailing, legs pedalling, the flame flickering wildly. |
| `fall.webp` | Dropping through the air, arms up, the flame stretched out above. |

Clip dances get no motion from the app, so the hops and bounces are drawn in. At the usual
120 BPM, Flare Up and Fireworks loop in two seconds and Hot Potato in one.

The app keeps every frame of a clip it is showing unpacked in memory, and as the flame is
always moving, every frame of Ember's is a frame of its own. `make_frames.py` prints the
total when it finishes: about 134 MB for every clip at once, while standing about Ember holds
only its idle clip, 25 MB. The clips run at 10 frames a second when Ember is standing,
sitting or napping, and at 20 when it is moving, and each is cropped to what it uses. On disk
the pack is about 5 MB.

## Changing things

Each clip is a short function near the end of `make_frames.py` (`idle`, `walk`, `sitting`,
`asleep`, `happy_flames`, `flare_up`, `hot_potato`, `fireworks`, `carried`, `falling`). It is
given the time in seconds and returns a pose. A pose can set:

- `eyes`: a pair, each `"open"`, `"wide"`, `"happy"`, `"closed"`, `"squint"`, `"dizzy"`, or a
  number from 0 to 1 for how far shut; `look`: how far the face moves right and down
- `mouth`: `"smile"`, `"open"`, `"grin"`, `"o"`, `"cat"`, `"flat"` or `"wobble"`
- `arms`: degrees each arm is lifted from hanging straight down (90 is straight out to the
  side); the spring adds its own swing
- `legs`: for each leg, degrees swung outwards and how far it is lifted; `seated`: `True` to
  sit it down
- `flame`: how big the flame is, 1 as usual, about 0.35 asleep and up to about 1.9;
  `wild`: how much more wildly it flickers, 0 to 1; `wind`: how far its tips are blown
  sideways, on top of what moving does
- `glow`: how strongly the air round Ember glows, 0 to 1
- `fx`: sparks `("spark", x, y, size, angle)`, coloured ones
  `("colour-spark", x, y, size, angle, (r, g, b))`, embers `("ember", x, y, radius, opacity)`,
  smoke `("smoke", x, y, radius, opacity)` and the streak of a rising spark
  `("trail", x0, y0, x1, y1, opacity)`, in units; `embers()` and `burst()` make the usual ones
- `squash` (positive is shorter and wider), `lean` (degrees, positive tips right), and `dx`,
  `dy` for the whole mate (negative `dy` is up)

Distances are in units: standing, Ember is about 330 tall with its flame. `CLIPS` lists each
clip's length and how many frames a second to draw it at, which has to divide 500, the rate
clips are sampled at, so that a loop is exactly as long as it should be. The clip must end as
it began, because it loops. To add a dance, write another function and add a line to
`CLIPS`; any key starting with `dance_` appears under **Dance move**.

The size of the ball, the flame, the face and the colours are the constants at the top: `R`,
`LEGS`, `FLAME_H`, `FLAME_BASE`, `EYES`, `MOUTH`, `CHEEKS`, `BODY_CORE`, `FLAME_OUT`, `INK` and
the rest. `OUT` sets how large the frames are saved.
