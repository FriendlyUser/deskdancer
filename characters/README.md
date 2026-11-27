# Making your own character

A character is a folder of images. Put the folder in either of these places:

- the `characters` folder next to the program, or
- your personal one: `%APPDATA%\DeskDancer\characters` on Windows,
  `~/.config/DeskDancer/characters` on Linux,
  `~/Library/Application Support/DeskDancer/characters` on macOS. The menu item
  **Character > Open characters folder** creates it and opens it for you. On a computer,
  **Settings...** shows where it is and lets you keep your characters in another folder
  instead; that one is then looked in first, and this one after it.

Use your personal one if DeskDancer came from one of its downloads. Such a copy updates
itself, and each update replaces the folder next to the program with the new version's;
on Linux and macOS that folder cannot be written to at all. The one next to the program is
for a copy you built yourself.

Then right-click the mate and choose **Character > Reload characters**.

On Android, put the folder in a folder of your own on the phone and choose that folder in
DeskDancer's settings, under **Your own characters**. See "Your own characters on Android"
in the [main README](../README.md#platform-notes).

Only use artwork you made or have permission to use.

## The quick version

One image is enough:

```
my-character/
    idle.png
```

That gives you a character that stands, waddles around, sits, naps and does all 15
dance moves, because the app animates the picture as a whole.

Use a **transparent background**. PNG, GIF and WebP all carry transparency. If an
image has no transparency at all and its four corners are the same colour, that
colour is removed automatically, working inwards from the edges, so a drawing on a
plain white or green backdrop also works. A photo with a busy background will not.

## Adding animations

Name each file after what it is for. Everything is optional except some kind of idle.

| File name | Used when the mate is |
| --- | --- |
| `idle` | standing still |
| `walk` | wandering along the floor |
| `sit` | sitting |
| `sleep` | napping (falls back to `sit`) |
| `drag` | being carried by the mouse (falls back to `fall`) |
| `fall` | dropping through the air (falls back to `drag`) |
| `dance`, `dance_anything` | each one becomes its own entry under **Dance move** |
| `action_anything` | each one becomes its own entry under **Actions** (see below) |
| any other name | also becomes a dance, so no animation goes to waste |

A missing animation is covered by the idle picture plus built-in motion. When you do
supply `walk`, the built-in waddle is switched off so your frames are shown as drawn.

A dance and an action are shown in different ways. A dance is danced to the beat: it
repeats for as long as the move lasts, with music notes rising and a glowing floor under
the mate. An action, such as `action_drink`, is something the mate does: it is played
once through at its own speed, as long as the animation is, with no notes and no floor,
and then the mate goes back to standing about. It is also done now and then unasked. Start
and end an action standing as in your idle picture, so the mate goes into it and comes out
of it without a jump. `domo` has three: `action_bubble_tea`, `action_fart` and
`action_apple_tree`; `piplup` has one, `action_take_a_bow`.

An action can take the mate across the screen. Draw the character running on the spot, in
the middle of the picture, and say in `character.json` how far it has really got at each
moment, with `travel` (see below): the app moves the mate by that much while the action
plays. Anything else in the picture that should stay put on the ground then has to be
drawn sliding the other way, and looks best if it is gone before the running starts.
Where the screen has no room for the journey, the app plays the action mirrored and goes
the other way.

A long action costs next to no memory. One that is a single animated GIF or WebP, with its
`anchor` given in `character.json`, is not unpacked like other animations: its frames are
read from the file one at a time as they are shown. So it can be long, well past the 400
frames other animations are limited to, and drawn as smoothly as you like. What it shows still has to fit in the mate's window, which reaches
one of the character's heights to each side of its feet and 1.8 heights above them.

An animation can be supplied in three ways:

1. **Animated GIF or WebP**: `walk.gif`. Frame timings come from the file.
2. **Sprite sheet**: one image holding a grid of frames, read left to right, top to
   bottom. Put the grid size in the name: `walk_8x1.png` is 8 columns by 1 row.
3. **Folder of frames**: `walk/001.png`, `walk/002.png`, ... played in name order.

Draw every animation at the same size as your idle picture so the character does not
grow or shrink between them. Empty margins are trimmed automatically and the bottom
of the artwork is treated as the floor.

Frames take memory once they are unpacked: four bytes for every pixel of every frame.
The idle animation is in memory for as long as the character is on screen. Each of the
others is read the first time the mate needs it, with the idle picture standing in for
the few frames that takes, and is dropped again when it has not been shown for a
minute. So a long idle animation costs more than a long dance does.

`remix-example` in this folder is a complete pack made of sprite sheets, a folder of
frames and single stills. Copy it and replace the images to get started.

`mochi` is a pack of animated WebP files, all made from one photo. Its `_source` folder
has the scripts that cut the character out and drew the animations, if you want to do
the same with a picture of your own.

`lyra` is the same idea for a drawing: its `_source` folder sharpens the drawing,
takes it off a white background, and animates it with hair that swings on a spring, legs
that walk, a hand that waves, an arm that strums her lute and a redrawn face.

`domo` is a pack with no picture behind it at all: the script in its `_source` folder
draws every frame. It is the one to copy if you would rather describe a character in
shapes than paint it, and it has clips for sitting and napping as well.

`domo-plush` is the same character painted in fleece. Its `_source` folder holds only a
painter; the shapes and the clips come from `domo`'s script, which shows how one
character can be given a second look without drawing it twice.

`sprig` is another drawing, and the one to copy if your character holds something that
should move: its `_source` folder cuts the sword arm out in one piece, paints in what was
behind it so the arm can swing anywhere, and turns the whole character round for a spin
with motion blur and a ring of light.

`kori` is drawn by a script too, but as a box in three dimensions rather than flat shapes:
the one to copy if your character should turn round on the spot with its sides lit as
they come into view, or change shape altogether, as Kori does when it melts.

`ember` is drawn by a script as well, and is the one to copy for something that never keeps
still: its flame is made of waves that fit a whole number of times into each clip, so every
clip loops without a jump however much it flickers, and it glows.

`aspen` is drawn by a script too, and is the one to copy for something soft: its body is
built along a line that bows and curls, so it bends without creasing, with springs to make
it trail and flop. It also shows how to turn a flat character round to its back, and how to
change its colours from one clip to the next.

`piplup` is drawn by a script after a picture, and is the one to copy if you have one
drawing of a character and want it to turn round: its head and body are balls, with the
face and markings placed on them as on a globe, and its measurements were taken from the
picture. It is also the one to copy for the look of a soft toy lit in 3D without modelling
anything in 3D: each pixel is lit by which way the part it is on faces there. Its walk is
the one to copy for feet that do not slide: a foot on the floor goes back exactly as fast
as the app moves the mate forward.

## character.json (optional)

Add this file to the folder to adjust things. Every setting is optional.

```json
{
  "name": "My Character",
  "height": 150,
  "facing": "right",
  "pixelArt": false,
  "fps": 10,
  "removeBackground": "auto",
  "tolerance": 28,
  "normalize": false,
  "clips": {
    "walk": { "file": "walk.png", "columns": 8, "rows": 1, "fps": 12 },
    "dance_spin": { "folder": "spin", "name": "Spin", "fps": 15, "loop": true },
    "sleep": { "file": "nap.gif", "scale": 0.9, "anchor": [64, 120] },
    "action_dash": { "file": "dash.webp", "anchor": [150, 290], "travel": [[1.0, 0], [3.0, -2.5], [5.0, 0]] }
  }
}
```

| Setting | Meaning |
| --- | --- |
| `name` | Name shown in the menu. Defaults to the folder name. |
| `height` | Height on screen in pixels at 100% size. Default 150. |
| `facing` | Which way the artwork faces, `"right"` or `"left"`. It is mirrored when the mate walks the other way. |
| `pixelArt` | `true` keeps hard pixel edges when scaled up. |
| `fps` | Frame rate for sprite sheets and frame folders. Default 10. GIFs keep their own timing. |
| `removeBackground` | `"auto"` (default), `false` to never touch the image, or a colour such as `"#00ff00"` to remove that colour even from images that already have transparency. |
| `tolerance` | How close to the background colour a pixel must be to be removed, 0 to 200. Default 28. |
| `normalize` | `true` scales every animation to the same height as idle. Useful when your images come in different sizes. |

Per animation, inside `clips`:

| Setting | Meaning |
| --- | --- |
| `file` or `folder` | Where the frames are, relative to the character folder. |
| `columns`, `rows`, `count` | Sprite sheet grid, and how many cells are used if the last row is not full. |
| `fps`, `loop` | Frame rate and whether it repeats. Everything repeats unless told otherwise, except an action. |
| `name` | Menu name for a dance or an action. |
| `scale` | Size multiplier for this animation only. |
| `anchor` | `[x, y]` position of the point between the feet, in pixels of one frame, if the automatic guess is off. |
| `travel` | For an action that goes somewhere: a list of `[seconds, distance]` pairs saying how far the mate has got by each moment, in the character's own heights, positive to the right of the picture, with straight lines between. It starts at 0 and stays where the last pair leaves it. |

## If it does not show up

- The folder needs at least one image in it, or in a folder inside it.
- Folders whose names start with `.` or `_` are ignored, both in the `characters`
  folder and inside a character's own folder. That makes them a good place for working
  files: `mochi/_source` is one.
- If the menu shows "could not load", the reason is in `deskdancer.log` in the
  settings folder. The mate uses the built-in character until it is fixed. If it is
  only that one of the animations is damaged, the mate keeps its character and the idle
  picture is shown where that animation would be.
- Very large images are scaled down to 640 pixels on their longest side when loaded,
  and an animation is limited to 400 frames.
