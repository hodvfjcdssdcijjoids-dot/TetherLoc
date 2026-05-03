param(
    [string]$RepoName = "TetherLoc",
    [switch]$Public
)

$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Stop-WithMessage {
    param([string]$Message)
    Write-Host ""
    Write-Host $Message -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

function Find-Gh {
    $command = Get-Command "gh.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidate = Join-Path $env:ProgramFiles "GitHub CLI\gh.exe"
    if (Test-Path $candidate) {
        return $candidate
    }

    return $null
}

Set-Location $Root

$gh = Find-Gh
if (-not $gh) {
    Stop-WithMessage "GitHub CLI was not found. Install it with: winget install GitHub.cli"
}

& git --version *> $null
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage "Git was not found. Install Git for Windows, then rerun this script."
}

$safeRoot = (Resolve-Path $Root).Path.Replace("\", "/")
$safeDirectories = @(& git config --global --get-all safe.directory 2>$null)
if ($safeDirectories -notcontains $safeRoot) {
    & git config --global --add safe.directory $safeRoot
}

& $gh auth status
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage "GitHub CLI is not logged in. Run: gh auth login"
}

$login = (& $gh api user --jq ".login").Trim()
$id = (& $gh api user --jq ".id").Trim()
if (-not $login -or -not $id) {
    Stop-WithMessage "Could not read your GitHub account from gh."
}

if (-not (Test-Path (Join-Path $Root ".git"))) {
    & git init -b main
}

& git branch --show-current *> $null
if ($LASTEXITCODE -ne 0) {
    & git checkout -B main
}

& git config --local user.name $login
& git config --local user.email "$id+$login@users.noreply.github.com"

$sourcePaths = @(
    ".gitignore",
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements-build.txt",
    "run.ps1",
    "publish_to_github.ps1",
    "build_windows.ps1",
    "build_installer.ps1",
    "build_msi.ps1",
    "ios_geo_spoofer",
    "tests"
)

& git add -- $sourcePaths
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    & git rev-parse --verify HEAD *> $null
    $commitMessage = if ($LASTEXITCODE -eq 0) { "Update TetherLoc source" } else { "Initial TetherLoc app" }
    & git commit -m $commitMessage
}
else {
    Write-Host "No source changes to commit."
}

$repoFullName = "$login/$RepoName"
$remoteUrl = "https://github.com/$repoFullName.git"
$remotes = @(& git remote)
if ($remotes -contains "origin") {
    & git remote set-url origin $remoteUrl
}
else {
    $visibility = if ($Public) { "--public" } else { "--private" }
    & $gh repo create $repoFullName $visibility --source $Root --remote origin
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Repo creation did not complete. If the repo already exists, adding it as origin..." -ForegroundColor Yellow
        & git remote add origin $remoteUrl
    }
}

& git push -u origin main

Write-Host ""
Write-Host "Uploaded: https://github.com/$repoFullName" -ForegroundColor Green
