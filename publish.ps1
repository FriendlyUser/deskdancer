# Builds a self-contained DeskDancer into dist\<runtime>. No .NET install is needed to run the result.
#   .\publish.ps1              -> win-x64
#   .\publish.ps1 linux-x64    -> Linux build
param([string]$Runtime = "win-x64")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Avalonia's build step sends anonymous usage data to its vendor unless this is set.
$env:AVALONIA_TELEMETRY_OPTOUT = "1"

dotnet publish src/DeskDancer -c Release -r $Runtime --self-contained true `
  -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true `
  -p:DebugType=none -o "dist/$Runtime"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Done: dist\$Runtime"
