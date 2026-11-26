# How Plush Domo was made

Plush Domo is [Domo](../../domo/_source/README.md) made of fleece: the same shapes, the
same poses and the same eleven clips, painted differently. He is still a flat drawing.
Nothing is modelled in 3D and nothing comes from a photo; the fleece is made by the
script, from random numbers. The app never reads this folder (its name starts with `_`);
it is here so the animations can be changed and rebuilt.

| File | What it is |
| --- | --- |
| `make_frames.py` | The fleece painter. It loads Domo's script for everything else and builds every animation and `character.json`. |

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

It needs `characters/domo/_source/make_frames.py` to be where it is in this project,
because that is where the shapes and the clips are. To change how he moves, or to add a
dance, change that script and rebuild both packs; its README says how.

## How it works

Domo's script works out where every shape of a pose goes and hands them, from the back
to the front, to a painter. Domo's own painter fills each with one flat colour and gives
it a dark edge. The painter here, `Plush`, does this instead:

**The fleece.** One square of cloth is made when the script starts: fine random grain,
smoothed at two sizes and one taken from the other, which leaves curls of about the
same size all over; each curl is then lit from its upper left. The square repeats
without a seam. Every part of him is cut from a different stretch of it.

**Staying put.** The fleece is fixed to the part it is on. Domo's script tells the
painter how each part lies on the canvas, and the cloth is laid the same way, so it
turns with an arm, leans with the body and squashes when he lands. It never slides
across him.

**Edges.** There is no outline. A second pattern in the cloth says where the pile stands
up and where it lies flat, and a part's edge is pushed out or in by it, so the edge is
soft and uneven, and the same from frame to frame.

**Stuffing.** Each part is darker towards its edge all round and lighter on its upper
left, which is what makes it look filled, and it casts a soft shadow on whatever is
behind it: the body on the arms, a sitting leg on the body, the arm that holds the cup on
the cup.

**The face.** The mouth is cut out of the fleece and backed with red felt, in shadow
under its top edge. The teeth are thick cream felt, a little rounded, with their own
shadow on the red. Each eye is a glossy bead sunk into the pile: black, with a soft
shine, a spark, and the room reflected low down. Shut or smiling, an eye is a line of
dark stitching.

**The cup and the cloud.** The cup is clear plastic, so what is behind it shows through
above the tea; it is round, so it is darker towards its sides, with a gleam down it. The
cloud of gas is soft all the way through.

## The clips

The same eleven as Domo's, with the same names in the menu: `idle`, `walk`, `sit`,
`sleep`, `drag`, `fall`, `dance` (**Happy Arms**, shown during all 15 built-in moves),
the dances of his own, **Chomp** and **Monster Stomp**, and his two actions, **Bubble
Tea** and **Fart**.
What each one does is in [Domo's README](../../domo/_source/README.md#the-clips).

The app keeps the idle clip unpacked in memory the whole time, and each other clip while
it is being shown and for a minute afterwards. `make_frames.py` prints the total for
every clip when it finishes (about 201 MB, of which idle is 28 and the two actions 104).
On disk the pack is about 6 MB: fleece is all fine detail, which does not pack down
without loss, so these clips are saved the way a photo is, where Domo's flat colour is
saved exactly.

## Changing things

His colours are at the top of `make_frames.py`: `FLEECE`, `FELT`, `TOOTH`, `BEAD` and the
rest. `weave` makes the cloth: the two sizes it smooths at set how big the curls are, and
the numbers after them how strongly the curls, their lighting and the slow changes in
tone show. In `fur`, the first line of arithmetic sets how uneven the edge is and the
next few how strongly he is shaded. Each thing the painter can be asked for is one
method of `Plush`: `fur`, `crease`, `eye`, `mouth`, `cup` and `gas`.

To make another Domo in a different material, copy this folder into a new pack, give
`build_pack` a new name, and change the painter.
