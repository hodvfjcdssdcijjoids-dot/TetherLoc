from __future__ import annotations

import json
import os
import platform
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

if platform.system() == "Windows":
    import ctypes


LogSink = Callable[[str], None]

RSD_OPTION_RE = re.compile(r"--rsd\s+([^\s]+)\s+(\d+)")
RSD_ADDRESS_RE = re.compile(r"RSD Address:\s*([^\s]+)")
RSD_PORT_RE = re.compile(r"RSD Port:\s*(\d+)")
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
DEVELOPER_SERVICE_MARKERS = (
    "failed to start service",
    "developer mode",
    "developermode",
    "developerdiskimage",
    "personalizedimage",
    "mounter auto-mount",
    "pass the --rsd",
    "com.apple.instruments",
)
DEVELOPER_IMAGE_MOUNT_FAILURE_MARKERS = (
    "unable to find the correct developerdiskimage",
    "failed to query developerdiskimage versions",
    "developerdiskimage could not be saved",
)


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    returncode: int
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class Device:
    identifier: str
    name: str
    product_version: str
    product_type: str
    connection_type: str
    raw: dict

    @property
    def ios_major(self) -> int | None:
        try:
            return int(self.product_version.split(".", 1)[0])
        except (ValueError, AttributeError):
            return None

    @property
    def display_name(self) -> str:
        version = f"iOS {self.product_version}" if self.product_version else "iOS unknown"
        conn = self.connection_type or "unknown connection"
        name = self.name or self.product_type or "iOS device"
        return f"{name} ({version}, {conn})"


@dataclass(frozen=True)
class TunnelInfo:
    host: str
    port: int


