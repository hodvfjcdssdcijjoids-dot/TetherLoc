param(
    [switch]$Clean,
    [switch]$InstallWix,
    [string]$Version = "",
    [string]$Platform = "x64"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppName = "TetherLoc"
$Manufacturer = "TetherLoc"
$UpgradeCode = "C16D1F65-D76C-40C8-94A0-31212E9F735F"

function Stop-WithMessage {
    param([string]$Message)
    Write-Host ""
    Write-Host $Message -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

function Get-ProjectVersion {
    $match = Select-String -Path (Join-Path $Root "pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($match) {
        return $match.Matches[0].Groups[1].Value
    }
    return "0.1.0"
}

function Find-Wix {
    $command = Get-Command "wix.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @()
    if ($env:USERPROFILE) {
        $candidates += (Join-Path $env:USERPROFILE ".dotnet\tools\wix.exe")
    }
    if ($env:ProgramFiles) {
        $candidates += (Join-Path $env:ProgramFiles "WiX Toolset v5.0\bin\wix.exe")
        $candidates += (Join-Path $env:ProgramFiles "WiX Toolset v4.0\bin\wix.exe")
    }
    if (${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} "WiX Toolset v4.0\bin\wix.exe")
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    return $null
}

function Install-WixCli {
    $dotnet = Get-Command "dotnet.exe" -ErrorAction SilentlyContinue
    if (-not $dotnet) {
        Stop-WithMessage "WiX was not found and dotnet was not found. Install WiX Toolset with winget install WiXToolset.WiXToolset, then rerun this script."
    }

    Write-Host "Installing WiX Toolset CLI..."
    & $dotnet.Source tool install --global wix
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WiX install did not complete. Trying update in case it is already installed..."
        & $dotnet.Source tool update --global wix
    }
}

function ConvertTo-WixId {
    param(
        [string]$Prefix,
        [string]$Value
    )

    $sha1 = [System.Security.Cryptography.SHA1]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value.ToLowerInvariant())
        $hash = $sha1.ComputeHash($bytes)
        $hex = -join ($hash[0..9] | ForEach-Object { $_.ToString("x2") })
        return "$Prefix$hex"
    }
    finally {
        $sha1.Dispose()
    }
}

function ConvertTo-XmlText {
    param([string]$Value)
    return [System.Security.SecurityElement]::Escape($Value)
}

