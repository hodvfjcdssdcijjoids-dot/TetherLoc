from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from dataclasses import dataclass

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
RSD_OPTION_RE = re.compile(r"--rsd\s+(\S+)\s+(\d+)")
RSD_ADDRESS_RE = re.compile(r"RSD Address:\s*(\S+)", re.IGNORECASE)
RSD_PORT_RE = re.compile(r"RSD Port:\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class Device:
    identifier: str
    name: str
    product_version: str
    product_type: str
    connection_type: str

    @property
    def ios_major(self) -> int | None:
        try:
            return int(self.product_version.split(".", 1)[0])
        except (AttributeError, ValueError):
            return None

    @property
    def label(self) -> str:
        version = f"iOS {self.product_version}" if self.product_version else "iOS unknown"
        name = self.name or self.product_type or "iOS device"
        connection = self.connection_type or "USB"
        return f"{name} ({version}, {connection})"


@dataclass(frozen=True)
class TunnelInfo:
    host: str
    port: int


def clean_output(output: str | None) -> str:
    if not output:
        return ""
    output = ANSI_ESCAPE_RE.sub("", output)
    output = CONTROL_CHARACTER_RE.sub("", output)
    return output.strip()


def pmobile_args(args: list[str]) -> list[str]:
    return [sys.executable, "-m", "pymobiledevice3", *args]


def display_command(args: list[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in args)


def run_pmobile(args: list[str], timeout: float = 90, verbose: bool = False) -> subprocess.CompletedProcess[str]:
    full_args = pmobile_args(args)
    if verbose:
        print(f"Running: {display_command(full_args)}")
    try:
        result = subprocess.run(
            full_args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        output = clean_output(f"{exc.stdout or ''}{exc.stderr or ''}")
        message = output or f"Command timed out after {timeout:.0f}s: {display_command(full_args)}"
        raise RuntimeError(message) from exc
    output = clean_output(f"{result.stdout}{result.stderr}")
    if verbose and output:
        print(output)
    return subprocess.CompletedProcess(full_args, result.returncode, result.stdout, result.stderr)


def checked_run(args: list[str], timeout: float = 90, verbose: bool = False) -> str:
    result = run_pmobile(args, timeout=timeout, verbose=verbose)
    output = clean_output(f"{result.stdout}{result.stderr}")
    if result.returncode != 0:
        raise RuntimeError(output or f"Command failed: {display_command(result.args)}")
    return output


def dvt_tunnel_args(device: Device) -> list[str]:
    return ["--tunnel", device.identifier or ""]


def doctor(verbose: bool = False) -> int:
    print(f"Working folder: {os.getcwd()}")
    print(f"Python: {sys.executable}")
    for path in ("requirements.txt", "tetherloc_linux.py", "tetherloc-env/bin/activate"):
        print(f"{path}: {'OK' if os.path.exists(path) else 'missing'}")

    service = subprocess.run(
        ["bash", "-lc", "if command -v service >/dev/null 2>&1; then service usbmuxd status || true; else echo 'service command not available'; fi"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    service_output = clean_output(f"{service.stdout}{service.stderr}")
    print("usbmuxd status:")
    print(service_output or "No service output.")

    print("Testing pymobiledevice3 usbmux list...")
    try:
        output = checked_run(["usbmux", "list"], timeout=15, verbose=verbose)
        print(output or "No device output.")
    except Exception as exc:
        print(f"usbmux list failed: {clean_output(str(exc))}")
        return 1
    return 0


def extract_json_array(output: str) -> list[dict]:
    cleaned = clean_output(output)
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise RuntimeError(f"Could not parse device list: {cleaned}")
    return json.loads(cleaned[start : end + 1])


def list_devices(verbose: bool = False) -> list[Device]:
    result = checked_run(["usbmux", "list"], timeout=30, verbose=verbose)
    payload = extract_json_array(result)
    devices: list[Device] = []
    for item in payload:
        devices.append(
            Device(
                identifier=item.get("Identifier") or item.get("UniqueDeviceID") or item.get("SerialNumber") or "",
                name=item.get("DeviceName") or item.get("Name") or "",
                product_version=item.get("ProductVersion") or "",
                product_type=item.get("ProductType") or item.get("DeviceClass") or "",
                connection_type=item.get("ConnectionType") or "",
            )
        )
    return devices


def select_device(udid: str | None, verbose: bool = False) -> Device:
    devices = list_devices(verbose=verbose)
    if not devices:
        raise RuntimeError("No USB iPhone found. Plug it in, unlock it, tap Trust, then retry.")
    if udid:
        for device in devices:
            if device.identifier == udid:
                return device
        raise RuntimeError(f"No connected device matched UDID {udid}.")
    if len(devices) > 1:
        print("More than one iPhone is connected. Use --udid with one of these:")
        for device in devices:
            print(f"  {device.identifier}  {device.label}")
        raise RuntimeError("Choose a device with --udid.")
    return devices[0]


def device_args(device: Device) -> list[str]:
    return ["--udid", device.identifier] if device.identifier else []


def format_coord(value: float, low: float, high: float, label: str) -> str:
    if value < low or value > high:
        raise ValueError(f"{label} must be between {low} and {high}.")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def parse_rsd(text: str) -> TunnelInfo | None:
    option = RSD_OPTION_RE.search(text)
    if option:
        return TunnelInfo(option.group(1), int(option.group(2)))
    address = RSD_ADDRESS_RE.search(text)
    port = RSD_PORT_RE.search(text)
    if address and port:
        return TunnelInfo(address.group(1), int(port.group(1)))
    return None


def popen_pmobile(args: list[str], verbose: bool = False, stdin: bool = True) -> subprocess.Popen[str]:
    full_args = pmobile_args(args)
    if verbose:
        print(f"Running: {display_command(full_args)}")
    return subprocess.Popen(
        full_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )


def stop_process(proc: subprocess.Popen[str] | None, send_enter: bool = False) -> None:
    if proc is None or proc.poll() is not None:
        return
    if send_enter and proc.stdin:
        try:
            proc.stdin.write("\n")
            proc.stdin.flush()
            proc.wait(timeout=5)
            return
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            pass
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def mount_developer_image(device: Device, verbose: bool = False) -> None:
    checked_run(["mounter", "auto-mount", *device_args(device)], timeout=240, verbose=verbose)


def start_tunnel(device: Device, verbose: bool = False, timeout: float = 75) -> tuple[TunnelInfo, subprocess.Popen[str]]:
    commands = [
        ["lockdown", "start-tunnel", *device_args(device)],
        ["remote", "start-tunnel", *device_args(device)],
    ]
    last_output = ""
    for command in commands:
        proc = popen_pmobile(command, verbose=verbose, stdin=False)
        output_lines: list[str] = []
        deadline = time.monotonic() + timeout
        selector = selectors.DefaultSelector()
        try:
            if proc.stdout is None:
                break
            selector.register(proc.stdout, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                if proc.poll() is not None and not selector.select(timeout=0):
                    break
                remaining = max(0.05, deadline - time.monotonic())
                events = selector.select(timeout=min(0.25, remaining))
                if not events:
                    continue
                line = proc.stdout.readline()
                if not line:
                    continue
                cleaned = clean_output(line)
                if cleaned:
                    output_lines.append(cleaned)
                    if verbose:
                        print(cleaned)
                    info = parse_rsd("\n".join(output_lines))
                    if info:
                        return info, proc
        finally:
            selector.close()
        last_output = "\n".join(output_lines)
        stop_process(proc)
    raise RuntimeError(last_output or "Tunnel did not publish RSD connection details.")


def start_tunneld(verbose: bool = False) -> subprocess.Popen[str]:
    proc = popen_pmobile(["remote", "tunneld"], verbose=verbose, stdin=False)
    time.sleep(4.0)
    if proc.poll() is not None:
        output = proc.stdout.read() if proc.stdout else ""
        raise RuntimeError(clean_output(output) or "tunneld exited before it was ready.")
    if verbose:
        print("tunneld is running.")
    return proc


def clear_location(device: Device, verbose: bool = False) -> None:
    major = device.ios_major
    if major is not None and major >= 17:
        mount_developer_image(device, verbose=verbose)
        tunneld_proc: subprocess.Popen[str] | None = None
        try:
            tunneld_proc = start_tunneld(verbose=verbose)
            checked_run(
                ["developer", "dvt", "simulate-location", "clear", *dvt_tunnel_args(device)],
                timeout=90,
                verbose=verbose,
            )
            return
        except Exception as exc:
            if verbose:
                print(f"tunneld clear failed: {clean_output(str(exc))}")
                print("Trying manual tunnel fallback.")
        finally:
            stop_process(tunneld_proc)

        tunnel_proc: subprocess.Popen[str] | None = None
        try:
            tunnel, tunnel_proc = start_tunnel(device, verbose=verbose)
            checked_run(
                ["developer", "dvt", "simulate-location", "clear", "--rsd", tunnel.host, str(tunnel.port)],
                timeout=90,
                verbose=verbose,
            )
        finally:
            stop_process(tunnel_proc)
        return

    checked_run(["developer", "simulate-location", "clear", *device_args(device)], timeout=90, verbose=verbose)


def set_location(device: Device, latitude: float, longitude: float, verbose: bool = False) -> None:
    lat = format_coord(latitude, -90, 90, "Latitude")
    lon = format_coord(longitude, -180, 180, "Longitude")
    major = device.ios_major
    if major is not None and major >= 17:
        mount_developer_image(device, verbose=verbose)
        tunneld_proc: subprocess.Popen[str] | None = None
        tunnel_proc: subprocess.Popen[str] | None = None
        hold_proc: subprocess.Popen[str] | None = None
        tunnel: TunnelInfo | None = None
        stopping = False

        def request_stop(_signum: int, _frame: object) -> None:
            nonlocal stopping
            stopping = True

        old_sigint = signal.signal(signal.SIGINT, request_stop)
        old_sigterm = signal.signal(signal.SIGTERM, request_stop)
        try:
            tunneld_proc = start_tunneld(verbose=verbose)
            hold_proc = popen_pmobile(
                [
                    "developer",
                    "dvt",
                    "simulate-location",
                    "set",
                    *dvt_tunnel_args(device),
                    "--",
                    lat,
                    lon,
                ],
                verbose=verbose,
                stdin=True,
            )
            time.sleep(2.5)
            if hold_proc.poll() is not None:
                output = hold_proc.stdout.read() if hold_proc.stdout else ""
                stop_process(hold_proc, send_enter=True)
                hold_proc = None
                stop_process(tunneld_proc)
                tunneld_proc = None
                if verbose:
                    print(clean_output(output) or "tunneld set exited; trying manual tunnel fallback.")
                tunnel, tunnel_proc = start_tunnel(device, verbose=verbose, timeout=30)
                hold_proc = popen_pmobile(
                    [
                        "developer",
                        "dvt",
                        "simulate-location",
                        "set",
                        "--rsd",
                        tunnel.host,
                        str(tunnel.port),
                        "--",
                        lat,
                        lon,
                    ],
                    verbose=verbose,
                    stdin=True,
                )
                time.sleep(2.5)

            if hold_proc.poll() is not None:
                output = hold_proc.stdout.read() if hold_proc.stdout else ""
                raise RuntimeError(clean_output(output) or "Location command exited before holding the location.")
            print(f"Location active at {lat}, {lon}. Press Ctrl+C to clear and exit.")
            while not stopping:
                time.sleep(0.2)
            print("\nClearing location...")
            stop_process(hold_proc, send_enter=True)
            hold_proc = None
            clear_args = [
                "developer",
                "dvt",
                "simulate-location",
                "clear",
            ]
            if tunnel is None:
                clear_args.extend(dvt_tunnel_args(device))
            else:
                clear_args.extend(["--rsd", tunnel.host, str(tunnel.port)])
            checked_run(clear_args, timeout=90, verbose=verbose)
            print("Location cleared.")
        finally:
            signal.signal(signal.SIGINT, old_sigint)
            signal.signal(signal.SIGTERM, old_sigterm)
            stop_process(hold_proc, send_enter=True)
            stop_process(tunnel_proc)
            stop_process(tunneld_proc)
        return

    checked_run(
        ["developer", "simulate-location", "set", *device_args(device), "--", lat, lon],
        timeout=90,
        verbose=verbose,
    )
    print(f"Location sent: {lat}, {lon}")


def prompt_developer_mode(device: Device, verbose: bool = False) -> None:
    status = run_pmobile(["amfi", "developer-mode-status", *device_args(device)], timeout=90, verbose=verbose)
    status_output = clean_output(f"{status.stdout}{status.stderr}").lower()
    if status.returncode == 0 and ("true" in status_output or "enabled" in status_output):
        print("Developer Mode is already enabled.")
        return
    run_pmobile(["amfi", "reveal-developer-mode", *device_args(device)], timeout=90, verbose=verbose)
    result = run_pmobile(["amfi", "enable-developer-mode", *device_args(device)], timeout=180, verbose=verbose)
    output = clean_output(f"{result.stdout}{result.stderr}")
    if result.returncode != 0:
        raise RuntimeError(output or "Developer Mode prompt failed.")
    print("Developer Mode prompt sent. Check the iPhone.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tiny USB-only iOS location CLI for Linux/Penguin.")
    parser.add_argument("--udid", help="Target a specific connected iPhone UDID.")
    parser.add_argument("--verbose", action="store_true", help="Show pymobiledevice3 output.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check folder, usbmuxd, and iPhone visibility.")
    subparsers.add_parser("devices", help="List connected USB iPhones.")
    subparsers.add_parser("devmode", help="Prompt/reveal Developer Mode.")
    subparsers.add_parser("mount", help="Mount the DeveloperDiskImage.")
    subparsers.add_parser("clear", help="Clear simulated location.")
    set_parser = subparsers.add_parser("set", help="Set and hold a simulated location.")
    set_parser.add_argument("latitude", type=float)
    set_parser.add_argument("longitude", type=float)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "devices":
            devices = list_devices(verbose=args.verbose)
            if not devices:
                print("No USB iPhone found.")
                return 1
            for device in devices:
                print(f"{device.identifier}\t{device.label}")
            return 0
        if args.command == "doctor":
            return doctor(verbose=args.verbose)

        device = select_device(args.udid, verbose=args.verbose)
        if args.command in {"set", "clear"} and device.ios_major is not None and device.ios_major >= 17 and os.geteuid() != 0:
            raise RuntimeError("iOS 17+ location commands need root on Linux. Rerun with: sudo bash run.sh " + args.command)
        if args.command == "devmode":
            prompt_developer_mode(device, verbose=args.verbose)
        elif args.command == "mount":
            mount_developer_image(device, verbose=args.verbose)
            print("Developer image mounted.")
        elif args.command == "set":
            set_location(device, args.latitude, args.longitude, verbose=args.verbose)
        elif args.command == "clear":
            clear_location(device, verbose=args.verbose)
            print("Location cleared.")
        return 0
    except Exception as exc:
        print(f"Error: {clean_output(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