class ManagedProcess:
    """A long-running pymobiledevice3 process with streaming output."""

    def __init__(self, proc: subprocess.Popen[str], args: list[str], emit: LogSink | None = None):
        self.proc = proc
        self.args = args
        self._emit = emit
        self._lines: list[str] = []
        self._queue: queue.Queue[str] = queue.Queue()
        self._reader = threading.Thread(target=self._read_stdout, name="pymobiledevice3-reader", daemon=True)
        self._reader.start()

    @property
    def lines(self) -> list[str]:
        return list(self._lines)

    @property
    def output(self) -> str:
        return clean_command_output("".join(self._lines))

    @property
    def is_running(self) -> bool:
        return self.proc.poll() is None

    def wait_for_line(self, matcher: Callable[[str], bool], timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        for line in self._lines:
            if matcher(line):
                return line
        while time.monotonic() < deadline:
            if not self.is_running and self._queue.empty():
                return None
            remaining = max(0.05, deadline - time.monotonic())
            try:
                line = self._queue.get(timeout=min(0.25, remaining))
            except queue.Empty:
                continue
            if matcher(line):
                return line
        return None

    def stop(self, send_enter: bool = False, timeout: float = 5.0) -> None:
        if not self.is_running:
            return
        if send_enter and self.proc.stdin:
            try:
                self.proc.stdin.write("\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=timeout)
                return
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def _read_stdout(self) -> None:
        if not self.proc.stdout:
            return
        for line in self.proc.stdout:
            self._lines.append(line)
            self._queue.put(line)
            if self._emit:
                cleaned = clean_command_output(line)
                if cleaned:
                    self._emit(cleaned)


class PymobiledeviceClient:
    def __init__(self, python_executable: str | None = None):
        self.python_executable = python_executable or sys.executable
        self._active_location: ManagedProcess | None = None
        self._active_tunnel: ManagedProcess | None = None
        self._active_tunnel_info: TunnelInfo | None = None

    def base_cmd(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [self.python_executable, "--pymobiledevice3"]
        return [self.python_executable, "-m", "pymobiledevice3"]

    def close(self) -> None:
        self.stop_location_hold()
        self.stop_tunnel()

    def check_pymobiledevice(self, emit: LogSink | None = None) -> CommandResult:
        return self.run(["version"], timeout=30, emit=emit)

    def check_apple_mobile_device_service(self) -> tuple[bool, str]:
        if platform.system() != "Windows":
            return True, "Apple Mobile Device Service check skipped on this host."
        result = subprocess.run(
            ["sc", "query", "Apple Mobile Device Service"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = f"{result.stdout}\n{result.stderr}".strip()
        if result.returncode != 0:
            return False, "Apple Mobile Device Service was not found. Install iTunes from Microsoft Store."
        if "RUNNING" in output:
            return True, "Apple Mobile Device Service is running."
        return False, "Apple Mobile Device Service is installed but not running."

    def list_devices(self, emit: LogSink | None = None) -> list[Device]:
        result = self.run(["usbmux", "list"], timeout=45, emit=emit)
        if not result.ok:
            raise RuntimeError(result.output.strip() or "Unable to list iOS devices.")
        payload = extract_json_array(result.output)
        devices = []
        for item in payload:
            identifier = item.get("Identifier") or item.get("UniqueDeviceID") or item.get("SerialNumber") or ""
            devices.append(
                Device(
                    identifier=identifier,
                    name=item.get("DeviceName") or item.get("Name") or "",
                    product_version=item.get("ProductVersion") or "",
                    product_type=item.get("ProductType") or item.get("DeviceClass") or "",
                    connection_type=item.get("ConnectionType") or "",
                    raw=item,
                )
            )
        return devices

    def enable_developer_mode(self, device: Device | None, emit: LogSink | None = None) -> CommandResult:
        return self.run(["amfi", "enable-developer-mode", *device_args(device)], timeout=180, emit=emit)

    def reveal_developer_mode(self, device: Device | None, emit: LogSink | None = None) -> CommandResult:
        return self.run(["amfi", "reveal-developer-mode", *device_args(device)], timeout=90, emit=emit)

    def developer_mode_status(self, device: Device | None, emit: LogSink | None = None) -> bool | None:
        result = self.run(["amfi", "developer-mode-status", *device_args(device)], timeout=90, emit=emit)
        if not result.ok:
            return None
        return parse_bool_output(result.output)

    def prompt_developer_mode(self, device: Device | None, emit: LogSink | None = None) -> str:
        status = self.developer_mode_status(device, emit=emit)
        if status is True:
            return "Developer Mode is already enabled."

        if emit:
            emit("Showing Developer Mode on the iPhone...")
        reveal_result = self.reveal_developer_mode(device, emit=emit)
        if not reveal_result.ok:
            raise RuntimeError(reveal_result.output.strip() or "Could not reveal Developer Mode on the iPhone.")

        if emit:
            emit("Sending Developer Mode enable prompt...")
        enable_result = self.enable_developer_mode(device, emit=emit)
        if not enable_result.ok:
            raise RuntimeError(enable_result.output.strip() or "Could not send the Developer Mode prompt.")

        return "Developer Mode prompt sent. Check the iPhone and approve the restart if it asks."

    def mount_developer_image(self, device: Device | None, emit: LogSink | None = None) -> CommandResult:
        return self.run(["mounter", "auto-mount", *device_args(device)], timeout=240, emit=emit)

    def prepare_developer_services(self, device: Device, emit: LogSink | None = None) -> None:
        if device.ios_major is None or device.ios_major < 17:
            return
        if emit:
            emit("Preparing iOS developer image...")
        result = self.mount_developer_image(device, emit=emit)
        if not result.ok or is_developer_image_mount_failure(result.output):
            raise RuntimeError(format_developer_service_error(result.output))

    def start_tunnel(self, device: Device, emit: LogSink | None = None, timeout: float = 75.0) -> TunnelInfo:
        if self._active_tunnel and self._active_tunnel.is_running and self._active_tunnel_info:
            return self._active_tunnel_info

        commands = [
            ["lockdown", "start-tunnel", *device_args(device)],
            ["remote", "start-tunnel", *device_args(device)],
        ]
        last_output = ""
        for args in commands:
            if emit:
                emit(f"Starting tunnel: {display_command(self.base_cmd() + args)}")
            proc = self.popen(args, emit=emit, stdin=False)
            info = wait_for_rsd(proc, timeout=timeout)
            if info:
                self._active_tunnel = proc
                self._active_tunnel_info = info
                if emit:
                    emit(f"Tunnel ready: --rsd {info.host} {info.port}")
                return info
            last_output = proc.output
            proc.stop(timeout=2)

        raise RuntimeError(format_location_command_error(last_output, "Tunnel did not publish RSD connection details."))

    def stop_tunnel(self) -> None:
        if self._active_tunnel:
            self._active_tunnel.stop()
        self._active_tunnel = None
        self._active_tunnel_info = None

    def set_location(self, device: Device, latitude: float, longitude: float, emit: LogSink | None = None) -> str:
        self.stop_location_hold()
        major = device.ios_major
        lat = format_latitude(latitude)
        lon = format_longitude(longitude)

        if major is not None and major >= 17:
            self.prepare_developer_services(device, emit=emit)
            tunnel = self.start_tunnel(device, emit=emit)
            args = build_dvt_set_args(tunnel, lat, lon)
            if emit:
                emit(f"Setting location: {lat}, {lon}")
            hold = self.popen(args, emit=emit, stdin=True)
            time.sleep(2.5)
            if not hold.is_running:
                raise RuntimeError(format_location_command_error(hold.output, "Location command exited before holding the location."))
            self._active_location = hold
            return "Location is active. Keep this app open or press Clear Location to restore real GPS."

        args = build_legacy_set_args(device, lat, lon)
        result = self.run(args, timeout=90, emit=emit)
        if not result.ok:
            raise RuntimeError(format_location_command_error(result.output, "Location command failed."))
        return "Location was sent to the device."

    def clear_location(self, device: Device, emit: LogSink | None = None) -> CommandResult:
        self.stop_location_hold()
        major = device.ios_major
        if major is not None and major >= 17:
            self.prepare_developer_services(device, emit=emit)
            tunnel = self.start_tunnel(device, emit=emit)
            return self.run(build_dvt_clear_args(tunnel), timeout=90, emit=emit)
        return self.run(["developer", "simulate-location", "clear", *device_args(device)], timeout=90, emit=emit)

    def play_gpx_route(self, device: Device, gpx_path: Path, emit: LogSink | None = None) -> str:
        self.stop_location_hold()
        major = device.ios_major
        if major is not None and major >= 17:
            self.prepare_developer_services(device, emit=emit)
            tunnel = self.start_tunnel(device, emit=emit)
            args = build_dvt_play_args(tunnel, gpx_path)
        else:
            args = build_legacy_play_args(device, gpx_path)

        if emit:
            emit(f"Starting route playback: {gpx_path}")
        hold = self.popen(args, emit=emit, stdin=True)
        time.sleep(2.5)
        if not hold.is_running:
            raise RuntimeError(format_location_command_error(hold.output, "Route playback command exited before the route started."))
        self._active_location = hold
        return "Route playback is active. Keep this app open or press Clear Location to stop it."

    def stop_location_hold(self) -> None:
        if self._active_location:
            self._active_location.stop(send_enter=True)
        self._active_location = None

    def run(self, args: list[str], timeout: float, emit: LogSink | None = None) -> CommandResult:
        full_args = self.base_cmd() + args
        if emit:
            emit(f"Running: {display_command(full_args)}")
        proc = subprocess.run(
            full_args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env=child_env(),
            creationflags=creation_flags(),
        )
        output = clean_command_output(f"{proc.stdout}{proc.stderr}")
        if emit and output.strip():
            for line in output.splitlines():
                cleaned = clean_command_output(line)
                if cleaned:
                    emit(cleaned)
        return CommandResult(full_args, proc.returncode, output)

    def popen(self, args: list[str], emit: LogSink | None = None, stdin: bool = True) -> ManagedProcess:
        full_args = self.base_cmd() + args
        proc = subprocess.Popen(
            full_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env(),
            creationflags=creation_flags(),
        )
        return ManagedProcess(proc, full_args, emit=emit)


def clean_command_output(output: str | None) -> str:
    if not output:
        return ""
    output = ANSI_ESCAPE_RE.sub("", output)
    output = CONTROL_CHARACTER_RE.sub("", output)
    output = output.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in output.splitlines()]
    return "\n".join(lines).strip()


def is_developer_service_error(output: str | None) -> bool:
    cleaned = clean_command_output(output).lower()
    return any(marker in cleaned for marker in DEVELOPER_SERVICE_MARKERS)


def is_developer_image_mount_failure(output: str | None) -> bool:
    cleaned = clean_command_output(output).lower()
    return any(marker in cleaned for marker in DEVELOPER_IMAGE_MOUNT_FAILURE_MARKERS)


def summarize_command_output(output: str | None) -> str:
    for line in clean_command_output(output).splitlines():
        line = line.strip()
        if not line or line.startswith(("Usage:", "Try ")) or line[:1] in {"\u250c", "\u2502", "\u2514"}:
            continue
        return line[:400]
    return ""


def format_developer_service_error(output: str | None) -> str:
    summary = summarize_command_output(output)
    details = f"\n\nDevice tool detail: {summary}" if summary else ""
    return (
        "TetherLoc could not start the iOS developer location service.\n\n"
        "Try this:\n"
        "1. Unlock the iPhone and keep it connected by USB.\n"
        "2. On the iPhone, turn on Settings > Privacy & Security > Developer Mode.\n"
        "3. In TetherLoc, press Mount Developer Image, then try the location again.\n"
        "4. If the phone asks to trust this computer or restart for Developer Mode, accept it.\n"
        "5. If it still fails, unplug the phone, plug it back in, and run TetherLoc as Administrator."
        f"{details}"
    )


def format_location_command_error(output: str | None, fallback: str) -> str:
    cleaned = clean_command_output(output)
    if is_developer_service_error(cleaned):
        return format_developer_service_error(cleaned)
    return cleaned or fallback


def build_dvt_set_args(tunnel: TunnelInfo, latitude: str, longitude: str) -> list[str]:
    return [
        "developer",
        "dvt",
        "simulate-location",
        "set",
        "--rsd",
        tunnel.host,
        str(tunnel.port),
        "--",
        latitude,
        longitude,
    ]


def build_dvt_clear_args(tunnel: TunnelInfo) -> list[str]:
    return ["developer", "dvt", "simulate-location", "clear", "--rsd", tunnel.host, str(tunnel.port)]


def build_dvt_play_args(tunnel: TunnelInfo, gpx_path: Path) -> list[str]:
    return [
        "developer",
        "dvt",
        "simulate-location",
        "play",
        "--rsd",
        tunnel.host,
        str(tunnel.port),
        "--",
        str(gpx_path),
    ]


def build_legacy_set_args(device: Device | None, latitude: str, longitude: str) -> list[str]:
    return ["developer", "simulate-location", "set", *device_args(device), "--", latitude, longitude]


def build_legacy_play_args(device: Device | None, gpx_path: Path) -> list[str]:
    return ["developer", "simulate-location", "play", *device_args(device), "--", str(gpx_path)]


def device_args(device: Device | None) -> list[str]:
    if device and device.identifier:
        return ["--udid", device.identifier]
    return []


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def creation_flags() -> int:
    if platform.system() == "Windows" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return subprocess.CREATE_NO_WINDOW
    return 0


def is_running_as_admin() -> bool:
    if platform.system() != "Windows":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def extract_json_array(output: str) -> list[dict]:
    start = output.find("[")
    end = output.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("Expected a JSON device list but did not receive one.")
    parsed = json.loads(output[start : end + 1])
    if not isinstance(parsed, list):
        raise RuntimeError("Device list response was not a JSON array.")
    return parsed


def parse_bool_output(output: str | None) -> bool | None:
    cleaned = clean_command_output(output).strip().lower()
    for line in reversed(cleaned.splitlines()):
        value = line.strip().strip('"')
        if value == "true":
            return True
        if value == "false":
            return False
    return None


def parse_rsd_from_text(text: str) -> TunnelInfo | None:
    option = RSD_OPTION_RE.search(text)
    if option:
        return TunnelInfo(option.group(1), int(option.group(2)))
    address = RSD_ADDRESS_RE.search(text)
    port = RSD_PORT_RE.search(text)
    if address and port:
        return TunnelInfo(address.group(1), int(port.group(1)))
    return None


def wait_for_rsd(proc: ManagedProcess, timeout: float) -> TunnelInfo | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = parse_rsd_from_text(proc.output)
        if info:
            return info
        if not proc.is_running:
            return None
        time.sleep(0.15)
    return None


def format_latitude(value: float | str) -> str:
    return format_coord(value, minimum=-90, maximum=90, label="Latitude")


def format_longitude(value: float | str) -> str:
    return format_coord(value, minimum=-180, maximum=180, label="Longitude")


def format_coord(
    value: float | str,
    minimum: float = -180,
    maximum: float = 180,
    label: str = "Coordinate",
) -> str:
    numeric = float(value)
    if numeric < minimum or numeric > maximum:
        raise ValueError(f"{label} is outside the valid range.")
    return f"{numeric:.8f}".rstrip("0").rstrip(".")


def display_command(args: Iterable[str]) -> str:
    return " ".join(quote_arg(arg) for arg in args)


def quote_arg(arg: str) -> str:
    if not arg or any(ch.isspace() for ch in arg):
        return f'"{arg}"'
    return arg
