from __future__ import annotations

import math
import queue
import threading
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import tkintermapview
    from tkintermapview.utility_functions import decimal_to_osm
except ImportError:  # pragma: no cover - exercised only when dependency install failed
    tkintermapview = None
    decimal_to_osm = None

from .backend import (
    Device,
    PymobiledeviceClient,
    clean_command_output,
    format_location_command_error,
    is_running_as_admin,
    is_developer_image_mount_failure,
)
from .routing import (
    build_flight_plan,
    build_route_plan,
    fetch_road_route_details,
    fetch_stop_signs_near_route,
    match_stop_signs_to_route,
)


DEFAULT_LOCATION = (37.3349, -122.0090)
APPLE_WINDOWS_DOWNLOAD_URL = "https://support.apple.com/en-us/118290"
APPLE_DEVICES_INSTALL_URL = "https://support.apple.com/guide/devices-windows/install-the-apple-devices-app-mchl5ded2763/windows"

AIRPORTS: dict[str, tuple[str, float, float]] = {
    "ATL": ("ATL - Atlanta", 33.6407, -84.4277),
    "BOS": ("BOS - Boston Logan", 42.3656, -71.0096),
    "DFW": ("DFW - Dallas/Fort Worth", 32.8998, -97.0403),
    "DEN": ("DEN - Denver", 39.8561, -104.6737),
    "EWR": ("EWR - Newark", 40.6895, -74.1745),
    "JFK": ("JFK - New York JFK", 40.6413, -73.7781),
    "LAS": ("LAS - Las Vegas", 36.0840, -115.1537),
    "LAX": ("LAX - Los Angeles", 33.9416, -118.4085),
    "MIA": ("MIA - Miami", 25.7959, -80.2870),
    "ORD": ("ORD - Chicago O'Hare", 41.9742, -87.9073),
    "SEA": ("SEA - Seattle-Tacoma", 47.4502, -122.3088),
    "SFO": ("SFO - San Francisco", 37.6213, -122.3790),
}
AIRPORT_LABEL_TO_CODE = {label: code for code, (label, _lat, _lon) in AIRPORTS.items()}
AIRPORT_CHOICES = [AIRPORTS[code][0] for code in sorted(AIRPORTS)]

