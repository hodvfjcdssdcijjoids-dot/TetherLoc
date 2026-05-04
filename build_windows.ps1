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

function Stop-GeneratedAppProcesses {
    $processes = @(Get-Process -Name $AppName -ErrorAction SilentlyContinue)
    if ($processes.Count -eq 0) {
        return
    }

    foreach ($process in $processes) {
        Write-Host "Stopping running $AppName process $($process.Id) so build files can be replaced..."
        try {
            Stop-Process -Id $process.Id -Force -ErrorAction Stop
            Wait-Process -Id $process.Id -Timeout 5 -ErrorAction SilentlyContinue
        } catch {
            Stop-WithMessage "Could not stop $AppName process $($process.Id). Close TetherLoc from Task Manager, then rerun the build."
        }
    }
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

    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            Remove-Item -LiteralPath $resolvedPath -Recurse -Force -ErrorAction Stop
            return
        } catch {
            if ($attempt -eq 5) {
                Stop-WithMessage "Could not remove generated build files at $resolvedPath. Close TetherLoc, close any Explorer windows opened inside dist/build, then rerun the build."
            }
            Start-Sleep -Milliseconds 700
        }
    }
}

function Invoke-CommandParts {
    param(
        [Parameter(Mandatory = $true)][string[]]$CommandParts,
        [string[]]$Arguments = @()
    )
    $exe = $CommandParts[0]
    $baseArgs = @()
    if ($CommandParts.Count -gt 1) {
        $baseArgs = $CommandParts[1..($CommandParts.Count - 1)]
    }
    & $exe @baseArgs @Arguments
}

function Test-PythonCommand {
    param([Parameter(Mandatory = $true)][string[]]$CommandParts)

    try {
        $output = Invoke-CommandParts $CommandParts @("-c", "import sys; print(sys.version_info >= (3, 10))") 2>$null
        return ($LASTEXITCODE -eq 0 -and (($output -join "") -match "True"))
    } catch {
        return $false
    }
}

function Find-BootstrapPython {
    param([switch]$SkipVenv)

    $venvPython = Join-Path $Venv "Scripts\python.exe"
    if (-not $SkipVenv -and (Test-Path $venvPython) -and (Test-PythonCommand @($venvPython))) {
        return @($venvPython)
    }

    $candidates = @()
    $venvConfig = Join-Path $Venv "pyvenv.cfg"
    if (Test-Path $venvConfig) {
        $configuredPython = Get-Content $venvConfig |
            Where-Object { $_ -match "^executable\s*=\s*(.+)$" } |
            ForEach-Object { $Matches[1].Trim() } |
            Select-Object -First 1

        if ($configuredPython -and (Test-Path $configuredPython)) {
            $candidates += ,@($configuredPython)
        }
    }

    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        $candidates += ,@("py", "-3")
    }
    if (Get-Command python.exe -ErrorAction SilentlyContinue) {
        $candidates += ,@("python")
    }
    if (Get-Command python3.exe -ErrorAction SilentlyContinue) {
        $candidates += ,@("python3")
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonCommand $candidate) {
            return $candidate
        }
    }

    return $null
}

if (-not (Test-Path $Venv)) {
    $BootstrapPython = Find-BootstrapPython
    if ($null -eq $BootstrapPython) {
        Stop-WithMessage "Python 3.10+ is required. Install it from https://www.python.org/downloads/windows/, then rerun this script."
    }
    Invoke-CommandParts $BootstrapPython @("-m", "venv", $Venv)
}

$Python = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $BootstrapPython = Find-BootstrapPython
    if ($null -eq $BootstrapPython) {
        Stop-WithMessage "Python 3.10+ is required. Install it from https://www.python.org/downloads/windows/, then rerun this script."
    }
    Invoke-CommandParts $BootstrapPython @("-m", "venv", $Venv)
}

if (-not (Test-PythonCommand @($Python))) {
    $BootstrapPython = Find-BootstrapPython -SkipVenv
    if ($null -eq $BootstrapPython) {
        Stop-WithMessage "The project virtual environment is not working, and no separate Python 3.10+ install was found to rebuild it. Install Python from https://www.python.org/downloads/windows/, then rerun this script."
    }

    Write-Host "Recreating the project Python environment..."
    Remove-GeneratedPath $Venv
    Invoke-CommandParts $BootstrapPython @("-m", "venv", $Venv)

    if (-not (Test-PythonCommand @($Python))) {
        Stop-WithMessage "The project virtual environment still is not working after rebuilding it. Reinstall Python from https://www.python.org/downloads/windows/, then rerun this script."
    }
}

if ($Clean) {
    Stop-GeneratedAppProcesses
    Remove-GeneratedPath (Join-Path $Root "build")
    Remove-GeneratedPath (Join-Path $Root "dist")
    Remove-GeneratedPath (Join-Path $Root "$AppName.spec")
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Root "requirements.txt")
& $Python -m pip install -r (Join-Path $Root "requirements-build.txt")

$mode = if ($OneFile) { "--onefile" } else { "--onedir" }
$entry = Join-Path $Root "ios_geo_spoofer\__main__.py"
$wintunBin = Join-Path $Venv "Lib\site-packages\pytun_pmd3\wintun\bin"
$wintunDlls = @()
if (Test-Path $wintunBin) {
    $wintunDlls = @(Get-ChildItem -Path $wintunBin -Recurse -Filter "wintun.dll")
}
if ($wintunDlls.Count -eq 0) {
    Stop-WithMessage "Could not find pytun_pmd3's wintun.dll files in the virtual environment. Rerun this script after the dependency install finishes, or recreate .venv."
}

$pyinstallerArgs = @(
    "-m", "PyInstaller",
    "--name", $AppName,
    "--windowed",
    $mode,
    "--clean",
    "--collect-all", "tkintermapview",
    "--collect-all", "pymobiledevice3",
    "--collect-all", "pytun_pmd3",
    "--recursive-copy-metadata", "pymobiledevice3",
    "--copy-metadata", "readchar",
    "--copy-metadata", "inquirer3"
)

foreach ($dll in $wintunDlls) {
    $architecture = $dll.Directory.Name
    $destination = "pytun_pmd3\wintun\bin\$architecture"
    $pyinstallerArgs += @("--add-binary", "$($dll.FullName);$destination")
}

$pyinstallerArgs += $entry

& $Python @pyinstallerArgs

if ($OneFile) {
    Write-Host "Built: $(Join-Path $Root 'dist\TetherLoc.exe')"
} else {
    $builtApp = Join-Path $Root "dist\TetherLoc\TetherLoc.exe"
    $builtWintun = Join-Path $Root "dist\TetherLoc\_internal\pytun_pmd3\wintun\bin\amd64\wintun.dll"
    if (-not (Test-Path $builtWintun)) {
        Stop-WithMessage "The EXE was built, but wintun.dll was not bundled at $builtWintun. Delete dist/build and rerun this script from the updated project folder."
    }
    Write-Host "Built: $builtApp"
    Write-Host "Bundled: $builtWintun"
}
