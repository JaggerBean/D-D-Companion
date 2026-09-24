param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$installer = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $installer)) { $installer = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $installer)) { $installer = Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $installer)) { throw "Inno Setup 6 is required to build a release." }

Remove-Item -LiteralPath (Join-Path $projectRoot "build") -Recurse -Force -ErrorAction SilentlyContinue
& $python -m PyInstaller --noconfirm --clean --distpath (Join-Path $projectRoot "build\dist") --workpath (Join-Path $projectRoot "build\work") (Join-Path $projectRoot "installer\DNDCompanion.spec")
if ($LASTEXITCODE -ne 0) { throw "Application build failed." }

$env:DND_COMPANION_VERSION = $Version
& $installer (Join-Path $projectRoot "installer\DND-Companion.iss")
if ($LASTEXITCODE -ne 0) { throw "Installer build failed." }

Write-Host "Release installer: $(Join-Path $projectRoot "release\DND-Companion-$Version-Setup.exe")"