function Get-RelativePath {
    param(
        [string]$BasePath,
        [string]$Path
    )

    $base = [System.IO.Path]::GetFullPath($BasePath).TrimEnd("\", "/")
    $full = [System.IO.Path]::GetFullPath($Path).TrimEnd("\", "/")
    if ($full.Equals($base, [System.StringComparison]::OrdinalIgnoreCase)) {
        return ""
    }
    return $full.Substring($base.Length + 1)
}

function Add-AppDirectoryXml {
    param(
        [System.Text.StringBuilder]$Builder,
        [System.Collections.Generic.List[string]]$ComponentRefs,
        [string]$DistRoot,
        [string]$DirectoryPath,
        [int]$Indent
    )

    $prefix = " " * $Indent
    $files = Get-ChildItem -LiteralPath $DirectoryPath -File | Sort-Object Name
    foreach ($file in $files) {
        $relative = Get-RelativePath -BasePath $DistRoot -Path $file.FullName
        $componentId = ConvertTo-WixId -Prefix "Cmp" -Value $relative
        $fileId = ConvertTo-WixId -Prefix "Fil" -Value $relative
        $source = ConvertTo-XmlText $file.FullName
        $name = ConvertTo-XmlText $file.Name

        [void]$Builder.AppendLine("$prefix<Component Id=`"$componentId`" Guid=`"*`">")
        [void]$Builder.AppendLine("$prefix  <File Id=`"$fileId`" Source=`"$source`" Name=`"$name`" KeyPath=`"yes`" />")
        [void]$Builder.AppendLine("$prefix</Component>")
        $ComponentRefs.Add($componentId)
    }

    $directories = Get-ChildItem -LiteralPath $DirectoryPath -Directory | Sort-Object Name
    foreach ($directory in $directories) {
        $relative = Get-RelativePath -BasePath $DistRoot -Path $directory.FullName
        $directoryId = ConvertTo-WixId -Prefix "Dir" -Value $relative
        $name = ConvertTo-XmlText $directory.Name

        [void]$Builder.AppendLine("$prefix<Directory Id=`"$directoryId`" Name=`"$name`">")
        Add-AppDirectoryXml -Builder $Builder -ComponentRefs $ComponentRefs -DistRoot $DistRoot -DirectoryPath $directory.FullName -Indent ($Indent + 2)
        [void]$Builder.AppendLine("$prefix</Directory>")
    }
}

function New-WixSource {
    param(
        [string]$DistRoot,
        [string]$OutputPath,
        [string]$Version
    )

    $componentRefs = [System.Collections.Generic.List[string]]::new()
    $appTree = [System.Text.StringBuilder]::new()
    Add-AppDirectoryXml -Builder $appTree -ComponentRefs $componentRefs -DistRoot $DistRoot -DirectoryPath $DistRoot -Indent 10

    $escapedAppName = ConvertTo-XmlText $AppName
    $escapedManufacturer = ConvertTo-XmlText $Manufacturer
    $escapedVersion = ConvertTo-XmlText $Version

    $featureRefs = [System.Text.StringBuilder]::new()
    foreach ($componentId in $componentRefs) {
        [void]$featureRefs.AppendLine("      <ComponentRef Id=`"$componentId`" />")
    }

    $xml = @"
<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">
  <Package Name="$escapedAppName" Manufacturer="$escapedManufacturer" Version="$escapedVersion" UpgradeCode="$UpgradeCode" Scope="perUser" Compressed="yes">
    <MajorUpgrade DowngradeErrorMessage="A newer version of $escapedAppName is already installed." />
    <MediaTemplate EmbedCab="yes" />

    <StandardDirectory Id="LocalAppDataFolder">
      <Directory Id="INSTALLFOLDER" Name="$escapedAppName">
$($appTree.ToString().TrimEnd())
      </Directory>
    </StandardDirectory>

    <StandardDirectory Id="ProgramMenuFolder">
      <Directory Id="ApplicationProgramsFolder" Name="$escapedAppName">
        <Component Id="CmpStartMenuShortcut" Guid="*">
          <Shortcut Id="StartMenuShortcut" Name="$escapedAppName" Description="Launch $escapedAppName" Target="[INSTALLFOLDER]TetherLoc.exe" WorkingDirectory="INSTALLFOLDER" />
          <RemoveFolder Id="RemoveApplicationProgramsFolder" On="uninstall" />
          <RegistryValue Root="HKCU" Key="Software\$escapedAppName" Name="StartMenuShortcut" Type="integer" Value="1" KeyPath="yes" />
        </Component>
      </Directory>
    </StandardDirectory>

    <StandardDirectory Id="DesktopFolder">
      <Component Id="CmpDesktopShortcut" Guid="*">
        <Shortcut Id="DesktopShortcut" Name="$escapedAppName" Description="Launch $escapedAppName" Target="[INSTALLFOLDER]TetherLoc.exe" WorkingDirectory="INSTALLFOLDER" />
        <RegistryValue Root="HKCU" Key="Software\$escapedAppName" Name="DesktopShortcut" Type="integer" Value="1" KeyPath="yes" />
      </Component>
    </StandardDirectory>

    <Feature Id="MainFeature" Title="$escapedAppName" Level="1">
$($featureRefs.ToString().TrimEnd())
      <ComponentRef Id="CmpStartMenuShortcut" />
      <ComponentRef Id="CmpDesktopShortcut" />
    </Feature>
  </Package>
</Wix>
"@

    Set-Content -LiteralPath $OutputPath -Value $xml -Encoding UTF8
}

if (-not $Version) {
    $Version = Get-ProjectVersion
}

& (Join-Path $Root "build_windows.ps1") -Clean:$Clean

$wix = Find-Wix
if (-not $wix -and $InstallWix) {
    Install-WixCli
    $wix = Find-Wix
}

if (-not $wix) {
    Stop-WithMessage "WiX Toolset CLI was not found. Install it with winget install WiXToolset.WiXToolset, or rerun with -InstallWix if you have the .NET SDK."
}

$distRoot = Join-Path $Root "dist\TetherLoc"
if (-not (Test-Path (Join-Path $distRoot "TetherLoc.exe"))) {
    Stop-WithMessage "The app build was not found at dist\TetherLoc\TetherLoc.exe."
}

$installerBuildDir = Join-Path $Root "build\installer"
$releaseDir = Join-Path $Root "release"
New-Item -ItemType Directory -Force -Path $installerBuildDir | Out-Null
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

$wxsPath = Join-Path $installerBuildDir "TetherLoc.Generated.wxs"
$msiPath = Join-Path $releaseDir "TetherLoc-$Version.msi"

New-WixSource -DistRoot $distRoot -OutputPath $wxsPath -Version $Version

& $wix build $wxsPath -arch $Platform -out $msiPath
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage "WiX failed to build the MSI."
}

Write-Host "Windows Installer built: $msiPath"