BG = "#050608"
SURFACE = "#15161B"
SURFACE_ALT = "#202126"
BORDER = "#343640"
TEXT = "#F3F5F8"
MUTED = "#8D929F"
ACCENT = "#35B8D8"
ACCENT_HOVER = "#4CC7E4"
SECONDARY = "#6C7483"
SECONDARY_HOVER = "#9AA2AF"
DANGER = "#FF6B6B"
LOCK = "#B8C0CC"
LOCK_HOVER = "#E3E8EF"
GREEN = "#31E77B"
WARNING = "#F59A23"
INPUT_BG = "#101116"
MAP_LOADING = "#020305"
LOG_BG = "#0C0D11"
LOG_FG = "#DCE8EA"
DARK_MAP_TILE_SERVER = "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
DEVICE_MONITOR_INTERVAL_MS = 3500
DEVICE_MONITOR_TIMEOUT_SECONDS = 8.0


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        parent,
        text: str,
        command,
        bg: str,
        fg: str,
        active_bg: str,
        active_fg: str | None = None,
        outline: str = "#343640",
        radius: int = 14,
        height: int = 42,
        padx: int = 18,
        font: tuple[str, int, str] = ("Segoe UI", 9, "bold"),
        min_width: int = 86,
    ) -> None:
        super().__init__(
            parent,
            height=height,
            width=min_width,
            bg=parent.cget("bg") if hasattr(parent, "cget") else BG,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.text = text
        self.command = command
        self.normal_bg = bg
        self.normal_fg = fg
        self.active_bg = active_bg
        self.active_fg = active_fg or fg
        self.outline = outline
        self.radius = radius
        self.button_height = height
        self.padx = padx
        self.font = font
        self._hovered = False
        self._pressed = False
        self.configure(width=max(min_width, len(text) * 8 + (padx * 2)))
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw()

    def _round_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        self.create_polygon(points, smooth=True, splinesteps=18, **kwargs)

    def _draw(self) -> None:
        self.delete("all")
        width = max(2, self.winfo_width())
        height = max(2, self.winfo_height() or self.button_height)
        bg = self.active_bg if self._hovered or self._pressed else self.normal_bg
        fg = self.active_fg if self._hovered or self._pressed else self.normal_fg
        y_offset = 1 if self._pressed else 0
        self._round_rect(1, 1 + y_offset, width - 1, height - 1 + y_offset, self.radius, fill=bg, outline=self.outline)
        self.create_text(width / 2, height / 2 + y_offset, text=self.text, fill=fg, font=self.font)

    def _on_enter(self, _event) -> None:
        self._hovered = True
        self._draw()

    def _on_leave(self, _event) -> None:
        self._hovered = False
        self._pressed = False
        self._draw()

    def _on_press(self, _event) -> None:
        self._pressed = True
        self._draw()

    def _on_release(self, event) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed and 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.command()

    def set_style(self, bg: str, fg: str, active_bg: str, active_fg: str | None = None, outline: str | None = None) -> None:
        self.normal_bg = bg
        self.normal_fg = fg
        self.active_bg = active_bg
        self.active_fg = active_fg or fg
        if outline is not None:
            self.outline = outline
        self._draw()


class TetherLocApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("TetherLoc")
        self.geometry("1180x780")
        self.minsize(980, 660)
        self.configure(bg=BG)

        self.client = PymobiledeviceClient()
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.devices: list[Device] = []
        self.destination_marker = None
        self.start_marker = None
        self.route_path = None
        self.speed_mode_buttons: dict[str, tk.Button] = {}
        self.route_start = DEFAULT_LOCATION
        self.map_widget = None
        self.side_canvas: tk.Canvas | None = None
        self.log_text: tk.Text | None = None
        self.device_combo: ttk.Combobox | None = None
        self.status_label: tk.Label | None = None
        self.connection_label: tk.Label | None = None
        self.route_summary_card: tk.Frame | None = None
        self.panel_tab_buttons: dict[str, RoundedButton] = {}
        self.route_page: tk.Frame | None = None
        self.misc_page: tk.Frame | None = None
        self.setup_frame: tk.Frame | None = None
        self.setup_badges: dict[str, tk.Label] = {}
        self.setup_detail_labels: dict[str, tk.Label] = {}
        self.setup_help_label: tk.Label | None = None
        self.setup_retry_button = None
        self.setup_apple_devices_button = None
        self.setup_itunes_button = None
        self.main_ready = False
        self.setup_checking = False
        self.device_monitor_checking = False
        self.device_monitor_after_id: str | None = None
        self.device_monitor_generation = 0
        self.developer_mode_prompted_devices: set[str] = set()
        self.developer_mode_prompting = False
        self._warming_map_cache = False

        self.selected_device = tk.StringVar()
        self.latitude = tk.StringVar(value=f"{DEFAULT_LOCATION[0]:.4f}")
        self.longitude = tk.StringVar(value=f"{DEFAULT_LOCATION[1]:.4f}")
        self.start_label = tk.StringVar(value=self._format_pair(self.route_start))
        self.speed_mode = tk.StringVar(value="auto")
        self.mph_label_text = tk.StringVar(value="Fallback MPH")
        self.mph_value_text = tk.StringVar(value="35 mph")
        self.mph = tk.DoubleVar(value=35.0)
        self.interval_seconds = tk.DoubleVar(value=1.0)
        self.stop_signs = tk.BooleanVar(value=True)
        self.stop_seconds = tk.DoubleVar(value=3.0)
        self.destination_label = tk.StringVar(value=self._format_pair(DEFAULT_LOCATION))
        self.roadtrip_speed_text = tk.StringVar(value="--")
        self.roadtrip_eta_text = tk.StringVar(value="--")
        self.roadtrip_distance_text = tk.StringVar(value="--")
        self.roadtrip_stops_text = tk.StringVar(value="--")
        self.route_summary_coords = tk.StringVar(value=self._format_pair(DEFAULT_LOCATION))
        self.route_summary_meta = tk.StringVar(value="Distance --")
        self.connection_text = tk.StringVar(value="Disconnected")
        self.status = tk.StringVar(value="Ready")
        self.panel_tab = tk.StringVar(value="route")
        self.flight_origin = tk.StringVar(value=AIRPORTS["SFO"][0])
        self.flight_destination = tk.StringVar(value=AIRPORTS["LAX"][0])
        self.flight_cruise_mph = tk.DoubleVar(value=480.0)
        self.flight_taxi_mph = tk.DoubleVar(value=18.0)
        self.flight_board_seconds = tk.DoubleVar(value=45.0)
        self.flight_interval_seconds = tk.DoubleVar(value=5.0)
        self.flight_speed_text = tk.StringVar(value="480 mph")
        self.flight_eta_text = tk.StringVar(value="--")
        self.flight_distance_text = tk.StringVar(value="--")
        self.flight_stage_text = tk.StringVar(value="Ready")
        self.setup_title = tk.StringVar(value="Checking setup")
        self.setup_detail = tk.StringVar(value="Looking for Apple drivers and a USB iPhone.")

        self._configure_style()
        if not is_running_as_admin():
            self._show_admin_required_screen()
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            return

        self._show_setup_screen(
            "Checking setup",
            "Looking for Apple drivers, pymobiledevice3, and a trusted USB iPhone.",
            checking=True,
        )
        self.after(100, self._drain_log_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(250, self._run_setup_gate_check)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=("Segoe UI", 10), background=BG, foreground=TEXT)
        style.configure("App.TFrame", background=BG)
        style.configure("Topbar.TFrame", background=BG)
        style.configure("Toolbar.TFrame", background=SURFACE)
        style.configure("Panel.TFrame", background=SURFACE)
        style.configure("Tile.TFrame", background=SURFACE_ALT)
        style.configure("MapShell.TFrame", background=BORDER)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 23, "bold"))
        style.configure("Subtle.TLabel", background=BG, foreground=MUTED)
        style.configure("Toolbar.TLabel", background=SURFACE, foreground=MUTED)
        style.configure("Panel.TLabel", background=SURFACE, foreground=TEXT)
        style.configure("SectionTitle.Panel.TLabel", background=SURFACE, foreground=TEXT, font=("Segoe UI", 12, "bold"))
        style.configure("Muted.Panel.TLabel", background=SURFACE, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Metric.Panel.TLabel", background=SURFACE_ALT, foreground=TEXT, font=("Segoe UI", 11, "bold"))
        style.configure("MetricName.Panel.TLabel", background=SURFACE_ALT, foreground=MUTED, font=("Segoe UI", 8, "bold"))
        style.configure(
            "TEntry",
            padding=(9, 7),
            fieldbackground=INPUT_BG,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
        )
        style.configure(
            "TCombobox",
            padding=(9, 7),
            fieldbackground=INPUT_BG,
            foreground=TEXT,
            background=INPUT_BG,
            bordercolor=BORDER,
            arrowcolor=TEXT,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", INPUT_BG)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", INPUT_BG)],
            selectforeground=[("readonly", TEXT)],
        )
        style.configure(
            "TSpinbox",
            padding=(8, 6),
            fieldbackground=INPUT_BG,
            foreground=TEXT,
            background=INPUT_BG,
            bordercolor=BORDER,
            arrowcolor=TEXT,
        )
        style.configure("TCheckbutton", background=SURFACE, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", SURFACE)], foreground=[("active", TEXT)])
        style.configure("TButton", padding=(13, 8), background=SURFACE_ALT, foreground=TEXT, bordercolor=BORDER, relief="flat")
        style.map("TButton", background=[("active", "#263443")], foreground=[("active", TEXT)])
        style.configure("Accent.TButton", padding=(14, 9), background=ACCENT, foreground="#061216", bordercolor=ACCENT, relief="flat")
        style.map("Accent.TButton", background=[("active", ACCENT_HOVER)], foreground=[("active", "#061216")])
        style.configure("Secondary.TButton", background="#203247", foreground=SECONDARY, bordercolor="#30475F", relief="flat")
        style.map("Secondary.TButton", background=[("active", "#293E55")], foreground=[("active", SECONDARY_HOVER)])
        style.configure("Danger.TButton", background="#3A1F29", foreground=DANGER, bordercolor="#613040", relief="flat")
        style.map("Danger.TButton", background=[("active", "#4B2632")], foreground=[("active", DANGER)])
        style.configure("Lock.TButton", background="#202A38", foreground=LOCK, bordercolor="#303C4F", relief="flat")
        style.map("Lock.TButton", background=[("active", "#293447")], foreground=[("active", LOCK_HOVER)])
        style.configure(
            "Vertical.TScrollbar",
            background=SURFACE_ALT,
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=MUTED,
            relief="flat",
        )
        style.layout(
            "Clean.Vertical.TScrollbar",
            [
                (
                    "Vertical.Scrollbar.trough",
                    {
                        "sticky": "ns",
                        "children": [
                            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"}),
                        ],
                    },
                )
            ],
        )
        style.configure(
            "Clean.Vertical.TScrollbar",
            background="#3A3E49",
            troughcolor=SURFACE,
            bordercolor=SURFACE,
            relief="flat",
            width=10,
        )

    def _build_ui(self) -> None:
        for row in range(3):
            self.rowconfigure(row, weight=0)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        shell = tk.Frame(self, bg=MAP_LOADING)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        self._build_map(shell)

        sidebar = tk.Frame(shell, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        sidebar.place(x=18, y=18, width=360, relheight=1, height=-36)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(0, weight=1)

        self.side_canvas = tk.Canvas(sidebar, bg=SURFACE, bd=0, highlightthickness=0)
        self.side_canvas.grid(row=0, column=0, sticky="nsew")
        side_scrollbar = ttk.Scrollbar(
            sidebar,
            orient="vertical",
            command=self.side_canvas.yview,
            style="Clean.Vertical.TScrollbar",
        )
        side_scrollbar.grid(row=0, column=1, sticky="ns")
        self.side_canvas.configure(yscrollcommand=side_scrollbar.set)

        side = tk.Frame(self.side_canvas, bg=SURFACE)
        side_window = self.side_canvas.create_window((0, 0), window=side, anchor="nw")
        side.columnconfigure(0, weight=1)
        side.bind("<Configure>", lambda event: self.side_canvas.configure(scrollregion=self.side_canvas.bbox("all")))
        self.side_canvas.bind("<Configure>", lambda event: self.side_canvas.itemconfigure(side_window, width=event.width))
        self._build_controls(side)
        self.side_canvas.bind("<MouseWheel>", self._on_side_mousewheel)
        self.side_canvas.bind("<Button-4>", self._on_side_mousewheel)
        self.side_canvas.bind("<Button-5>", self._on_side_mousewheel)
        self._bind_side_scroll_widgets(side)

        status_chip = tk.Frame(shell, bg="#11171A", highlightbackground="#1C5C3B", highlightthickness=1)
        status_chip.place(relx=0.5, y=18, anchor="n")
        tk.Label(
            status_chip,
            text="TETHERLOC",
            bg="#11171A",
            fg=GREEN,
            font=("Segoe UI", 8, "bold"),
        ).grid(row=0, column=0, sticky="ew", padx=18, pady=(8, 0))
        self.status_label = tk.Label(
            status_chip,
            textvariable=self.status,
            bg="#11171A",
            fg=TEXT,
            font=("Segoe UI", 13, "bold"),
        )
        self.status_label.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))

        connection_chip = tk.Frame(shell, bg="#15100A", highlightbackground="#6B4917", highlightthickness=1)
        connection_chip.place(relx=1.0, y=18, x=-20, anchor="ne")
        self.connection_label = tk.Label(
            connection_chip,
            textvariable=self.connection_text,
            bg="#15100A",
            fg=WARNING,
            font=("Segoe UI", 10, "bold"),
        )
        self.connection_label.grid(row=0, column=0, padx=14, pady=8)

        self.route_summary_card = tk.Frame(shell, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        self.route_summary_card.place(relx=0.58, rely=1.0, y=-34, anchor="s", width=360)
        self.route_summary_card.columnconfigure(0, weight=1)
        tk.Label(
            self.route_summary_card,
            text="Destination",
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 2))
        tk.Label(
            self.route_summary_card,
            textvariable=self.route_summary_coords,
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=16)
        tk.Label(
            self.route_summary_card,
            textvariable=self.route_summary_meta,
            bg=SURFACE,
            fg=SECONDARY_HOVER,
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", padx=16, pady=(2, 12))

        map_actions = tk.Frame(shell, bg=MAP_LOADING)
        map_actions.place(relx=1.0, rely=0.55, x=-22, anchor="e")
        self._map_action_button(map_actions, 0, "Target", lambda: self.map_widget.set_position(*self.route_start) if self.map_widget else None)
        self._map_action_button(map_actions, 1, "Clear", self._start_clear_location, danger=True)
        self._map_action_button(map_actions, 2, "Lock", self._show_pause_help)
        self._map_action_button(map_actions, 3, "Stop", lambda: self._run_worker("Stop roadtrip", self._stop_roadtrip), danger=True)

        zoom_actions = tk.Frame(shell, bg=MAP_LOADING)
        zoom_actions.place(x=392, y=18, anchor="nw")
        self._map_action_button(zoom_actions, 0, "+", lambda: self._adjust_zoom(1))
        self._map_action_button(zoom_actions, 1, "-", lambda: self._adjust_zoom(-1))

        for widget in (sidebar, status_chip, connection_chip, self.route_summary_card, map_actions, zoom_actions):
            widget.lift()
        self._set_connection_state(bool(self.devices))

    def _show_admin_required_screen(self) -> None:
        self._clear_root()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        frame = tk.Frame(self, bg=BG)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        card = tk.Frame(frame, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        card.grid(row=0, column=0, sticky="", padx=28, pady=28)
        card.columnconfigure(0, weight=1)

        tk.Label(
            card,
            text="Administrator Required",
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI", 24, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=26, pady=(24, 6))
        tk.Label(
            card,
            text=(
                "TetherLoc needs Administrator rights before it can prepare the iOS developer tunnel. "
                "Close this window, open PowerShell as Administrator, return to this folder, and rerun setup."
            ),
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 10),
            wraplength=600,
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=26, pady=(0, 18))

        command = "powershell -ExecutionPolicy Bypass -File .\\run.ps1"
        command_box = tk.Frame(card, bg=INPUT_BG, highlightbackground="#273645", highlightthickness=1)
        command_box.grid(row=2, column=0, sticky="ew", padx=26, pady=(0, 18))
        command_box.columnconfigure(0, weight=1)
        tk.Label(
            command_box,
            text=command,
            bg=INPUT_BG,
            fg=ACCENT,
            font=("Cascadia Mono", 10, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=12)

        tk.Label(
            card,
            text=(
                "If you are using the installed app instead of the source folder, close it and start TetherLoc "
                "with Run as administrator."
            ),
            bg=SURFACE,
            fg=SECONDARY_HOVER,
            font=("Segoe UI", 9),
            wraplength=600,
            justify="left",
        ).grid(row=3, column=0, sticky="w", padx=26, pady=(0, 20))

        actions = tk.Frame(card, bg=SURFACE)
        actions.grid(row=4, column=0, sticky="ew", padx=26, pady=(0, 24))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        RoundedButton(
            actions,
            "Copy Command",
            lambda: self._copy_text(command, "Admin command copied"),
            bg=ACCENT,
            fg="#061216",
            active_bg=ACCENT_HOVER,
            outline=ACCENT,
            radius=18,
            height=44,
            min_width=150,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        RoundedButton(
            actions,
            "Close TetherLoc",
            self.destroy,
            bg=SURFACE_ALT,
            fg=TEXT,
            active_bg="#2A2D36",
            outline=BORDER,
            radius=18,
            height=44,
            min_width=150,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 0))

    def _copy_text(self, text: str, status: str = "Copied") -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.set(status)

    def _adjust_zoom(self, delta: int) -> None:
        if not self.map_widget:
            return
        next_zoom = max(self.map_widget.min_zoom, min(self.map_widget.max_zoom, round(self.map_widget.zoom) + delta))
        self.map_widget.set_zoom(next_zoom)

    def _map_action_button(self, parent: tk.Frame, row: int, text: str, command, danger: bool = False) -> None:
        bg = "#211016" if danger else "#1A1C22"
        fg = DANGER if danger else TEXT
        active_bg = "#341A23" if danger else "#2A2D36"
        button = RoundedButton(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            active_bg=active_bg,
            outline="#3A3D48",
            radius=17,
            height=42,
            padx=12,
            min_width=58,
        )
        button.grid(row=row, column=0, sticky="ew", pady=5)

    def _show_setup_screen(
        self,
        title: str,
        detail: str,
        checking: bool = False,
        driver_ok: bool | None = None,
        pymobiledevice_ok: bool | None = None,
        device_count: int | None = None,
        device_error: str = "",
    ) -> None:
        if self.setup_frame is not None:
            self._update_setup_screen(
                title,
                detail,
                checking,
                driver_ok,
                pymobiledevice_ok,
                device_count,
                device_error,
            )
            return

        self._clear_root()
        self.setup_title.set(title)
        self.setup_detail.set(detail)

        self.setup_frame = tk.Frame(self, bg=BG)
        self.setup_frame.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self.rowconfigure(2, weight=0)
        self.setup_frame.columnconfigure(0, weight=1)
        self.setup_frame.rowconfigure(0, weight=1)

        card = tk.Frame(self.setup_frame, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        card.grid(row=0, column=0, sticky="", padx=28, pady=28)
        card.columnconfigure(0, weight=1)

        tk.Label(card, textvariable=self.setup_title, bg=SURFACE, fg=TEXT, font=("Segoe UI", 24, "bold")).grid(
            row=0, column=0, sticky="w", padx=26, pady=(24, 6)
        )
        tk.Label(
            card,
            textvariable=self.setup_detail,
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 10),
            wraplength=560,
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=26, pady=(0, 18))

        checks = tk.Frame(card, bg=SURFACE)
        checks.grid(row=2, column=0, sticky="ew", padx=26, pady=(0, 18))
        checks.columnconfigure(1, weight=1)
        self.setup_badges = {}
        self.setup_detail_labels = {}
        self._add_setup_check_row(checks, "driver", 0, "Apple drivers", driver_ok, "Apple Mobile Device Service")
        self._add_setup_check_row(checks, "tools", 1, "Core tools", pymobiledevice_ok, "pymobiledevice3")
        device_ok = None if device_count is None else device_count > 0
        if device_count is None:
            device_status = "Not checked yet"
        elif device_count:
            device_status = f"{device_count} device(s) found"
        else:
            device_status = "Waiting for iPhone"
        self._add_setup_check_row(checks, "device", 2, "iPhone", device_ok, device_status)

        help_box = tk.Frame(card, bg=SURFACE_ALT, highlightbackground="#273645", highlightthickness=1)
        help_box.grid(row=3, column=0, sticky="ew", padx=26, pady=(0, 18))
        help_box.columnconfigure(0, weight=1)
        help_text = self._setup_help_text(driver_ok, pymobiledevice_ok, device_count, device_error)
        self.setup_help_label = tk.Label(
            help_box,
            text=help_text,
            bg=SURFACE_ALT,
            fg=TEXT,
            font=("Segoe UI", 10),
            wraplength=560,
            justify="left",
        )
        self.setup_help_label.grid(row=0, column=0, sticky="w", padx=16, pady=14)

        actions = tk.Frame(card, bg=SURFACE)
        actions.grid(row=4, column=0, sticky="ew", padx=26, pady=(0, 24))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        actions.columnconfigure(2, weight=1)
        retry_text = "Checking..." if checking else "Retry Check"
        self.setup_retry_button = ttk.Button(
            actions,
            text=retry_text,
            style="Accent.TButton",
            command=self._run_setup_gate_check,
        )
        self.setup_retry_button.grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        self.setup_apple_devices_button = ttk.Button(
            actions,
            text="Get Apple Devices",
            style="Secondary.TButton",
            command=self._open_apple_devices_page,
        )
        self.setup_apple_devices_button.grid(
            row=0, column=1, sticky="ew", padx=6
        )
        self.setup_itunes_button = ttk.Button(
            actions,
            text="Get iTunes / Drivers",
            command=self._open_apple_download_page,
        )
        self.setup_itunes_button.grid(
            row=0, column=2, sticky="ew", padx=(6, 0)
        )

        self._update_setup_screen(
            title,
            detail,
            checking,
            driver_ok,
            pymobiledevice_ok,
            device_count,
            device_error,
        )

    def _add_setup_check_row(
        self,
        parent: tk.Frame,
        key: str,
        row: int,
        label: str,
        ok: bool | None,
        detail: str,
    ) -> None:
        badge_text, badge_bg, badge_fg = self._setup_badge_config(ok)
        badge = tk.Label(
            parent,
            text=badge_text,
            bg=badge_bg,
            fg=badge_fg,
            font=("Segoe UI", 8, "bold"),
            padx=10,
            pady=5,
        )
        badge.grid(row=row, column=0, sticky="w", pady=5)
        tk.Label(parent, text=label, bg=SURFACE, fg=TEXT, font=("Segoe UI", 10, "bold")).grid(
            row=row, column=1, sticky="w", padx=(12, 8), pady=5
        )
        detail_label = tk.Label(parent, text=detail, bg=SURFACE, fg=MUTED, font=("Segoe UI", 9))
        detail_label.grid(
            row=row, column=2, sticky="e", pady=5
        )
        self.setup_badges[key] = badge
        self.setup_detail_labels[key] = detail_label

    def _update_setup_screen(
        self,
        title: str,
        detail: str,
        checking: bool,
        driver_ok: bool | None,
        pymobiledevice_ok: bool | None,
        device_count: int | None,
        device_error: str,
    ) -> None:
        if self.setup_title.get() != title:
            self.setup_title.set(title)
        if self.setup_detail.get() != detail:
            self.setup_detail.set(detail)
        self._update_setup_check_row("driver", driver_ok, "Apple Mobile Device Service")
        self._update_setup_check_row("tools", pymobiledevice_ok, "pymobiledevice3")
        device_ok = None if device_count is None else device_count > 0
        if device_count is None:
            device_status = "Not checked yet"
        elif device_count:
            device_status = f"{device_count} device(s) found"
        else:
            device_status = "Waiting for iPhone"
        self._update_setup_check_row("device", device_ok, device_status)
        if self.setup_help_label is not None:
            help_text = self._setup_help_text(driver_ok, pymobiledevice_ok, device_count, device_error)
            if self.setup_help_label.cget("text") != help_text:
                self.setup_help_label.configure(text=help_text)
        if self.setup_retry_button is not None:
            retry_text = "Checking..." if checking else "Retry Check"
            if self.setup_retry_button.cget("text") != retry_text:
                self.setup_retry_button.configure(text=retry_text)

    def _update_setup_check_row(self, key: str, ok: bool | None, detail: str) -> None:
        badge = self.setup_badges.get(key)
        detail_label = self.setup_detail_labels.get(key)
        if badge is not None:
            badge_text, badge_bg, badge_fg = self._setup_badge_config(ok)
            if (
                badge.cget("text") != badge_text
                or badge.cget("bg") != badge_bg
                or badge.cget("fg") != badge_fg
            ):
                badge.configure(text=badge_text, bg=badge_bg, fg=badge_fg)
        if detail_label is not None:
            if detail_label.cget("text") != detail:
                detail_label.configure(text=detail)

    @staticmethod
    def _setup_badge_config(ok: bool | None) -> tuple[str, str, str]:
        if ok is None:
            return "...", "#202B38", MUTED
        if ok:
            return "OK", "#143831", ACCENT
        return "WAIT", "#3A1F29", DANGER

    def _setup_help_text(
        self,
        driver_ok: bool | None,
        pymobiledevice_ok: bool | None,
        device_count: int | None,
        device_error: str,
    ) -> str:
        if driver_ok is False:
            return (
                "Apple Mobile Device Support is missing or not running. Install Apple Devices from the Microsoft "
                "Store using the Get Apple Devices button. If that does not install the USB driver on your PC, "
                "use Get iTunes / Drivers from Apple's Windows download page. After installing, reconnect your "
                "iPhone, tap Trust This Computer, reopen TetherLoc as Administrator, and retry."
            )
        if pymobiledevice_ok is False:
            return (
                "The local Python tool package is missing or not starting. Close this window and run run.ps1 again "
                "so it can reinstall the required packages."
            )
        if device_error:
            return f"Device scan could not finish: {device_error}"
        if device_count == 0:
            return (
                "Connect your iPhone with USB, unlock it, and tap Trust This Computer. If Windows does not react, "
                "use Get Apple Devices or Get iTunes / Drivers, then unplug and reconnect."
            )
        return "This usually takes a few seconds. Keep the phone unlocked while TetherLoc checks the connection."

    def _run_setup_gate_check(self) -> None:
        if self.main_ready or self.setup_checking:
            return
        self.setup_checking = True
        if self.setup_frame is None:
            self._show_setup_screen(
                "Checking setup",
                "Looking for Apple drivers, pymobiledevice3, and a trusted USB iPhone.",
                checking=True,
            )
        threading.Thread(target=self._setup_gate_check, name="setup-gate", daemon=True).start()

    def _setup_gate_check(self) -> None:
        driver_ok = False
        driver_message = ""
        pymobiledevice_ok = False
        pymobiledevice_message = ""
        devices: list[Device] = []
        device_error = ""
        try:
            driver_ok, driver_message = self.client.check_apple_mobile_device_service()
        except Exception as exc:
            driver_message = str(exc)

        try:
            result = self.client.check_pymobiledevice()
            pymobiledevice_ok = result.ok
            pymobiledevice_message = result.output.strip() or "pymobiledevice3 ready"
        except Exception as exc:
            pymobiledevice_message = str(exc)

        if driver_ok and pymobiledevice_ok:
            try:
                devices = self.client.list_devices()
            except Exception as exc:
                device_error = str(exc)

        self.after(
            0,
            lambda: self._apply_setup_gate_result(
                driver_ok,
                driver_message,
                pymobiledevice_ok,
                pymobiledevice_message,
                devices,
                device_error,
            ),
        )

    def _apply_setup_gate_result(
        self,
        driver_ok: bool,
        driver_message: str,
        pymobiledevice_ok: bool,
        pymobiledevice_message: str,
        devices: list[Device],
        device_error: str,
    ) -> None:
        self.setup_checking = False
        if self.main_ready:
            return
        if driver_ok and pymobiledevice_ok and devices:
            self._enter_main_app(devices)
            return

        if driver_ok and pymobiledevice_ok:
            title = "Waiting for iPhone"
            detail = "TetherLoc is ready. Connect and trust your iPhone to continue."
            self.after(3000, self._run_setup_gate_check)
        else:
            title = "Setup needed"
            missing = []
            if not driver_ok:
                missing.append(driver_message or "Apple drivers")
            if not pymobiledevice_ok:
                missing.append(pymobiledevice_message or "pymobiledevice3")
            detail = "Fix the items below, then retry the check."
            if missing:
                detail = f"{detail} Missing: {'; '.join(missing)}"

        self._show_setup_screen(
            title,
            detail,
            checking=False,
            driver_ok=driver_ok,
            pymobiledevice_ok=pymobiledevice_ok,
            device_count=len(devices),
            device_error=device_error,
        )

    def _enter_main_app(self, devices: list[Device]) -> None:
        self.main_ready = True
        self.devices = devices
        self._clear_root()
        self._build_ui()
        self._apply_devices(devices)
        self._set_status("Ready")
        self._start_device_monitor()

    def _clear_root(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self.setup_frame = None
        self.setup_badges = {}
        self.setup_detail_labels = {}
        self.setup_help_label = None
        self.setup_retry_button = None
        self.setup_apple_devices_button = None
        self.setup_itunes_button = None
        self.map_widget = None
        self.side_canvas = None
        self.log_text = None
        self.device_combo = None
        self.status_label = None
        self.connection_label = None
        self.route_summary_card = None
        self.panel_tab_buttons = {}
        self.route_page = None
        self.misc_page = None
        self.destination_marker = None
        self.start_marker = None
        self.route_path = None

    def _start_device_monitor(self) -> None:
        self.device_monitor_generation += 1
        self.device_monitor_checking = False
        self._schedule_device_monitor()

    def _stop_device_monitor(self) -> None:
        self.device_monitor_generation += 1
        self.device_monitor_checking = False
        if self.device_monitor_after_id is not None:
            try:
                self.after_cancel(self.device_monitor_after_id)
            except tk.TclError:
                pass
            self.device_monitor_after_id = None

    def _schedule_device_monitor(self, delay_ms: int = DEVICE_MONITOR_INTERVAL_MS) -> None:
        if not self.main_ready:
            return
        if self.device_monitor_after_id is not None:
            try:
                self.after_cancel(self.device_monitor_after_id)
            except tk.TclError:
                pass
        self.device_monitor_after_id = self.after(delay_ms, self._run_device_monitor_check)

    def _run_device_monitor_check(self) -> None:
        self.device_monitor_after_id = None
        if not self.main_ready or self.device_monitor_checking:
            return
        self.device_monitor_checking = True
        generation = self.device_monitor_generation
        threading.Thread(
            target=lambda: self._device_monitor_check(generation),
            name="device-monitor",
            daemon=True,
        ).start()

    def _device_monitor_check(self, generation: int) -> None:
        devices: list[Device] = []
        device_error = ""
        try:
            devices = self.client.list_devices(timeout=DEVICE_MONITOR_TIMEOUT_SECONDS)
        except Exception as exc:
            device_error = clean_command_output(str(exc)) or "Device scan failed."

        self.after(0, lambda: self._apply_device_monitor_result(generation, devices, device_error))

    def _apply_device_monitor_result(self, generation: int, devices: list[Device], device_error: str) -> None:
        if generation != self.device_monitor_generation:
            return
        self.device_monitor_checking = False
        if not self.main_ready:
            return

        if devices:
            self._apply_devices(devices, announce=False)
            self._schedule_device_monitor()
            return

        self._return_to_setup_after_disconnect(device_error)

    def _return_to_setup_after_disconnect(self, device_error: str = "") -> None:
        if not self.main_ready:
            return
        self._stop_device_monitor()
        self.main_ready = False
        self.devices = []
        self.selected_device.set("")
        self.developer_mode_prompted_devices.clear()
        try:
            self.client.stop_location_hold()
            self.client.stop_tunnel()
        except Exception as exc:
            self._log(f"Stopped after disconnect with warning: {clean_command_output(str(exc))}")

        detail = "The iPhone disconnected. Reconnect it, unlock it, and tap Trust This Computer to continue."
        self._clear_root()
        self._show_setup_screen(
            "Waiting for iPhone",
            detail,
            checking=False,
            driver_ok=True,
            pymobiledevice_ok=True,
            device_count=0,
            device_error=device_error,
        )
        self._set_connection_state(False)
        self.after(1000, self._run_setup_gate_check)

    @staticmethod
    def _open_apple_devices_page() -> None:
        webbrowser.open(APPLE_DEVICES_INSTALL_URL)

    @staticmethod
    def _open_apple_download_page() -> None:
        webbrowser.open(APPLE_WINDOWS_DOWNLOAD_URL)

    def _build_map(self, parent: ttk.Frame) -> None:
        if tkintermapview is None:
            fallback = ttk.Label(
                parent,
                text="Map package missing. Run .\\run.ps1 again so it can install tkintermapview.",
                anchor="center",
                style="Panel.TLabel",
            )
            fallback.grid(row=0, column=0, sticky="nsew")
            return

        self.map_widget = tkintermapview.TkinterMapView(
            parent,
            corner_radius=0,
            bg_color=BORDER,
            max_zoom=18,
        )
        self.map_widget.grid(row=0, column=0, sticky="nsew")
        self.map_widget.canvas.configure(bg=MAP_LOADING)
        try:
            self.map_widget.set_tile_server(DARK_MAP_TILE_SERVER, max_zoom=19)
        except Exception as exc:
            self._log(f"Dark map tiles unavailable: {exc}")
        self.map_widget.set_position(self.route_start[0], self.route_start[1])
        self.map_widget.set_zoom(13)
        self.map_widget.add_left_click_map_command(self._map_clicked)
        self._set_destination_marker(self.route_start)
        self._set_start_marker(self.route_start)
        self.after(700, self._warm_map_cache_loop)

    def _create_modern_section(
        self,
        parent: tk.Frame,
        row: int,
        title: str,
        pady: tuple[int, int] = (0, 12),
    ) -> tk.Frame:
        outer = tk.Frame(parent, bg=SURFACE, highlightbackground="#252731", highlightthickness=1)
        outer.grid(row=row, column=0, sticky="ew", padx=16, pady=pady)
        outer.columnconfigure(0, weight=1)
        tk.Label(
            outer,
            text=title.upper(),
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        body = tk.Frame(outer, bg=SURFACE)
        body.grid(row=1, column=0, sticky="ew", padx=14, pady=(6, 14))
        body.columnconfigure(0, weight=1)
        return body

    def _field_label(self, parent: tk.Widget, row: int, column: int, text: str) -> None:
        tk.Label(parent, text=text, bg=SURFACE, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w").grid(
            row=row,
            column=column,
            sticky="w",
            padx=(0 if column == 0 else 6, 6 if column == 0 else 0),
        )

    def _number_stepper(
        self,
        parent: tk.Widget,
        variable: tk.Variable,
        minimum: float,
        maximum: float,
        increment: float,
        row: int,
        column: int,
        width: int = 7,
        sticky: str = "ew",
        padx=0,
        pady=0,
    ) -> tk.Frame:
        shell = tk.Frame(parent, bg=INPUT_BG, highlightbackground=BORDER, highlightthickness=1)
        shell.grid(row=row, column=column, sticky=sticky, padx=padx, pady=pady)
        shell.columnconfigure(0, weight=1)

        entry = tk.Entry(
            shell,
            textvariable=variable,
            width=width,
            justify="center",
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            font=("Segoe UI", 10, "bold"),
        )
        entry.grid(row=0, column=0, sticky="ew", padx=(10, 4), pady=8)

        controls = tk.Frame(shell, bg=INPUT_BG)
        controls.grid(row=0, column=1, sticky="e", padx=(0, 6), pady=5)
        self._mini_step_button(
            controls,
            "-",
            lambda: self._step_number(variable, minimum, maximum, -increment),
            column=0,
        )
        self._mini_step_button(
            controls,
            "+",
            lambda: self._step_number(variable, minimum, maximum, increment),
            column=1,
        )
        return shell

    def _mini_step_button(self, parent: tk.Widget, text: str, command, column: int) -> None:
        RoundedButton(
            parent,
            text=text,
            command=command,
            bg="#262933",
            fg=TEXT,
            active_bg="#343844",
            outline="#3A3E49",
            radius=10,
            height=28,
            padx=4,
            font=("Segoe UI", 10, "bold"),
            min_width=28,
        ).grid(row=0, column=column, padx=(0 if column == 0 else 4, 0))

    def _step_number(self, variable: tk.Variable, minimum: float, maximum: float, delta: float) -> None:
        try:
            current = float(variable.get())
        except (TypeError, ValueError, tk.TclError):
            current = minimum
        value = max(minimum, min(maximum, current + delta))
        variable.set(round(value, 3))

    def _flat_button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        row: int,
        column: int,
        bg: str,
        fg: str,
        padx=0,
        pady=0,
    ) -> RoundedButton:
        active_bg = ACCENT_HOVER if bg == ACCENT else self._lighten_color(bg)
        active_fg = "#061216" if bg == ACCENT else fg
        button = RoundedButton(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            active_bg=active_bg,
            active_fg=active_fg,
            outline="#353842",
            radius=15,
            height=44,
            padx=10,
            font=("Segoe UI", 9, "bold"),
        )
        button.grid(row=row, column=column, sticky="ew", padx=padx, pady=pady)
        return button

    @staticmethod
    def _lighten_color(color: str, amount: int = 18) -> str:
        color = color.lstrip("#")
        try:
            red = min(255, int(color[0:2], 16) + amount)
            green = min(255, int(color[2:4], 16) + amount)
            blue = min(255, int(color[4:6], 16) + amount)
        except (ValueError, IndexError):
            return "#2A2C34"
        return f"#{red:02X}{green:02X}{blue:02X}"

    def _route_point(self, parent: tk.Frame, row: int, number: str, label: str, variable: tk.StringVar, command) -> None:
        card = tk.Frame(parent, bg=SURFACE_ALT, highlightbackground="#292B34", highlightthickness=1)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        card.columnconfigure(2, weight=1)
        tk.Label(card, text=number, bg=SURFACE_ALT, fg=MUTED, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, padx=(10, 8), pady=10
        )
        tk.Label(card, text=label, bg=SURFACE_ALT, fg=MUTED, font=("Segoe UI", 8, "bold")).grid(
            row=0, column=1, sticky="w", pady=10
        )
        tk.Label(card, textvariable=variable, bg=SURFACE_ALT, fg=TEXT, font=("Segoe UI", 9, "bold"), anchor="w").grid(
            row=0, column=2, sticky="ew", padx=(8, 8), pady=10
        )
        set_button = RoundedButton(
            card,
            text="Set",
            command=command,
            bg="#123644",
            fg=ACCENT,
            active_bg="#17485A",
            active_fg=ACCENT_HOVER,
            outline="#1D6178",
            radius=11,
            height=30,
            padx=8,
            font=("Segoe UI", 8, "bold"),
            min_width=48,
        )
        set_button.grid(row=0, column=3, padx=(0, 10), pady=8)

    def _switch_row(self, parent: tk.Frame, row: int, label: str, variable: tk.BooleanVar | None, locked: bool = False) -> None:
        tk.Label(parent, text=label, bg=SURFACE, fg=TEXT, font=("Segoe UI", 10, "bold"), anchor="w").grid(
            row=row, column=0, sticky="w", pady=5
        )
        switch = tk.Canvas(
            parent,
            width=54,
            height=30,
            bg=SURFACE,
            bd=0,
            highlightthickness=0,
            cursor="arrow" if locked else "hand2",
        )

        def refresh() -> None:
            is_on = True if locked else bool(variable and variable.get())
            switch.delete("all")
            fill = GREEN if is_on else "#343741"
            knob = "#F4F6FA" if is_on else "#B7BDC7"
            switch.create_oval(1, 2, 29, 30, fill=fill, outline="")
            switch.create_oval(25, 2, 53, 30, fill=fill, outline="")
            switch.create_rectangle(15, 2, 39, 30, fill=fill, outline="")
            knob_left = 27 if is_on else 5
            switch.create_oval(knob_left, 6, knob_left + 20, 26, fill=knob, outline="")

        def toggle() -> None:
            if locked or variable is None:
                return
            variable.set(not variable.get())
            refresh()

        switch.bind("<Button-1>", lambda _event: toggle())
        switch.grid(row=row, column=1, sticky="e", pady=5)
        refresh()

    def _add_modern_stat_tile(self, parent: tk.Frame, row: int, column: int, label: str, variable: tk.StringVar) -> None:
        tile = tk.Frame(parent, bg=SURFACE_ALT, highlightbackground="#292B34", highlightthickness=1)
        tile.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 6, 6 if column == 0 else 0), pady=4)
        tile.columnconfigure(0, weight=1)
        tk.Label(tile, text=label.upper(), bg=SURFACE_ALT, fg=MUTED, font=("Segoe UI", 8, "bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 0)
        )
        tk.Label(tile, textvariable=variable, bg=SURFACE_ALT, fg=TEXT, font=("Segoe UI", 10, "bold")).grid(
            row=1, column=0, sticky="w", padx=10, pady=(0, 8)
        )

    def _on_mph_changed(self, value: str) -> None:
        try:
            mph = float(value)
        except ValueError:
            mph = float(self.mph.get())
        self.mph_value_text.set(f"{mph:.0f} mph")

    def _on_flight_speed_changed(self, value: str) -> None:
        try:
            mph = float(value)
        except ValueError:
            mph = float(self.flight_cruise_mph.get())
        self.flight_speed_text.set(f"{mph:.0f} mph")

    def _build_panel_tabs(self, parent: tk.Frame, row: int) -> None:
        tabs = tk.Frame(parent, bg="#252730")
        tabs.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 12))
        tabs.columnconfigure(0, weight=1)
        tabs.columnconfigure(1, weight=1)
        self.panel_tab_buttons = {}
        for column, (tab, label) in enumerate((("route", "Route"), ("misc", "Misc"))):
            button = RoundedButton(
                tabs,
                text=label,
                command=lambda value=tab: self._set_panel_tab(value),
                bg="#252730",
                fg=MUTED,
                active_bg="#323540",
                outline="#252730",
                radius=13,
                height=38,
                min_width=120,
            )
            button.grid(row=0, column=column, sticky="ew", padx=3, pady=3)
            self.panel_tab_buttons[tab] = button

    def _set_panel_tab(self, tab: str) -> None:
        self.panel_tab.set(tab)
        if self.route_page is not None:
            if tab == "route":
                self.route_page.grid()
            else:
                self.route_page.grid_remove()
        if self.misc_page is not None:
            if tab == "misc":
                self.misc_page.grid()
            else:
                self.misc_page.grid_remove()
        for value, button in self.panel_tab_buttons.items():
            selected = value == tab
            button.set_style(
                bg=ACCENT if selected else "#252730",
                fg="#061216" if selected else MUTED,
                active_bg=ACCENT_HOVER if selected else "#323540",
                active_fg="#061216" if selected else TEXT,
                outline=ACCENT if selected else "#252730",
            )

    def _build_misc_controls(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        flight = self._create_modern_section(parent, row=0, title="Flight Mode", pady=(0, 12))
        flight.columnconfigure(0, weight=1)
        flight.columnconfigure(1, weight=1)

        self._field_label(flight, 0, 0, "From")
        self._field_label(flight, 0, 1, "To")
        ttk.Combobox(flight, textvariable=self.flight_origin, values=AIRPORT_CHOICES, state="readonly").grid(
            row=1, column=0, sticky="ew", padx=(0, 6), pady=(4, 10)
        )
        ttk.Combobox(flight, textvariable=self.flight_destination, values=AIRPORT_CHOICES, state="readonly").grid(
            row=1, column=1, sticky="ew", padx=(6, 0), pady=(4, 10)
        )

        speed_row = tk.Frame(flight, bg=SURFACE)
        speed_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        speed_row.columnconfigure(0, weight=1)
        tk.Label(speed_row, text="Cruise", bg=SURFACE, fg=MUTED, font=("Segoe UI", 8, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(speed_row, textvariable=self.flight_speed_text, bg=SURFACE, fg=TEXT, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=1, sticky="e"
        )
        tk.Scale(
            speed_row,
            from_=120,
            to=620,
            orient="horizontal",
            resolution=5,
            showvalue=False,
            variable=self.flight_cruise_mph,
            command=self._on_flight_speed_changed,
            bg=SURFACE,
            fg=TEXT,
            activebackground=ACCENT,
            troughcolor="#3B3D47",
            highlightthickness=0,
            bd=0,
        ).grid(row=1, column=0, columnspan=2, sticky="ew")

        details = tk.Frame(flight, bg=SURFACE)
        details.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 10))
        details.columnconfigure(0, weight=1)
        details.columnconfigure(1, weight=1)
        details.columnconfigure(2, weight=1)
        self._field_label(details, 0, 0, "Taxi MPH")
        self._field_label(details, 0, 1, "Board Sec")
        self._field_label(details, 0, 2, "Smooth Sec")
        self._number_stepper(details, self.flight_taxi_mph, 5, 45, 1, row=1, column=0, width=5, padx=(0, 6), pady=(4, 0))
        self._number_stepper(details, self.flight_board_seconds, 0, 180, 5, row=1, column=1, width=5, padx=6, pady=(4, 0))
        self._number_stepper(
            details,
            self.flight_interval_seconds,
            1,
            30,
            1,
            row=1,
            column=2,
            width=5,
            padx=(6, 0),
            pady=(4, 0),
        )

        stats = tk.Frame(flight, bg=SURFACE)
        stats.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(2, 12))
        stats.columnconfigure(0, weight=1)
        stats.columnconfigure(1, weight=1)
        self._add_modern_stat_tile(stats, 0, 0, "ETA", self.flight_eta_text)
        self._add_modern_stat_tile(stats, 0, 1, "Distance", self.flight_distance_text)
        self._add_modern_stat_tile(stats, 1, 0, "Stage", self.flight_stage_text)
        self._add_modern_stat_tile(stats, 1, 1, "Cruise", self.flight_speed_text)

        actions = tk.Frame(flight, bg=SURFACE)
        actions.grid(row=5, column=0, columnspan=2, sticky="ew")
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self._flat_button(actions, "Start Flight", self._start_flight, row=0, column=0, bg=ACCENT, fg="#061216")
        self._flat_button(
            actions,
            "Stop",
            lambda: self._run_worker("Stop flight", self._stop_roadtrip),
            row=0,
            column=1,
            bg="#2D171D",
            fg=DANGER,
            padx=(8, 0),
        )

        utilities = self._create_modern_section(parent, row=1, title="Quick Tools", pady=(0, 12))
        utilities.columnconfigure(0, weight=1)
        utilities.columnconfigure(1, weight=1)
        self._flat_button(utilities, "Origin on Map", self._set_origin_airport_as_destination, row=0, column=0, bg=SURFACE_ALT, fg=TEXT)
        self._flat_button(utilities, "Destination on Map", self._set_destination_airport_as_destination, row=0, column=1, bg=SURFACE_ALT, fg=TEXT, padx=(8, 0))
        self._flat_button(utilities, "Set Start to Origin", self._set_start_to_origin_airport, row=1, column=0, bg=SURFACE_ALT, fg=TEXT, pady=(8, 0))
        self._flat_button(utilities, "Clear Route Line", self._clear_route_line, row=1, column=1, bg=SURFACE_ALT, fg=TEXT, padx=(8, 0), pady=(8, 0))

    def _build_controls(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        top = tk.Frame(parent, bg=SURFACE)
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 10))
        top.columnconfigure(0, weight=1)
        tk.Label(top, text="TetherLoc", bg=SURFACE, fg=TEXT, font=("Segoe UI", 18, "bold"), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(top, text="route controller", bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), anchor="w").grid(
            row=1, column=0, sticky="w", pady=(0, 8)
        )

        search = tk.Frame(top, bg=INPUT_BG, highlightbackground="#2B2D35", highlightthickness=1)
        search.grid(row=2, column=0, sticky="ew")
        search.columnconfigure(1, weight=1)
        tk.Label(search, text="Point", bg=INPUT_BG, fg=ACCENT, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, padx=(12, 8), pady=10
        )
        tk.Label(
            search,
            text="Map target",
            bg=INPUT_BG,
            fg=MUTED,
            font=("Segoe UI", 10),
            anchor="w",
        ).grid(row=0, column=1, sticky="ew", pady=10)

        self._build_panel_tabs(parent, row=1)

        self.route_page = tk.Frame(parent, bg=SURFACE)
        self.route_page.grid(row=2, column=0, sticky="ew")
        self.route_page.columnconfigure(0, weight=1)
        self.misc_page = tk.Frame(parent, bg=SURFACE)
        self.misc_page.grid(row=2, column=0, sticky="ew")
        self.misc_page.columnconfigure(0, weight=1)

        coord_section = self._create_modern_section(self.route_page, row=0, title="Custom Coordinates", pady=(0, 12))
        coord_section.columnconfigure(0, weight=1)
        coord_section.columnconfigure(1, weight=1)
        self._field_label(coord_section, 0, 0, "Latitude")
        self._field_label(coord_section, 0, 1, "Longitude")
        ttk.Entry(coord_section, textvariable=self.latitude).grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(4, 10))
        ttk.Entry(coord_section, textvariable=self.longitude).grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(4, 10))

        point_actions = tk.Frame(coord_section, bg=SURFACE)
        point_actions.grid(row=2, column=0, columnspan=2, sticky="ew")
        point_actions.columnconfigure(0, weight=1)
        point_actions.columnconfigure(1, weight=1)
        self._flat_button(point_actions, "Set Here", self._start_set_location, row=0, column=0, bg="#123644", fg=ACCENT)
        self._flat_button(
            point_actions,
            "Start Here",
            self._set_route_start_from_destination,
            row=0,
            column=1,
            bg=SURFACE_ALT,
            fg=TEXT,
            padx=(6, 0),
        )

        route_section = self._create_modern_section(self.route_page, row=1, title="Route", pady=(0, 12))
        route_section.columnconfigure(0, weight=1)
        self._route_point(route_section, 0, "1.", "Start", self.start_label, self._set_route_start_from_destination)
        self._route_point(route_section, 1, "2.", "Destination", self.destination_label, self._start_set_location)

        tk.Label(route_section, text="Options", bg=SURFACE, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w").grid(
            row=2, column=0, sticky="ew", pady=(10, 4)
        )
        speed_row = tk.Frame(route_section, bg=SURFACE)
        speed_row.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        speed_row.columnconfigure(0, weight=1)
        tk.Scale(
            speed_row,
            from_=1,
            to=150,
            orient="horizontal",
            resolution=1,
            showvalue=False,
            variable=self.mph,
            command=self._on_mph_changed,
            bg=SURFACE,
            fg=TEXT,
            activebackground=ACCENT,
            troughcolor="#3B3D47",
            highlightthickness=0,
            bd=0,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 12))
        tk.Label(speed_row, textvariable=self.mph_value_text, bg=SURFACE, fg=TEXT, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=1, sticky="e"
        )

        tk.Label(route_section, text="Speed Mode", bg=SURFACE, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w").grid(
            row=4, column=0, sticky="ew", pady=(4, 4)
        )
        selector = self._build_speed_mode_selector(route_section)
        selector.grid(row=5, column=0, sticky="ew", pady=(0, 10))

        switches = tk.Frame(route_section, bg=SURFACE)
        switches.grid(row=6, column=0, sticky="ew")
        switches.columnconfigure(0, weight=1)
        self._switch_row(switches, 0, "Movement realism", self.stop_signs)
        self._switch_row(switches, 1, "Follow roads", None, locked=True)

        timing = tk.Frame(route_section, bg=SURFACE)
        timing.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        timing.columnconfigure(0, weight=1)
        timing.columnconfigure(1, weight=1)
        self._field_label(timing, 0, 0, "Smooth Sec")
        self._field_label(timing, 0, 1, "Stop Delay")
        self._number_stepper(timing, self.interval_seconds, 0.5, 10, 0.5, row=1, column=0, padx=(0, 6), pady=(4, 0))
        self._number_stepper(timing, self.stop_seconds, 1, 10, 1, row=1, column=1, padx=(6, 0), pady=(4, 0))

        stats = tk.Frame(route_section, bg=SURFACE)
        stats.grid(row=8, column=0, sticky="ew", pady=(12, 12))
        stats.columnconfigure(0, weight=1)
        stats.columnconfigure(1, weight=1)
        self._add_modern_stat_tile(stats, 0, 0, "Speed", self.roadtrip_speed_text)
        self._add_modern_stat_tile(stats, 0, 1, "ETA", self.roadtrip_eta_text)
        self._add_modern_stat_tile(stats, 1, 0, "Distance", self.roadtrip_distance_text)
        self._add_modern_stat_tile(stats, 1, 1, "Stops", self.roadtrip_stops_text)

        route_actions = tk.Frame(route_section, bg=SURFACE)
        route_actions.grid(row=9, column=0, sticky="ew")
        route_actions.columnconfigure(0, weight=1)
        self._flat_button(route_actions, "Start Route", self._start_roadtrip, row=0, column=0, bg=ACCENT, fg="#061216")
        self._flat_button(
            route_actions,
            "Stop",
            lambda: self._run_worker("Stop roadtrip", self._stop_roadtrip),
            row=0,
            column=1,
            bg="#2D171D",
            fg=DANGER,
            padx=(8, 0),
        )

        self._build_misc_controls(self.misc_page)
        self._set_panel_tab(self.panel_tab.get())

        device_section = self._create_modern_section(parent, row=3, title="Device", pady=(0, 12))
        device_section.columnconfigure(0, weight=1)
        device_section.columnconfigure(1, weight=1)
        self.device_combo = ttk.Combobox(device_section, textvariable=self.selected_device, state="readonly")
        self.device_combo.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self._flat_button(
            device_section,
            "Refresh",
            lambda: self._run_worker("Refresh devices", self._refresh_devices),
            row=1,
            column=0,
            bg=SURFACE_ALT,
            fg=TEXT,
        )
        self._flat_button(
            device_section,
            "Setup Check",
            lambda: self._run_worker("Setup check", self._setup_check),
            row=1,
            column=1,
            bg=SURFACE_ALT,
            fg=TEXT,
            padx=(8, 0),
        )
        self._flat_button(
            device_section,
            "Prompt Dev Mode",
            self._start_enable_developer_mode,
            row=2,
            column=0,
            bg=SURFACE_ALT,
            fg=TEXT,
            pady=(8, 0),
        )
        self._flat_button(
            device_section,
            "Mount Image",
            self._start_mount_developer_image,
            row=2,
            column=1,
            bg=SURFACE_ALT,
            fg=TEXT,
            padx=(8, 0),
            pady=(8, 0),
        )

        session = self._create_modern_section(parent, row=4, title="Session", pady=(0, 12))
        for column in range(3):
            session.columnconfigure(column, weight=1)
        self._flat_button(session, "Clear", self._start_clear_location, row=0, column=0, bg="#2D171D", fg=DANGER)
        self._flat_button(session, "Lock", self._show_pause_help, row=0, column=1, bg=SURFACE_ALT, fg=LOCK, padx=6)
        self._flat_button(session, "Tunnel", self._stop_tunnel, row=0, column=2, bg=SURFACE_ALT, fg=TEXT)

        log_frame = self._create_modern_section(parent, row=5, title="Activity", pady=(0, 16))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_frame,
            width=36,
            height=9,
            wrap="word",
            state="disabled",
            font=("Cascadia Mono", 8),
            bg=LOG_BG,
            fg=LOG_FG,
            insertbackground=LOG_FG,
            relief="flat",
            padx=10,
            pady=10,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self._on_mph_changed(str(self.mph.get()))
        self._set_speed_mode(self.speed_mode.get())
        return

        parent.rowconfigure(3, weight=1)

        destination = self._create_section(parent, row=0, title="Destination")
        destination.columnconfigure(0, weight=1)
        destination.columnconfigure(1, weight=1)

        ttk.Label(destination, text="Latitude", style="Muted.Panel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(destination, text="Longitude", style="Muted.Panel.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Entry(destination, textvariable=self.latitude).grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(4, 10))
        ttk.Entry(destination, textvariable=self.longitude).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(4, 10))

        actions = ttk.Frame(destination, style="Panel.TFrame")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew")
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="Teleport", style="Accent.TButton", command=self._start_set_location).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(actions, text="Set Start", style="Secondary.TButton", command=self._set_route_start_from_destination).grid(
            row=0, column=1, sticky="ew", padx=(6, 0)
        )

        roadtrip = self._create_section(parent, row=1, title="Roadtrip")
        roadtrip.columnconfigure(0, weight=1)
        roadtrip.columnconfigure(1, weight=1)

        ttk.Label(roadtrip, text="Start", style="Muted.Panel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(roadtrip, textvariable=self.start_label, style="Panel.TLabel").grid(
            row=0, column=1, sticky="e", pady=(0, 10)
        )

        ttk.Label(roadtrip, text="Speed Mode", style="Muted.Panel.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w"
        )
        selector = self._build_speed_mode_selector(roadtrip)
        selector.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 10))

        ttk.Label(roadtrip, textvariable=self.mph_label_text, style="Muted.Panel.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Label(roadtrip, text="Smooth Sec", style="Muted.Panel.TLabel").grid(row=3, column=1, sticky="w", padx=(8, 0))
        self._number_stepper(roadtrip, self.mph, 1, 120, 1, row=4, column=0, padx=(0, 8), pady=(4, 10))
        self._number_stepper(roadtrip, self.interval_seconds, 0.5, 10, 0.5, row=4, column=1, padx=(8, 0), pady=(4, 10))

        ttk.Checkbutton(roadtrip, text="Pause at stop signs", variable=self.stop_signs).grid(
            row=5, column=0, sticky="w", pady=(0, 10)
        )
        self._number_stepper(roadtrip, self.stop_seconds, 1, 10, 1, row=5, column=1, sticky="e", pady=(0, 10))

        stats = ttk.Frame(roadtrip, style="Panel.TFrame")
        stats.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(2, 12))
        stats.columnconfigure(0, weight=1)
        stats.columnconfigure(1, weight=1)
        self._add_stat_tile(stats, 0, 0, "Speed", self.roadtrip_speed_text)
        self._add_stat_tile(stats, 0, 1, "ETA", self.roadtrip_eta_text)
        self._add_stat_tile(stats, 1, 0, "Distance", self.roadtrip_distance_text)
        self._add_stat_tile(stats, 1, 1, "Stops", self.roadtrip_stops_text)

        route_actions = ttk.Frame(roadtrip, style="Panel.TFrame")
        route_actions.grid(row=7, column=0, columnspan=2, sticky="ew")
        route_actions.columnconfigure(0, weight=1)
        route_actions.columnconfigure(1, weight=1)
        ttk.Button(route_actions, text="Start Roadtrip", style="Accent.TButton", command=self._start_roadtrip).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(
            route_actions,
            text="Stop",
            style="Danger.TButton",
            command=lambda: self._run_worker("Stop roadtrip", self._stop_roadtrip),
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        session = self._create_section(parent, row=2, title="Session")
        for column in range(3):
            session.columnconfigure(column, weight=1)
        ttk.Button(session, text="Clear", style="Danger.TButton", command=self._start_clear_location).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(session, text="🔒 Pause", style="Lock.TButton", command=self._show_pause_help).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Button(session, text="Tunnel", command=self._stop_tunnel).grid(row=0, column=2, sticky="ew", padx=(6, 0))

        log_frame = self._create_section(parent, row=3, title="Activity", sticky="nsew", pady=(0, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_frame,
            width=40,
            height=12,
            wrap="word",
            state="disabled",
            font=("Cascadia Mono", 9),
            bg=LOG_BG,
            fg=LOG_FG,
            insertbackground=LOG_FG,
            relief="flat",
            padx=12,
            pady=12,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self._set_speed_mode(self.speed_mode.get())

    def _create_section(
        self,
        parent: ttk.Frame,
        row: int,
        title: str,
        sticky: str = "ew",
        pady: tuple[int, int] = (0, 12),
    ) -> ttk.Frame:
        outer = tk.Frame(parent, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        outer.grid(row=row, column=0, sticky=sticky, pady=pady)
        outer.columnconfigure(0, weight=1)
        if "n" in sticky and "s" in sticky:
            outer.rowconfigure(1, weight=1)
        ttk.Label(outer, text=title, style="SectionTitle.Panel.TLabel").grid(
            row=0, column=0, sticky="ew", padx=14, pady=(12, 4)
        )
        body = ttk.Frame(outer, padding=(14, 6, 14, 14), style="Panel.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        return body

    def _build_speed_mode_selector(self, parent: ttk.Frame) -> tk.Frame:
        selector = tk.Frame(parent, bg="#252730", highlightthickness=0)
        selector.columnconfigure(0, weight=1)
        selector.columnconfigure(1, weight=1)
        self.speed_mode_buttons = {}
        for column, (mode, label) in enumerate((("auto", "Automatic"), ("set", "Set MPH"))):
            button = tk.Button(
                selector,
                text=label,
                bd=0,
                relief="flat",
                highlightthickness=0,
                padx=10,
                pady=8,
                cursor="hand2",
                font=("Segoe UI", 9, "bold"),
                command=lambda value=mode: self._set_speed_mode(value),
            )
            button.grid(row=0, column=column, sticky="ew", padx=3, pady=3)
            self.speed_mode_buttons[mode] = button
        return selector

    def _add_stat_tile(self, parent: ttk.Frame, row: int, column: int, label: str, variable: tk.StringVar) -> None:
        tile = tk.Frame(parent, bg=SURFACE_ALT, highlightbackground="#273645", highlightthickness=1)
        tile.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 6, 6 if column == 0 else 0), pady=4)
        tile.columnconfigure(0, weight=1)
        ttk.Label(tile, text=label.upper(), style="MetricName.Panel.TLabel").grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 0)
        )
        ttk.Label(tile, textvariable=variable, style="Metric.Panel.TLabel").grid(
            row=1, column=0, sticky="w", padx=10, pady=(0, 8)
        )

    def _set_speed_mode(self, mode: str) -> None:
        self.speed_mode.set(mode)
        self.mph_label_text.set("Set MPH" if mode == "set" else "Fallback MPH")
        for value, button in self.speed_mode_buttons.items():
            selected = value == mode
            button.configure(
                bg=ACCENT if selected else "#252730",
                fg="#061216" if selected else MUTED,
                activebackground=ACCENT_HOVER if selected else "#323540",
                activeforeground="#061216" if selected else TEXT,
            )

    def _bind_side_scroll_widgets(self, widget: tk.Widget) -> None:
        widget.bind("<MouseWheel>", self._on_side_mousewheel)
        widget.bind("<Button-4>", self._on_side_mousewheel)
        widget.bind("<Button-5>", self._on_side_mousewheel)
        for child in widget.winfo_children():
            self._bind_side_scroll_widgets(child)

    def _on_side_mousewheel(self, event: tk.Event) -> str:
        if not self.side_canvas:
            return "break"
        if getattr(event, "num", None) == 4:
            units = -3
        elif getattr(event, "num", None) == 5:
            units = 3
        else:
            units = -3 if getattr(event, "delta", 0) > 0 else 3
        self.side_canvas.yview_scroll(units, "units")
        return "break"

    def _warm_map_cache_loop(self) -> None:
        if self.map_widget and decimal_to_osm and not self._warming_map_cache:
            self._warming_map_cache = True
            threading.Thread(target=self._warm_adjacent_zoom_tiles, name="map-cache-warmer", daemon=True).start()
        if self.map_widget:
            self.after(1800, self._warm_map_cache_loop)

    def _warm_adjacent_zoom_tiles(self) -> None:
        try:
            widget = self.map_widget
            if not widget:
                return
            center = widget.get_position()
            current_zoom = round(widget.zoom)
            warmed_tiles = 0
            for zoom in (current_zoom - 1, current_zoom, current_zoom + 1):
                if zoom < widget.min_zoom or zoom > widget.max_zoom:
                    continue
                center_x, center_y = decimal_to_osm(center[0], center[1], zoom)
                half_x = math.ceil(widget.width / widget.tile_size / 2)
                half_y = math.ceil(widget.height / widget.tile_size / 2)
                max_index = (2**zoom) - 1
                for x in range(max(0, math.floor(center_x) - half_x), min(max_index, math.floor(center_x) + half_x) + 1):
                    for y in range(max(0, math.floor(center_y) - half_y), min(max_index, math.floor(center_y) + half_y) + 1):
                        if widget.get_tile_image_from_cache(zoom, x, y) is False:
                            widget.request_image(zoom, x, y)
                            warmed_tiles += 1
                            if warmed_tiles >= 60:
                                return
        finally:
            self._warming_map_cache = False

    def _setup_check(self) -> None:
        ok, message = self.client.check_apple_mobile_device_service()
        self._log(message)
        result = self.client.check_pymobiledevice(emit=self._log)
        if result.ok and ok:
            self._set_status("Setup looks ready")
        elif result.ok:
            self._set_status("Install or start iTunes drivers")
        else:
            self._set_status("Install pymobiledevice3")
        self._refresh_devices()

    def _refresh_devices(self) -> None:
        devices = self.client.list_devices(emit=self._log)
        self.after(0, lambda: self._apply_devices(devices))

    def _apply_devices(self, devices: list[Device], announce: bool = True) -> None:
        self.devices = devices
        values = [device.display_name for device in devices]
        if self.device_combo is not None:
            self.device_combo.configure(values=values)
        if values and self.selected_device.get() not in values:
            self.selected_device.set(values[0])
        if devices:
            self._set_connection_state(True)
            if announce:
                self._set_status(f"{len(devices)} device(s) found")
            self._maybe_prompt_developer_mode(devices)
        else:
            self._set_connection_state(False)
            if announce:
                self._set_status("No device found")
            self.developer_mode_prompted_devices.clear()
            if self.main_ready:
                self._return_to_setup_after_disconnect()

    def _maybe_prompt_developer_mode(self, devices: list[Device]) -> None:
        if self.developer_mode_prompting:
            return
        for device in devices:
            if device.ios_major is not None and device.ios_major < 16:
                continue
            key = device.identifier or device.display_name
            if key in self.developer_mode_prompted_devices:
                continue
            self.developer_mode_prompted_devices.add(key)
            self.developer_mode_prompting = True
            threading.Thread(
                target=lambda device=device: self._auto_prompt_developer_mode(device),
                name="developer-mode-prompt",
                daemon=True,
            ).start()
            return

    def _auto_prompt_developer_mode(self, device: Device) -> None:
        try:
            message = self.client.prompt_developer_mode(device, emit=self._log)
            self._log(message)
            if "already enabled" not in message.lower():
                self._set_status("Check iPhone for Developer Mode")
        except Exception as exc:
            message = clean_command_output(str(exc)) or "Developer Mode prompt failed."
            self._log(f"Developer Mode prompt skipped: {message}")
        finally:
            self.developer_mode_prompting = False

    def _set_connection_state(self, connected: bool) -> None:
        self.connection_text.set("Connected" if connected else "Disconnected")
        if self.connection_label is not None:
            if connected:
                self.connection_label.configure(bg="#0D1C14", fg=GREEN)
                parent = self.connection_label.master
                if parent is not None:
                    parent.configure(bg="#0D1C14", highlightbackground="#1F7D48")
            else:
                self.connection_label.configure(bg="#15100A", fg=WARNING)
                parent = self.connection_label.master
                if parent is not None:
                    parent.configure(bg="#15100A", highlightbackground="#6B4917")

    def _map_clicked(self, coords: tuple[float, float]) -> None:
        self._set_destination(coords)

    def _set_destination(self, coords: tuple[float, float]) -> None:
        lat, lon = coords
        self.latitude.set(f"{lat:.6f}")
        self.longitude.set(f"{lon:.6f}")
        self._refresh_destination_display((lat, lon))
        self._set_destination_marker((lat, lon))

    def _refresh_destination_display(self, coords: tuple[float, float]) -> None:
        formatted = self._format_pair(coords)
        self.destination_label.set(formatted)
        self.route_summary_coords.set(formatted)

    def _set_destination_marker(self, coords: tuple[float, float]) -> None:
        if not self.map_widget:
            return
        if self.destination_marker:
            self.destination_marker.delete()
        self.destination_marker = self.map_widget.set_marker(coords[0], coords[1], text="Destination")

    def _set_start_marker(self, coords: tuple[float, float]) -> None:
        if not self.map_widget:
            return
        if self.start_marker:
            self.start_marker.delete()
        self.start_marker = self.map_widget.set_marker(coords[0], coords[1], text="Start")

    def _set_route_path(self, coordinates: list[tuple[float, float]]) -> None:
        if not self.map_widget:
            return
        if self.route_path:
            self.route_path.delete()
        display_coordinates = self._thin_coordinates(coordinates, limit=700)
        if len(display_coordinates) >= 2:
            self.route_path = self.map_widget.set_path(display_coordinates, color=ACCENT, width=4)

    def _set_route_start_from_destination(self) -> None:
        coords = self._destination_coords()
        self._refresh_destination_display(coords)
        self._apply_route_start(coords)
        self._log(f"Roadtrip start set to {self._format_pair(coords)}")

    def _apply_route_start(self, coords: tuple[float, float]) -> None:
        self.route_start = coords
        self.start_label.set(self._format_pair(coords))
        self._set_start_marker(coords)

    def _start_enable_developer_mode(self) -> None:
        device = self._require_device()
        self._run_worker("Prompt Developer Mode", lambda: self._enable_developer_mode(device))

    def _enable_developer_mode(self, device: Device | None) -> None:
        message = self.client.prompt_developer_mode(device, emit=self._log)
        self._log(message)
        self._set_status("Developer Mode ready" if "already enabled" in message.lower() else "Check iPhone")

    def _start_mount_developer_image(self) -> None:
        device = self._current_device()
        self._run_worker("Mount Developer Image", lambda: self._mount_developer_image(device))

    def _mount_developer_image(self, device: Device | None) -> None:
        result = self.client.mount_developer_image(device, emit=self._log)
        if not result.ok or is_developer_image_mount_failure(result.output):
            raise RuntimeError(format_location_command_error(result.output, "Developer image mount failed."))
        self._set_status("Developer image mounted" if result.ok else "Developer image mount failed")

    def _start_set_location(self) -> None:
        device = self._require_device()
        lat, lon = self._destination_coords()
        self._refresh_destination_display((lat, lon))
        self._run_worker("Set location", lambda: self._set_location(device, lat, lon))

    def _set_location(self, device: Device, lat: float, lon: float) -> None:
        message = self.client.set_location(device, lat, lon, emit=self._log)
        self.after(0, lambda: self._apply_route_start((lat, lon)))
        self._log(message)
        self._set_status("Location active")

    def _start_roadtrip(self) -> None:
        device = self._require_device()
        start = self.route_start
        destination = self._destination_coords()
        self._refresh_destination_display(destination)
        mph = float(self.mph.get())
        interval = float(self.interval_seconds.get())
        auto_speed = self.speed_mode.get() == "auto"
        stop_signs = bool(self.stop_signs.get())
        stop_seconds = float(self.stop_seconds.get())
        self._set_roadtrip_stats("Planning...", "Planning...", "--", "--")
        self._run_worker(
            "Roadtrip",
            lambda: self._roadtrip(device, start, destination, mph, interval, auto_speed, stop_signs, stop_seconds),
        )

    def _airport_coords(self, airport_label: str) -> tuple[float, float]:
        code = AIRPORT_LABEL_TO_CODE.get(airport_label)
        if not code:
            raise ValueError("Choose a valid airport.")
        _label, lat, lon = AIRPORTS[code]
        return lat, lon

    def _set_origin_airport_as_destination(self) -> None:
        coords = self._airport_coords(self.flight_origin.get())
        self._set_destination(coords)
        if self.map_widget:
            self.map_widget.set_position(coords[0], coords[1])

    def _set_destination_airport_as_destination(self) -> None:
        coords = self._airport_coords(self.flight_destination.get())
        self._set_destination(coords)
        if self.map_widget:
            self.map_widget.set_position(coords[0], coords[1])

    def _set_start_to_origin_airport(self) -> None:
        coords = self._airport_coords(self.flight_origin.get())
        self._apply_route_start(coords)
        if self.map_widget:
            self.map_widget.set_position(coords[0], coords[1])
        self._log(f"Start set to {self.flight_origin.get()}")

    def _clear_route_line(self) -> None:
        if self.route_path:
            self.route_path.delete()
            self.route_path = None
        self._set_roadtrip_stats("--", "--", "--", "--")
        self._set_flight_stats("--", "--", "Ready")
        self._set_status("Route line cleared")

    def _start_flight(self) -> None:
        device = self._require_device()
        origin = self._airport_coords(self.flight_origin.get())
        destination = self._airport_coords(self.flight_destination.get())
        cruise_mph = float(self.flight_cruise_mph.get())
        taxi_mph = float(self.flight_taxi_mph.get())
        boarding_seconds = float(self.flight_board_seconds.get())
        interval = float(self.flight_interval_seconds.get())
        self._set_destination(destination)
        self._apply_route_start(origin)
        self._set_flight_stats("Planning...", "Planning...", "Boarding")
        self._run_worker(
            "Flight mode",
            lambda: self._flight(device, origin, destination, cruise_mph, taxi_mph, boarding_seconds, interval),
        )

    def _flight(
        self,
        device: Device,
        origin: tuple[float, float],
        destination: tuple[float, float],
        cruise_mph: float,
        taxi_mph: float,
        boarding_seconds: float,
        interval: float,
    ) -> None:
        self._log(f"Flight mode: {self.flight_origin.get()} to {self.flight_destination.get()}")
        plan = build_flight_plan(
            origin,
            destination,
            cruise_mph=cruise_mph,
            taxi_mph=taxi_mph,
            sample_interval_seconds=interval,
            boarding_seconds=boarding_seconds,
        )
        miles = plan.distance_meters / 1609.344
        self.after(0, lambda: self._set_route_path(plan.coordinates))
        self.after(
            0,
            lambda: self._set_flight_stats(
                self._format_duration(plan.duration_seconds),
                f"{miles:.0f} mi",
                "In flight",
            ),
        )
        self._log(
            f"Flight plan: boarding {boarding_seconds:g}s, taxi {taxi_mph:g} MPH, cruise {cruise_mph:g} MPH, "
            f"{miles:.0f} miles, ETA {self._format_duration(plan.duration_seconds)}"
        )
        self._log(f"Smoothness: one GPS point every {interval:g} second(s)")
        message = self.client.play_gpx_route(device, plan.gpx_path, emit=self._log)
        self.after(0, lambda: self._apply_route_start(destination))
        self._log(message)
        self._set_status("Flight active")

    def _roadtrip(
        self,
        device: Device,
        start: tuple[float, float],
        destination: tuple[float, float],
        mph: float,
        interval: float,
        auto_speed: bool,
        stop_signs: bool,
        stop_seconds: float,
    ) -> None:
        self._log(f"Routing roads from {self._format_pair(start)} to {self._format_pair(destination)}")
        route = fetch_road_route_details(start, destination)
        stops = []
        if stop_signs:
            try:
                self._log("Looking for stop signs near the route...")
                stop_nodes = fetch_stop_signs_near_route(route.coordinates)
                stops = match_stop_signs_to_route(route.coordinates, stop_nodes, dwell_seconds=stop_seconds)
                self._log(f"Stop signs: matched {len(stops)} pause point(s)")
            except Exception as exc:
                self._log(f"Stop sign lookup skipped: {exc}")
        segment_speeds = route.segment_speeds_mps if auto_speed else None
        plan = build_route_plan(route.coordinates, mph, interval, segment_speeds_mps=segment_speeds, stops=stops)
        miles = plan.distance_meters / 1609.344
        minutes = plan.duration_seconds / 60
        self.after(0, lambda: self._set_route_path(plan.coordinates))
        average_mph = miles / (plan.duration_seconds / 3600) if plan.duration_seconds else 0
        if plan.used_auto_speed:
            speed_label = f"Auto avg {average_mph:.1f} MPH"
        elif auto_speed:
            speed_label = f"Fallback {mph:.1f} MPH"
        else:
            speed_label = f"Set {mph:.1f} MPH"
        self.after(
            0,
            lambda: self._set_roadtrip_stats(
                speed_label,
                self._format_duration(plan.duration_seconds),
                f"{miles:.2f} mi",
                str(plan.stop_count),
            ),
        )
        self._log(f"Roadtrip route: {miles:.2f} miles, about {minutes:.1f} minutes with {speed_label}")
        if auto_speed:
            if plan.used_auto_speed:
                self._log("Auto speed: using road-speed estimates from the router")
            else:
                self._log("Auto speed: router speed data unavailable, using fallback MPH")
        if plan.stop_count:
            self._log(f"Stops: pausing {stop_seconds:g} second(s) at each matched stop sign")
        self._log(f"Smoothness: one GPS point every {interval:g} second(s)")
        self._log(f"Road distance from router: {route.distance_meters / 1609.344:.2f} miles")
        message = self.client.play_gpx_route(device, plan.gpx_path, emit=self._log)
        self.after(0, lambda: self._apply_route_start(destination))
        self._log(message)
        self._set_status("Roadtrip active")

    def _start_clear_location(self) -> None:
        device = self._require_device()
        self._run_worker("Clear location", lambda: self._clear_location(device))

    def _clear_location(self, device: Device) -> None:
        result = self.client.clear_location(device, emit=self._log)
        if not result.ok:
            raise RuntimeError(format_location_command_error(result.output, "Clear location failed."))
        self._set_status("Location cleared" if result.ok else "Clear failed")

    def _stop_tunnel(self) -> None:
        self.client.stop_location_hold()
        self.client.stop_tunnel()
        self._log("Stopped local tunnel and location hold.")
        self._set_status("Stopped")

    def _stop_roadtrip(self) -> None:
        self.client.stop_location_hold()
        self._log("Stopped route playback. Press Clear Location if the simulated location stays active.")
        self.after(0, lambda: self.roadtrip_eta_text.set("Stopped"))
        self.after(0, lambda: self.flight_stage_text.set("Stopped"))
        self._set_status("Playback stopped")

    def _set_roadtrip_stats(self, speed: str, eta: str, distance: str, stops: str) -> None:
        self.roadtrip_speed_text.set(speed)
        self.roadtrip_eta_text.set(eta)
        self.roadtrip_distance_text.set(distance)
        self.roadtrip_stops_text.set(stops)
        self.route_summary_meta.set(f"{distance}  |  ETA {eta}")

    def _set_flight_stats(self, eta: str, distance: str, stage: str) -> None:
        self.flight_eta_text.set(eta)
        self.flight_distance_text.set(distance)
        self.flight_stage_text.set(stage)
        self.route_summary_meta.set(f"{distance}  |  ETA {eta}")

    def _show_pause_help(self) -> None:
        messagebox.showinfo(
            "Pause Location",
            "To pause at the current simulated spot:\n\n"
            "1. Move there with Teleport or Roadtrip.\n"
            "2. On the iPhone, open Settings > Privacy & Security > Developer Mode.\n"
            "3. Turn Developer Mode off.\n"
            "4. Unplug the iPhone.\n\n"
            "When you want normal GPS again, turn Developer Mode back on if needed, reconnect, "
            "and press Clear Location, or toggle Location Services on the phone.",
        )

    def _destination_coords(self) -> tuple[float, float]:
        return float(self.latitude.get()), float(self.longitude.get())

    def _current_device(self) -> Device | None:
        selected = self.selected_device.get()
        for device in self.devices:
            if device.display_name == selected:
                return device
        return self.devices[0] if self.devices else None

    def _require_device(self) -> Device:
        device = self._current_device()
        if not device:
            raise RuntimeError("Connect an iPhone or iPad, trust this computer, then refresh devices.")
        return device

    def _run_worker(self, title: str, target) -> None:
        self._set_status(f"{title}...")

        def wrapped() -> None:
            try:
                target()
            except Exception as exc:
                message = clean_command_output(str(exc)) or "Something went wrong."
                self._log(f"Error: {message}")
                self._set_status("Needs attention")
                self.after(0, lambda: messagebox.showerror("TetherLoc", message))

        threading.Thread(target=wrapped, name=f"worker-{title}", daemon=True).start()

    def _log(self, message: str) -> None:
        if message:
            self.log_queue.put(message)

    def _set_status(self, message: str) -> None:
        self.after(0, lambda: self.status.set(message))

    def _drain_log_queue(self) -> None:
        if not self.log_text:
            self.after(100, self._drain_log_queue)
            return
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"{message}\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(100, self._drain_log_queue)

    def _on_close(self) -> None:
        self._stop_device_monitor()
        self.client.close()
        self.destroy()

    @staticmethod
    def _format_pair(coords: tuple[float, float]) -> str:
        return f"{coords[0]:.5f}, {coords[1]:.5f}"

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total_seconds = max(0, int(round(seconds)))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes:02d}m"
        if minutes:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"

    @staticmethod
    def _thin_coordinates(coordinates: list[tuple[float, float]], limit: int) -> list[tuple[float, float]]:
        if len(coordinates) <= limit:
            return coordinates
        step = max(1, math.ceil(len(coordinates) / limit))
        thinned = coordinates[::step]
        if thinned[-1] != coordinates[-1]:
            thinned.append(coordinates[-1])
        return thinned


def main() -> None:
    app = TetherLocApp()
    app.mainloop()
