param(
    [switch]$Clean,
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$AppName = "TetherLoc"

function Stop-WithMessage {
    param([string]$Message)
    Write-Host ""
    Write-Host $Message -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

function Remove-GeneratedPath {
    param([string]$Path)
    $resolvedRoot = (Resolve-Path $Root).Path
    if (-not (Test-Path $Path)) {
        return
    }
    $resolvedPath = (Resolve-Path $Path).Path
    if (-not $resolvedPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Stop-WithMessage "Refusing to remove a path outside the project: $resolvedPath"
    }
    Remove-Item -LiteralPath $resolvedPath -Recurse -Force
}

& py -3 -V *> $null
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage "Python 3.10+ is required. Install it from https://www.python.org/downloads/windows/ or Microsoft Store, then rerun this script."
}

if (-not (Test-Path $Venv)) {
    py -3 -m venv $Venv
}

if ($Clean) {
    Remove-GeneratedPath (Join-Path $Root "build")
    Remove-GeneratedPath (Join-Path $Root "dist")
    Remove-GeneratedPath (Join-Path $Root "$AppName.spec")
}

$Python = Join-Path $Venv "Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Root "requirements.txt")
& $Python -m pip install -r (Join-Path $Root "requirements-build.txt")

$mode = if ($OneFile) { "--onefile" } else { "--onedir" }
$entry = Join-Path $Root "ios_geo_spoofer\__main__.py"

$pyinstallerArgs = @(
    "-m", "PyInstaller",
    "--name", $AppName,
    "--windowed",
    $mode,
    "--clean",
    "--collect-all", "tkintermapview",
    "--collect-all", "pymobiledevice3",
    "--recursive-copy-metadata", "pymobiledevice3",
    "--copy-metadata", "readchar",
    "--copy-metadata", "inquirer3",
    $entry
)

& $Python @pyinstallerArgs

if ($OneFile) {
    Write-Host "Built: $(Join-Path $Root 'dist\TetherLoc.exe')"
} else {
    Write-Host "Built: $(Join-Path $Root 'dist\TetherLoc\TetherLoc.exe')"
}
