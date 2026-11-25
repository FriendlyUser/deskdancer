#!/usr/bin/env bash
# Builds a self-contained DeskDancer into dist/<runtime>. No .NET install is needed to run the result.
#   ./publish.sh              -> this machine's system: linux-x64, or on a Mac osx-arm64 / osx-x64
#   ./publish.sh win-x64      -> Windows build (cross-compiles fine from Linux)
#   ./publish.sh osx-arm64    -> macOS app for Apple silicon: dist/osx-arm64/DeskDancer.app
#   ./publish.sh osx-x64      -> the same for Intel Macs
set -euo pipefail
cd "$(dirname "$0")"

# Avalonia's build step sends anonymous usage data to its vendor unless this is set.
export AVALONIA_TELEMETRY_OPTOUT=1

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) host=osx-arm64 ;;
  Darwin-*)     host=osx-x64 ;;
  *)            host=linux-x64 ;;
esac
rid="${1:-$host}"

publish() {
  dotnet publish src/DeskDancer -c Release -r "$rid" --self-contained true \
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true \
    -p:DebugType=none -o "$1"
}

if [[ "$rid" != osx-* ]]; then
  publish "dist/$rid"
  echo "Done: dist/$rid"
  exit 0
fi

# macOS wants an app bundle: a folder called DeskDancer.app with the program in
# Contents/MacOS, everything it reads in Contents/Resources, and Info.plist to describe it.
app="dist/$rid/DeskDancer.app"
files="dist/$rid/files"
rm -rf "$app" "$files"
publish "$files"

mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
mv "$files/characters" "$app/Contents/Resources/characters"
mv "$files"/* "$app/Contents/MacOS/"
rmdir "$files"
chmod +x "$app/Contents/MacOS/DeskDancer"
version="$(sed -n 's:.*<Version>\(.*\)</Version>.*:\1:p' src/DeskDancer/DeskDancer.csproj)"
sed "s/@VERSION@/$version/g" packaging/macos/Info.plist > "$app/Contents/Info.plist"

# Seal the bundle with an ad-hoc signature (no Apple developer account involved), so macOS
# sees one consistent app. Only a Mac has the tool for that. Built anywhere else, just the
# program inside is signed, which the .NET SDK does itself.
if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$app"
else
  echo "Note: not built on a Mac, so the app as a whole is not signed. Build it on a Mac for one that is."
fi
echo "Done: $app"
