param(
  [string]$Version = "2.4.0",
  [string]$OutDir = "dist",
  [switch]$SkipSign
)
$ErrorActionPreference = "Stop"
python -m pip install -e .[build]
pyinstaller --noconfirm --clean --name "NPCreateStudio" --windowed --onedir "src/npcreate_studio/__main__.py"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Compress-Archive -Path "dist/NPCreateStudio/*" -DestinationPath "$OutDir/NPCreateStudio-$Version-portable.zip" -Force
if (-not $SkipSign) {
  ./scripts/sign_windows_artifacts.ps1 -Path "$OutDir/NPCreateStudio-$Version-portable.zip"
}
Write-Host "Build completed: $OutDir/NPCreateStudio-$Version-portable.zip"
