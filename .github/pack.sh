#!/usr/bin/env bash
# Packs a published build as a Velopack release (https://velopack.io): the download people
# install DeskDancer from, and the package an installed copy updates itself with.
#
#   .github/pack.sh <runtime> <version> <folder>
#
# <runtime> is win-x64, linux-x64, osx-arm64 or osx-x64, and its build has to be in
# dist/<runtime> already, where publish.sh and publish.ps1 put it. What comes out goes in
# <folder>, next to whatever is there: with the release before in it, a small package of
# just the differences is made as well. For each runtime that is
#
#   DeskDancer-<version>-<runtime>-full.nupkg    what an installed copy downloads to update
#   DeskDancer-<version>-<runtime>-delta.nupkg   the same as differences from the version before
#   releases.<runtime>.json                      the list of versions, which it looks at first
#   DeskDancer-<runtime>-Setup.exe               Windows: the installer
#   DeskDancer-<runtime>-Portable.zip            Windows, macOS: the program to unpack and run
#   DeskDancer-<runtime>.AppImage                Linux: the program
#
# A Mac build has to be packed on a Mac and a Linux one on Linux; a Windows build can be
# packed anywhere. Linux needs squashfs-tools and zstd, and a Mac needs zstd.
set -euo pipefail
cd "$(dirname "$0")/.."

rid="${1:?Which runtime? win-x64, linux-x64, osx-arm64 or osx-x64}"
version="${2:?Which version? Like 1.2.0}"
out="${3:?Which folder should the packages go in?}"

# The tool has to be the version of the Velopack library the program is built with.
velopack="$(sed -n 's:.*Include="Velopack" Version="\([^"]*\)".*:\1:p' src/DeskDancer/DeskDancer.csproj)"
[ -n "$velopack" ] || { echo "Could not find the Velopack version in DeskDancer.csproj" >&2; exit 1; }
export PATH="$PATH:$HOME/.dotnet/tools"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
dotnet tool update --global vpk --version "$velopack" > /dev/null

case "$(uname -s)" in
  Darwin) host=osx ;;
  MINGW*|MSYS*|CYGWIN*) host=win ;;
  *) host=linux ;;
esac
target="${rid%%-*}"
# Packing for another system than this one has to be asked for by name.
vpk=(vpk --yes --legacyConsole --skip-updates)
[ "$target" = "$host" ] || vpk=(vpk "[$target]" --yes --legacyConsole --skip-updates)

pack=(pack --packId DeskDancer --packTitle DeskDancer --packAuthors FriendlyUser
      --packVersion "$version" --runtime "$rid" --channel "$rid" --outputDir "$out")
case "$target" in
  win)
    "${vpk[@]}" "${pack[@]}" --packDir "dist/$rid" --mainExe DeskDancer.exe --icon packaging/icon.ico
    ;;
  linux)
    "${vpk[@]}" "${pack[@]}" --packDir "dist/$rid" --mainExe DeskDancer --icon packaging/icon.png --categories "Game;Amusement"
    ;;
  osx)
    [ "$host" = osx ] || { echo "A Mac build can only be packed on a Mac" >&2; exit 1; }
    # The app that publish.sh made is used as it is. Velopack adds its updater to it, which
    # breaks the seal publish.sh put on, so it is sealed again: with "-", the signature that
    # needs no Apple developer account, as before. There is no installer; the app is the
    # download, and updates itself wherever it has been put.
    "${vpk[@]}" "${pack[@]}" --packDir "dist/$rid/DeskDancer.app" --mainExe DeskDancer --noInst --signAppIdentity -
    ;;
  *)
    echo "Unknown runtime: $rid" >&2
    exit 1
    ;;
esac
echo "Packed DeskDancer $version for $rid in $out:"
ls -l "$out"
