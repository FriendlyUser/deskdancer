#!/usr/bin/env bash
# Smoke test for the Android build, run on an emulator by .github/workflows/android.yml.
#
#   bash .github/android/smoke.sh DeskDancer.apk out-dir
#
# Installs the APK, grants "display over other apps" the way a person would in Settings,
# puts Mochi on the home screen, makes it dance and drags it, taking screenshots along the
# way. check.py then looks at the screenshots and the log and decides whether it passed.
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
sleep 4
shot 0-home

log "putting the mate on the screen"
adb shell am start -W -n $pkg/.MainActivity --es command start --es character mochi
# First start unpacks the characters and drops the mate in from above.
sleep 12
shot 1-standing

log "dancing"
adb shell am start -W -n $pkg/.MainActivity --es command dance
sleep 3
for i in 1 2 3 4 5 6; do
  shot "2-dancing-$i"
  sleep 0.4
done

log "stopping the dance and dragging the mate"
adb shell am start -W -n $pkg/.MainActivity --es command dance
sleep 3
hit=$(adb logcat -d -s DeskDancer:I | grep -o 'hit=([0-9-]*,[0-9-]* [0-9]*x[0-9]*)' | tail -1)
echo "last hit box: $hit"
if [[ $hit =~ hit=\((-?[0-9]+),(-?[0-9]+)\ ([0-9]+)x([0-9]+)\) ]]; then
  x=$(( BASH_REMATCH[1] + BASH_REMATCH[3] / 2 ))
  y=$(( BASH_REMATCH[2] + BASH_REMATCH[4] / 2 ))
  adb shell input swipe $x $y $(( x - 150 )) $(( y - 500 )) 700
  sleep 0.3
  shot 3-thrown
  sleep 4
  shot 4-landed
else
  echo "no hit box in the log"
fi

log "still running?"
adb shell pidof $pkg && echo "running" || echo "NOT RUNNING"
adb shell dumpsys window windows | grep -E "Window #|mOwnerUid|ty=|mFrame=|mAlpha" | grep -B2 -A3 -i "$pkg" | head -40 || true

adb logcat -d > "$out/logcat.txt"
log "app log"
grep -E " DeskDancer| DOTNET|AndroidRuntime|FATAL|monodroid" "$out/logcat.txt" | tail -60

python3 "$(dirname "$0")/check.py" "$out"
