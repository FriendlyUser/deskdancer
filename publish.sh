#!/usr/bin/env bash
# Builds a self-contained DeskDancer into dist/<runtime>. No .NET install is needed to run the result.
#   ./publish.sh              -> linux-x64
#   ./publish.sh win-x64      -> Windows build (cross-compiles fine from Linux)
set -euo pipefail
cd "$(dirname "$0")"

# Avalonia's build step sends anonymous usage data to its vendor unless this is set.
export AVALONIA_TELEMETRY_OPTOUT=1

rid="${1:-linux-x64}"
dotnet publish src/DeskDancer -c Release -r "$rid" --self-contained true \
  -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true \
  -p:DebugType=none -o "dist/$rid"
echo "Done: dist/$rid"
