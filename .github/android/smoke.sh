#!/usr/bin/env bash
# Smoke test for the Android build, run on an emulator by .github/workflows/android.yml.
#
#   bash .github/android/smoke.sh DeskDancer.apk out-dir
#
# Installs the APK, grants "display over other apps" the way a person would in Settings,
# puts Mochi on the home screen, makes it dance and drags it, taking screenshots along the
# way. Then it puts a character in a folder on the phone, chooses that folder in the
# phone's folder picker by tapping through it, shows the character, opens the folder in the
# Files app and switches a move off in the settings. check.py then looks at the screenshots
# and the log and decides whether it passed.
set -uo pipefail

apk=$1
out=$2
pkg=io.github.friendlyuser.deskdancer
mkdir -p "$out"

shot() { adb exec-out screencap -p > "$out/$1.png"; }
log() { echo "== $*"; }

log "installing"
adb install -r "$apk" || exit 1
adb shell appops set $pkg SYSTEM_ALERT_WINDOW allow
adb shell pm grant $pkg android.permission.POST_NOTIFICATIONS || true
adb shell wm size
adb shell wm density
adb logcat -c

log "home screen, before"
adb shell input keyevent KEYCODE_HOME
# A freshly booted emulator's launcher keeps drawing for a while; wait until it holds still.
for i in $(seq 1 15); do
  sleep 2
  shot 0-home-a
  sleep 1
  shot 0-home
  cmp -s "$out/0-home-a.png" "$out/0-home.png" && { echo "home screen settled"; break; }
done
rm -f "$out/0-home-a.png"

log "putting the mate on the screen"
adb shell am start -W -n $pkg/.MainActivity --es command start --es character mochi --ez calm true
# First start unpacks the characters and drops the mate in from above.
sleep 12
shot 1-standing
# Where Android has put the mate's two windows at this moment, and how it composites them.
adb shell dumpsys window windows > "$out/1-standing-windows.txt"
adb shell dumpsys SurfaceFlinger > "$out/1-standing-surfaceflinger.txt"
log "the mate's layers, as SurfaceFlinger has them"
grep -n -i -A12 "deskdancer" "$out/1-standing-surfaceflinger.txt" | grep -i -E "deskdancer|isOpaque|opaque|alpha|format|z=|zOrder|flags|color|blend" | head -60 || true

log "dancing"
adb shell am start -W -n $pkg/.MainActivity --es command dance
sleep 3
for i in 1 2 3 4 5 6; do
  shot "2-dancing-$i"
  sleep 0.4
done

log "stopping the dance and dragging the mate"
adb shell am start -W -n $pkg/.MainActivity --es command rest
sleep 3
adb shell dumpsys window windows > "$out/3-before-drag-windows.txt"
hit=$(adb logcat -d -s DeskDancer:I | grep -o 'hit=([0-9-]*,[0-9-]* [0-9]*x[0-9]*)' | tail -1)
echo "last hit box: $hit"
if [[ $hit =~ hit=\((-?[0-9]+),(-?[0-9]+)\ ([0-9]+)x([0-9]+)\) ]]; then
  x=$(( BASH_REMATCH[1] + BASH_REMATCH[3] / 2 ))
  y=$(( BASH_REMATCH[2] + BASH_REMATCH[4] / 2 ))
  echo "swiping from ($x,$y)"
  adb shell input swipe $x $y $(( x - 150 )) $(( y - 500 )) 700
  sleep 0.3
  shot 3-thrown
  # If the touch never reached the mate, keep what Android knew about where it went.
  if ! adb logcat -d -s DeskDancer:I | grep -q "touch down"; then
    echo "no touch reached the mate; input and window state follow"
    adb shell dumpsys input > "$out/3-input.txt"
    adb shell dumpsys window windows > "$out/3-after-drag-windows.txt"
    # Every window input is offered to, top first, with what each does with a touch.
    sed -n '/Windows:/,/^  [A-Z]/p' "$out/3-input.txt" | grep -E "^ +[0-9]+: name=" \
      | sed -E 's/, (globalScale|applicationInfo\.(name|token)|ownerPid|dispatchingTimeout|hasToken)=[^,]*//g' | head -24
    adb logcat -d | grep -i -E "InputDispatcher|untrusted touch|obscur" | tail -20 || true
    # Where across the mate a touch does get through: taps along the middle of the hit box.
    w=${BASH_REMATCH[3]}
    for fx in 15 35 50 65 85; do
      tx=$(( BASH_REMATCH[1] + w * fx / 100 ))
      before=$(adb logcat -d -s DeskDancer:I | grep -c "touch down")
      adb shell input tap $tx $y
      sleep 1
      after=$(adb logcat -d -s DeskDancer:I | grep -c "touch down")
      echo "tap at ($tx,$y): $([ "$after" -gt "$before" ] && echo reached the mate || echo LOST)"
    done
  fi
  sleep 4
  shot 4-landed
