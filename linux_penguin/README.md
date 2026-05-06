# TetherLoc Linux / Penguin CLI

This is a tiny USB-only Linux version for Chromebook Penguin or normal Linux. It does not include the Windows map UI, roadtrip, flight mode, installer, or Apple driver checks.

It can:

- list connected iPhones
- prompt Developer Mode
- mount the DeveloperDiskImage
- set a latitude/longitude
- clear the simulated location

## Install

Copy this whole `linux_penguin` folder to the Chromebook/Linux machine.

In Penguin, open Terminal in this folder and run:

```bash
bash install.sh
```

Plug in the iPhone, unlock it, tap **Trust This Computer**, and let ChromeOS connect the USB device to Linux if it asks.

## Use

List devices:

```bash
bash run.sh devices
```

Prompt Developer Mode:

```bash
bash run.sh devmode
```

Mount developer image:

```bash
bash run.sh mount
```

Set a simulated location:

```bash
bash run.sh set 37.3349 -122.0090
```

On iOS 17 and newer, keep that terminal open while the simulated location is active. Press `Ctrl+C` to clear and exit.

Clear manually:

```bash
bash run.sh clear
```

If more than one phone is connected, use:

```bash
bash run.sh --udid YOUR_UDID set 37.3349 -122.0090
```

For command output while debugging:

```bash
bash run.sh --verbose devices
```

## If USB Stops Working

Restart usbmuxd:

```bash
sudo service usbmuxd restart
```

Then unplug/replug the iPhone, unlock it, trust the computer, reconnect it to Linux from ChromeOS if prompted, and run:

```bash
bash run.sh devices
```
