param(
    [switch]$Clean,
    [switch]$InstallWix,
    [switch]$DownloadInno,
    [string]$Version = "",
    [string]$Platform = "x64"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($DownloadInno) {
    Write-Host "-DownloadInno is no longer needed. TetherLoc now builds a Windows Installer MSI." -ForegroundColor Yellow
}

$argsForMsi = @()
if ($Clean) {
    $argsForMsi += "-Clean"
}
if ($InstallWix) {
    $argsForMsi += "-InstallWix"
}
if ($Version) {
    $argsForMsi += @("-Version", $Version)
}
if ($Platform) {
    $argsForMsi += @("-Platform", $Platform)
}

& (Join-Path $Root "build_msi.ps1") @argsForMsi
