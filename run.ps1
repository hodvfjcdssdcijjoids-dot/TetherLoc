$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"

function Stop-WithMessage {
    param([string]$Message)
    Write-Host ""
    Write-Host $Message -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

try {
    & py -3 -V *> $null
    if ($LASTEXITCODE -ne 0) {
        Stop-WithMessage "Python 3.10+ is required. Install it from https://www.python.org/downloads/windows/ or Microsoft Store, then rerun this script."
    }

    if (-not (Test-Path $Venv)) {
        py -3 -m venv $Venv
    }

    $Python = Join-Path $Venv "Scripts\python.exe"
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r (Join-Path $Root "requirements.txt")
    & $Python -m ios_geo_spoofer
}
catch {
    Stop-WithMessage $_.Exception.Message
}
