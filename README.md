# DeskDancer

A little mate that lives on your desktop and dances. It stands on your taskbar, wanders
about, sits down, naps, and breaks into dance moves on its own or whenever you ask.
Written in C# with [Avalonia](https://avaloniaui.net/); runs on Windows, Linux and macOS.

![Mochi, the character you start with, in five poses](docs/mochi.png)

The mate you start with is **Mochi**. It is an image pack, animated from a single photo.
Standing, it blinks, flicks an ear and tilts its head; it waddles from foot to foot when
it wanders, puts on a happy face and flaps its ears for every dance move, and has two
dances of its own, Bunny Hop and Ear Wave. Its ears swing on springs, so they trail and
flop as it moves. How it was made, and how to change it, is in
[characters/mochi/_source](characters/mochi/_source/README.md).

![Remix, the built-in character, in five poses](docs/remix.png)

**Remix** is a DJ robot drawn entirely in code, with arms, legs and a face of its own.
Switch between the two under **Character** in the menu. You can also drop in a folder of
your own images and it becomes a character that walks and dances too: see
[characters/README.md](characters/README.md).

## Run it

You need the [.NET 10 SDK](https://dotnet.microsoft.com/download) to build. The result
is a single self-contained program that needs nothing installed to run.

Windows (PowerShell):

```powershell
.\publish.ps1
dist\win-x64\DeskDancer.exe
```

Linux:

```bash
./publish.sh
dist/linux-x64/DeskDancer
```

macOS:

```bash
./publish.sh
open dist/osx-arm64/DeskDancer.app
```

On a Mac the script builds for the machine it is run on (`osx-arm64` on Apple silicon,
`osx-x64` on Intel) and wraps the result up as an app.

Either script takes a runtime name if you want to build for another system, for example
`./publish.sh win-x64`. Keep the `characters` folder next to the program: Mochi lives in
it, and without it the mate is Remix. In the Mac app it is inside the app itself.

Every push is also built by GitHub Actions. If you would rather not install .NET, open
the latest run under the repository's **Actions** tab and download one of its artifacts:
`DeskDancer-win-x64`, `DeskDancer-linux-x64`, `DeskDancer-osx-arm64` (Macs with Apple
silicon) or `DeskDancer-osx-x64` (Intel Macs).

To run straight from source instead: `dotnet run --project src/DeskDancer`.

## Using it

| Do this | And the mate |
| --- | --- |
| Double-click | starts a random four-move dance (double-click again to stop) |
| Click | does a happy hop |
| Drag | gets picked up; let go and it drops, throw it and it flies |
| Right-click | opens the menu |

The right-click menu has everything else:

- **Dance move / Routine**: pick one of 15 moves or a choreographed routine.
- **Dance party**: every mate on screen dances non-stop, in sync.
- **Tempo**: 80 to 160 BPM. All moves are written against the beat, so they follow it.
- **Sit down / Take a nap**, and switches for wandering, dancing on its own, falling
  when dropped, and the notes-and-sparkles effects.
- **Character / Size / Add another mate**: switch character, resize from 50% to 300%,
  or put several mates on screen at once.
- **Always on top**, **Click through empty space**, **Quit**.

### The moves

Bounce, Sway, Disco Point, Side Step, Shuffle, Wiggle, Headbang, Pop & Lock, Star Jumps,
Twirl, Tornado, Backflip, Cartwheel, Moonwalk and Strut. The last three travel across
the screen. Routines chain them: Disco Fever, Street, Acrobat and Chill.

Every move works on every character. Remix also moves its arms, legs, head and face;
image characters are bounced, leaned, spun and flipped as a whole.

## Platform notes

**Windows 10 and 11.** Nothing to set up.

**Linux.** Needs an X11 session, or Wayland with XWayland (the default on GNOME and
KDE), and a compositing window manager for the transparent background. Without a
compositor the mate appears on a black rectangle.

**macOS.** Macs with Apple silicon or Intel, on macOS 12 or later. The download unzips
to `DeskDancer.app`. It is not signed with an Apple developer ID, so the first time
macOS will say it cannot check the app. Open **System Settings > Privacy & Security**,
scroll down and choose **Open Anyway** (on macOS 14 and earlier, right-clicking the app
and choosing **Open** works too), or clear the download flag from a terminal:

```bash
xattr -dr com.apple.quarantine DeskDancer.app
```

An app you build yourself has no such flag and just opens. DeskDancer shows in the Dock
while it runs; quit from there or from the mate's menu. The mate stands on the Dock, or
on the bottom of the screen if the Dock is hidden or at the side.

**Clicking through.** The mate lives in a small transparent window. So that the empty
part of it does not block what is underneath, only the area around the character
takes mouse input. On Windows this is done while the mate is standing, sitting or
walking; during a dance the whole window (roughly 1.7 x 2 character heights) takes
clicks. On macOS a window either takes the mouse or ignores it altogether, so the mate's
window is switched from one to the other as the pointer moves on and off the character.
Turn the feature off in the menu if it misbehaves with your setup.

Settings are remembered in `%APPDATA%\DeskDancer` on Windows, `~/.config/DeskDancer` on
Linux and `~/Library/Application Support/DeskDancer` on macOS, along with a log file if
something goes wrong. That includes which character each mate is, so a mate you already
have stays as it was when the program is updated.

## Command line

```
--character <id>        Start with this character: "builtin" for Remix, or a folder
                        name such as "mochi"
--characters <folder>   Also look for character folders here
--fresh                 Ignore saved settings for this run
--smoke-test            Run every feature for a few seconds, exit 0 on success
--render-test <dir>     Render every dance move to PNG contact sheets
--export-sample <dir>   Write the built-in character out as an example image pack
```

## How it is put together

```
src/DeskDancer/
  Engine/       Behaviour and choreography. No UI code in here.
    DanceMoves.cs   Each move is a function from "beats elapsed" to a pose
    MateBrain.cs    Idle / walk / sit / sleep / dance / drag / fall state machine
    Conductor.cs    Beat clock and the shared session behind the dance party
  Characters/   Remix (drawn in code) and the loader for image packs
  Ui/           The transparent window, its menu and the renderer
  Platform/     Click-through for Windows, X11 and macOS
  Tools/        Smoke test, contact sheets and the example pack exporter
characters/     Character packs that ship with the app
packaging/      What macOS needs in order to treat the build as an app
```

The GitHub Actions workflow builds for Windows, Linux and both kinds of Mac, and runs
the smoke test on each. The smoke test starts the real app and drives it: dancing, a
two-mate party, the menu, dragging and throwing, with Mochi, Remix and the example pack
each taking a turn. On Windows and macOS it also reads pixels back off the screen to
confirm that the window is see-through and the character is visible, checks that clicks
pass through the empty part of the window, and saves pictures of the desktop as
artifacts. On macOS, where what a click lands on depends on where the pointer is, it
moves the pointer onto the mate, off onto the empty corner of its window and back again,
and asks the system each time.

One thing to know when building: Avalonia's build step sends anonymous usage data to
its vendor. The publish scripts and the workflow switch that off with
`AVALONIA_TELEMETRY_OPTOUT=1`; set it yourself if you build some other way.
