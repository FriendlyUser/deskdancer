# Making your own character

A character is a folder of images. Put the folder in either of these places:

- the `characters` folder next to the program, or
- your personal one: `%APPDATA%\DeskDancer\characters` on Windows,
  `~/.config/DeskDancer/characters` on Linux. The menu item
  **Character > Open characters folder** creates it and opens it for you.

Then right-click the mate and choose **Character > Reload characters**.

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
| any other name | also becomes a dance, so no animation goes to waste |

A missing animation is covered by the idle picture plus built-in motion. When you do
supply `walk`, the built-in waddle is switched off so your frames are shown as drawn.

An animation can be supplied in three ways:

1. **Animated GIF or WebP**: `walk.gif`. Frame timings come from the file.
2. **Sprite sheet**: one image holding a grid of frames, read left to right, top to
   bottom. Put the grid size in the name: `walk_8x1.png` is 8 columns by 1 row.
3. **Folder of frames**: `walk/001.png`, `walk/002.png`, ... played in name order.

Draw every animation at the same size as your idle picture so the character does not
grow or shrink between them. Empty margins are trimmed automatically and the bottom
of the artwork is treated as the floor.

Only the idle animation is read when the mate appears. Each of the others is read the
first time the mate uses it, and put away again once it has gone a couple of minutes
without being used. So a pack can carry as many as you like: they do not make it slower
to start, and only the ones in use take up memory.

`remix-example` in this folder is a complete pack made of sprite sheets, a folder of
frames and single stills. Copy it and replace the images to get started.

`mochi` is a pack of animated WebP files, all made from one photo. Its `_source` folder
has the scripts that cut the character out and drew the animations, if you want to do
the same with a picture of your own.

`lyra` is the same idea for a drawing: its `_source` folder sharpens the drawing,
takes it off a white background, and animates it with hair that swings on a spring, legs
that walk, a hand that waves and a redrawn face.

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
    "sleep": { "file": "nap.gif", "scale": 0.9, "anchor": [64, 120] }
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
| `fps`, `loop` | Frame rate and whether it repeats. |
| `name` | Menu name for a dance. |
| `scale` | Size multiplier for this animation only. |
| `anchor` | `[x, y]` position of the point between the feet, in pixels of one frame, if the automatic guess is off. |

## If it does not show up

- The folder needs at least one image in it, or in a folder inside it.
- Folders whose names start with `.` or `_` are ignored, both in the `characters`
  folder and inside a character's own folder. That makes them a good place for working
  files: `mochi/_source` is one.
- If the menu shows "could not load", the reason is in `deskdancer.log` in the
  settings folder. The mate uses the built-in character until it is fixed. A file that
  is there but damaged part way through only comes to light when its animation is first
  used: the mate then keeps its other animations and stands still for that one.
- Very large images are scaled down to 640 pixels on their longest side when loaded,
  and an animation is limited to 400 frames.