else
  echo "no hit box in the log"
fi

log "still running?"
adb shell pidof $pkg && echo "running" || echo "NOT RUNNING"

log "putting the mate away"
adb shell am start -W -n $pkg/.MainActivity --es command stop
sleep 4
shot 5-home-after

# ---- A character of the user's own, in a folder chosen in the phone's folder picker ----

# Taps the first thing on the screen whose text, in any case, is $1, as uiautomator sees the
# screen; what it saw is kept as ui-$2.xml.
tap_text() {
  local want=$1 tag=$2 xy
  adb shell uiautomator dump /sdcard/ui.xml > /dev/null 2>&1
  adb pull /sdcard/ui.xml "$out/ui-$tag.xml" > /dev/null 2>&1
  xy=$(python3 - "$out/ui-$tag.xml" "$want" <<'PY'
import re, sys, xml.etree.ElementTree as ET
want = sys.argv[2].lower()
try:
    nodes = list(ET.parse(sys.argv[1]).iter("node"))
except Exception:
    nodes = []
for node in nodes:
    if want in (node.get("text", "").strip().lower(), node.get("content-desc", "").strip().lower()):
        x0, y0, x1, y1 = map(int, re.findall(r"-?\d+", node.get("bounds", "")))
        print((x0 + x1) // 2, (y0 + y1) // 2)
        break
PY
)
  if [ -z "$xy" ]; then
    echo "nothing on the screen says '$want'"
    return 1
  fi
  echo "tapping '$want' at $xy"
  adb shell input tap $xy
}

log "putting a character in a folder on the phone"
folder=/sdcard/Documents/DeskDancer
adb shell mkdir -p "$folder/kori"
adb push characters/kori/character.json characters/kori/*.webp "$folder/kori/" > /dev/null
adb shell ls "$folder/kori"

log "choosing the folder in the folder picker"
adb shell am start -W -n $pkg/.MainActivity --es command choose-folder --es folder Documents/DeskDancer
sleep 5
shot 6-picker
for step in "Use this folder" "Allow"; do
  for try in 1 2 3; do
    tap_text "$step" "${step// /-}-$try" && break
    sleep 2
  done
  sleep 3
done
# The character is copied in and the characters read again.
sleep 6
shot 6-folder-chosen
adb logcat -d -s DeskDancer:I | grep -E "characters folder|command" | tail -6

log "the character from the folder, on the screen"
adb shell am start -W -n $pkg/.MainActivity --es command start --es character kori --ez calm true
sleep 10
shot 7-kori
adb shell dumpsys window windows > "$out/7-kori-windows.txt"
adb shell am start -W -n $pkg/.MainActivity --es command stop
sleep 3

log "opening the folder in the Files app"
adb shell am start -W -n $pkg/.MainActivity --es command open-folder
sleep 5
shot 8-files
adb shell dumpsys activity activities > "$out/8-activities.txt"
grep -m3 -E "ResumedActivity" "$out/8-activities.txt" || true

log "switching a move off in the settings"
adb shell am start -W -n $pkg/.MainActivity --es command show-moves --es move backflip
sleep 3
shot 9-moves
for try in 1 2 3; do
  tap_text "Backflip" "backflip-$try" && break
  sleep 2
done
sleep 2
shot 9-moves-after
adb shell input keyevent KEYCODE_HOME
sleep 2

adb logcat -d > "$out/logcat.txt"
log "app log"
grep -E " DeskDancer| DOTNET|AndroidRuntime|FATAL|monodroid" "$out/logcat.txt" | tail -60

python3 "$(dirname "$0")/check.py" "$out"
