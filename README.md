# TetherLoc

> **Administrator required:** Run TetherLoc from an Administrator PowerShell window. iOS 17+ developer tunneling may fail without elevated access, and the app will stop at an admin-required screen if it is launched normally.

TetherLoc is a small Windows-friendly desktop wrapper for iOS location simulation on your own connected iPhone or iPad. It uses Apple Mobile Device Support from iTunes for USB pairing/discovery and delegates device communication to `pymobiledevice3`.

## What It Does

- Lists USB-connected iOS devices.
- Starts with a setup gate that checks Apple drivers, required Python tools, and a trusted USB iPhone before opening the main map.
- Shows a waiting screen with install/connect steps and an Apple download link when the phone or drivers are missing.
- Lets you click an OpenStreetMap map to choose a destination.
- Checks whether the Apple Mobile Device service is available.
- Runs `pymobiledevice3` setup actions for Developer Mode and DeveloperDiskImage mounting.
- For iOS 17 and newer, starts the required RSD tunnel and keeps the location simulation process alive.
- Sets or clears a simulated latitude/longitude.
- Builds road-following GPX routes from the selected start to the clicked destination, with custom fallback MPH and smoothness interval.
- Can estimate per-road speeds from the router, pause at matched OpenStreetMap stop signs, and stop active roadtrip playback without closing the tunnel.
- Adds a **Misc** tab with Flight Mode: choose two airports, board, taxi to the runway, fly a timed route, approach, and taxi to the destination gate.
- Lets you choose **Automatic** route speed or a fixed **Set MPH** mode before starting a roadtrip.
- Shows roadtrip speed, ETA, distance, and stop count directly in the Roadtrip panel after planning.
- Uses a dark-mode interface and dark map tiles, with a separately scrollable side menu.
- Includes a pause helper that shows the on-phone Developer Mode/unplug steps for holding the current spot.

## Requirements

- Windows 10/11.
- Apple Devices or iTunes from Microsoft Store/Apple so Apple Mobile Device Support is installed.
- A USB-connected iPhone/iPad that has trusted this computer.
- Developer Mode enabled on the iOS device for developer-location services.
- Internet access for map tiles and road routing.

If TetherLoc says the Apple drivers are missing, install one of Apple's Windows options:

- Apple Devices for Windows: https://support.apple.com/guide/devices-windows/install-the-apple-devices-app-mchl5ded2763/windows
- Apple Windows download page for Apple Devices and iTunes: https://support.apple.com/en-us/118290

After installing, unplug and reconnect the iPhone, unlock it, tap **Trust This Computer**, then rerun the setup check.

When using the source checkout directly, Python 3.10 or newer is also required. When using the packaged installer, Python is bundled into the app build and does not need to be installed by the end user.

For iOS 17 and newer, run the app from an Administrator PowerShell window because the tunnel setup may need elevated network driver access.
If TetherLoc is opened without Administrator rights, it will stop at an admin-required screen and show the exact PowerShell command to rerun.

## Run

Open PowerShell in this folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

The first run creates a local `.venv`, installs `pymobiledevice3`, and launches the app.

Use the command above if PowerShell says `run.ps1 cannot be loaded because running scripts is disabled on this system`. The bypass only applies to that one launch.

## Build An EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

The app build will be created at `dist\TetherLoc\TetherLoc.exe`.

Use this if you just want a local executable folder without a setup wizard.

## Build A Downloadable Installer

Builder requirements:

- Windows 10/11.
- Python 3.10 or newer.
- Internet access while building, so Python packages can be downloaded.
- WiX Toolset CLI, used only on the build PC to create a Windows Installer `.msi`.

Build the installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1 -Clean
```

If WiX is not installed yet and you have the .NET SDK, the script can try to install the WiX CLI:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1 -Clean -InstallWix
```

You can also install WiX manually first:

```powershell
winget install WiXToolset.WiXToolset
```

The finished Windows Installer package will be created in `release`, for example:

```text
release\TetherLoc-0.1.0.msi
```

That `.msi` is the file you can upload to a website or release page. A user downloads it, opens it with Windows Installer, and gets Start Menu/Desktop shortcuts for TetherLoc. They still need Apple Mobile Device Support and a trusted iPhone because those are device-driver requirements, not Python app files.

## Notes

- This is intended for owned-device app testing and QA. Some apps and services forbid simulated locations in their terms.
- iOS 17+ location simulation often stays active only while the underlying developer tool connection stays open. Keep TetherLoc running until you press **Clear Location**.
- Roadtrip uses the public OSRM routing service, OpenStreetMap map tiles, and optional Overpass stop-sign lookup. Lower **Smooth sec** values generate denser playback points for smoother movement.
- **Automatic** speed uses router speed estimates, not official posted speed-limit signs. **Stop signs** depend on OpenStreetMap data and may miss or over-match some intersections.
- Flight Mode uses built-in airport coordinates and creates simulated GPX movement for boarding, taxi, takeoff, cruise, approach, and arrival taxi. It does not use live flight paths or official ATC routes.
- If the phone stays on a simulated location after disconnecting, reconnect it and press **Clear Location**, or toggle Location Services on the phone.

## Related Projects

- `pymobiledevice3`: the maintained Python iOS communication toolkit this app wraps.
- iFakeLocation: earlier cross-platform location simulation app using the iTunes/Apple Mobile Device path.
- GeoPort: open-source Python-based iOS location simulation app that also uses `pymobiledevice3`.
