#!/usr/bin/env bash
# Tries the self-update for real: installs one version of DeskDancer, puts a newer one in a
# folder standing in for the releases on GitHub, starts the installed one and waits for it to
# find the newer version, swap itself for it and come back.
#
#   .github/update-test.sh <runtime> [folder to work in]
#
# <runtime> is win-x64, linux-x64, osx-arm64 or osx-x64, and its build has to be in
# dist/<runtime> (see pack.sh). The program needs a screen to run on: on Linux that can be
# a virtual one, as in the build workflow. Both versions are the same build under two
# version numbers, which is all it takes: what is being tried is the finding, the fetching
# and the swapping.
set -euo pipefail
cd "$(dirname "$0")/.."

rid="${1:?Which runtime? win-x64, linux-x64, osx-arm64 or osx-x64}"
work="${2:-update-test}"
old=0.0.1
new=0.0.2
patience=180          # seconds the installed copy is given to update itself

rm -rf "$work"
mkdir -p "$work/feed"
# Nothing may be left of an earlier try: a version downloaded then would go in now.
rm -rf /var/tmp/velopack/DeskDancer "$HOME/Library/Caches/velopack/DeskDancer"
work="$(cd "$work" && pwd)"
feed="$work/feed"

echo "::group::Pack $old"
.github/pack.sh "$rid" "$old" "$feed"
echo "::endgroup::"

# Install the old version as a person would, and say how to start it, how to read which
# version is installed, whether it is running, how to stop it, and where Velopack's log is.
case "$rid" in
  linux-*)
    app="$work/DeskDancer.AppImage"
    cp "$feed/DeskDancer-$rid.AppImage" "$app"
    chmod +x "$app"
    # Where there is no FUSE to mount an AppImage with, it unpacks itself instead.
    export APPIMAGE_EXTRACT_AND_RUN=1
    start() { "$app" --update-feed "$feed" > "$work/app.log" 2>&1 & }
    installed() { "$app" --version 2> /dev/null | tail -1; }
    running() { pgrep -f "DeskDancer.*--update-feed" > /dev/null; }
    stop() { pkill -f "DeskDancer.*--update-feed" || true; }
    log=/tmp/velopack_DeskDancer.log
    ;;
  osx-*)
    ditto -x -k "$feed/DeskDancer-$rid-Portable.zip" "$work"
    app="$work/DeskDancer.app"
    # Velopack added its updater to the app and sealed it again; the seal has to hold.
    codesign --verify --deep --strict --verbose=2 "$app"
    start() { "$app/Contents/MacOS/DeskDancer" --update-feed "$feed" > "$work/app.log" 2>&1 & }
    installed() { sed -n 's:.*<version>\(.*\)</version>.*:\1:p' "$app/Contents/Resources/sq.version" 2> /dev/null; }
    running() { pgrep -f "DeskDancer.*--update-feed" > /dev/null; }
    stop() { pkill -f "DeskDancer.*--update-feed" || true; }
    log="$HOME/Library/Logs/velopack_DeskDancer.log"
    ;;
  win-*)
    root="$work/installed"
    "$feed/DeskDancer-$rid-Setup.exe" --silent --installto "$(cygpath -w "$root")"
    start() { "$root/current/DeskDancer.exe" --update-feed "$(cygpath -w "$feed")" > "$work/app.log" 2>&1 & }
    installed() { sed -n 's:.*<version>\(.*\)</version>.*:\1:p' "$root/current/sq.version" 2> /dev/null; }
    running() { tasklist //FI "IMAGENAME eq DeskDancer.exe" 2> /dev/null | grep -qi "DeskDancer.exe"; }
    stop() { taskkill //F //IM DeskDancer.exe > /dev/null 2>&1 || true; }
    log="$LOCALAPPDATA/velopack/velopack_DeskDancer.log"
    ;;
  *)
    echo "Unknown runtime: $rid" >&2
    exit 1
    ;;
esac

fail() {
  echo "::error::Self-update ($rid): $1"
  echo "::group::The program's own output"; cat "$work/app.log" 2> /dev/null || true; echo "::endgroup::"
  echo "::group::Velopack's log"; tail -n 200 "$log" 2> /dev/null || echo "(none at $log)"; echo "::endgroup::"
  stop
  exit 1
}

[ "$(installed)" = "$old" ] || fail "installing $old left version '$(installed)' installed"
echo "Installed DeskDancer $(installed)"

echo "::group::Pack $new"
.github/pack.sh "$rid" "$new" "$feed"
echo "::endgroup::"

start
echo "Started DeskDancer $old, with $new waiting in $feed"
waited=0
until [ "$(installed)" = "$new" ]; do
  [ "$waited" -lt "$patience" ] || fail "after $patience seconds the installed version is still '$(installed)', not $new"
  sleep 2
  waited=$((waited + 2))
done
echo "After about $waited seconds the installed version is $(installed)"

# It should have come back by itself, as the new version.
waited=0
until running; do
  [ "$waited" -lt 60 ] || fail "the program did not start again after updating itself"
  sleep 2
  waited=$((waited + 2))
done
# And stay: the new version looks in the same folder, and must find nothing newer than itself.
sleep 10
running || fail "the program started again after updating itself, and then stopped"
[ "$(installed)" = "$new" ] || fail "the installed version changed again, to '$(installed)'"
stop
echo "Self-update works on $rid: DeskDancer $old found $new, swapped itself for it and started again."
