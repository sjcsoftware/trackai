"""Persisted preferences and XDG paths (port of Settings.swift).

macOS keeps these in UserDefaults; on Linux they live in a plain JSON file
under ``$XDG_CONFIG_HOME/trackai``.
"""

from __future__ import annotations

import json
import copy
import os
import shutil
import sys

APP_NAME = "trackai"

# Menu-bar colouring metrics.
METRIC_DAILY = "daily"
METRIC_SESSION = "session"
METRIC_WEEKLY = "weekly"

COLOR_METRICS = [
    (METRIC_DAILY, "Daily usage (vs. 30-day peak)"),
    (METRIC_SESSION, "Session (5h) limit"),
    (METRIC_WEEKLY, "Weekly limit"),
]

# RGB triplets matching the macOS system colours the Swift build uses.
COLOR_GREEN = (0.204, 0.780, 0.349)
COLOR_ORANGE = (1.000, 0.584, 0.000)
COLOR_RED = (1.000, 0.231, 0.188)
COLOR_GRAY = (0.557, 0.557, 0.576)


def _xdg(env_var, fallback):
    base = os.environ.get(env_var, "")
    if not base:
        base = os.path.join(os.path.expanduser("~"), fallback)
    return os.path.join(base, APP_NAME)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config")
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache")
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share")

SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
API_CACHE_FILE = os.path.join(CACHE_DIR, "api-cache.json")
ICON_DIR = os.path.join(CACHE_DIR, "icons")
PID_FILE = os.path.join(CACHE_DIR, "trackai.pid")
LOG_FILE = os.path.join(CACHE_DIR, "trackai.log")
AUTOSTART_FILE = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"),
    "autostart", "trackai.desktop",
)

DEFAULTS = {
    "warnThreshold": 50.0,
    "critThreshold": 80.0,
    "colorMetric": METRIC_DAILY,
    "transparency": 0.65,
    "opaqueBackground": False,
    "defaultAccountID": "",
    "extraConfigDirs": [],
    "codexHome": "",
    "enabledProviders": ["claude", "codex"],
    "providerOrder": ["claude", "codex"],
    "iconProviders": ["claude", "codex"],
    "iconMode": "average",
    "refreshInterval": 120.0,
    "showPercentInMenuBar": False,
    "launchAtLogin": False,
}


def ensure_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass


def launcher_command():
    # type: () -> str
    """Best command line for relaunching the app (used by the autostart entry)."""
    explicit = os.environ.get("TRACKAI_CLI")
    if explicit and os.access(explicit, os.X_OK):
        return desktop_quote(explicit) + " start"
    for candidate in (
        os.path.join(os.path.expanduser("~"), ".local", "bin", APP_NAME),
        "/usr/local/bin/" + APP_NAME,
        "/usr/bin/" + APP_NAME,
    ):
        if os.access(candidate, os.X_OK):
            return desktop_quote(candidate) + " start"
    found = shutil.which(APP_NAME)
    if found:
        return desktop_quote(found) + " start"
    # Last resort: re-run this very package with the interpreter that loaded it.
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return "{} -c \"import sys; sys.path.insert(0, {!r}); from trackai.__main__ import main; sys.exit(main())\"".format(
        sys.executable, package_root
    )


def _field(key):
    """Build a property backed by the settings dict that saves and notifies."""

    def getter(self):
        return self._values[key]

    def setter(self, value):
        if self._values.get(key) == value:
            return
        self._values[key] = value
        self.save()
        if key == "launchAtLogin":
            self.apply_launch_at_login()
        self.notify()

    return property(getter, setter)


class Settings(object):
    """Singleton preference store. Use ``Settings.shared()``."""

    _instance = None

    @classmethod
    def shared(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._values = dict(DEFAULTS)
        self._values["extraConfigDirs"] = []
        self._listeners = []
        self.load()

    def snapshot(self):
        snapshot = copy.copy(self)
        snapshot._values = copy.deepcopy(self._values)
        snapshot._listeners = []
        return snapshot

    codex_home = _field("codexHome")
    enabled_providers = _field("enabledProviders")
    provider_order = _field("providerOrder")
    icon_providers = _field("iconProviders")
    icon_mode = _field("iconMode")

    # -- persistence -------------------------------------------------------

    def load(self):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
        except (OSError, ValueError):
            return
        if not isinstance(stored, dict):
            return
        for key, default in DEFAULTS.items():
            if key not in stored:
                continue
            value = stored[key]
            if isinstance(default, bool):
                if isinstance(value, bool):
                    self._values[key] = value
            elif isinstance(default, float):
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self._values[key] = float(value)
            elif isinstance(default, list):
                if isinstance(value, list):
                    self._values[key] = [str(v) for v in value]
            elif isinstance(default, str):
                if isinstance(value, str):
                    self._values[key] = value

    def save(self):
        ensure_dir(CONFIG_DIR)
        tmp = SETTINGS_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._values, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, SETTINGS_FILE)
        except OSError:
            pass

    # -- observation -------------------------------------------------------

    def add_listener(self, callback):
        self._listeners.append(callback)

    def notify(self):
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:      # a broken observer must not break settings
                pass

    # -- fields ------------------------------------------------------------

    warn_threshold = _field("warnThreshold")
    crit_threshold = _field("critThreshold")
    color_metric = _field("colorMetric")
    transparency = _field("transparency")
    opaque_background = _field("opaqueBackground")
    default_account_id = _field("defaultAccountID")
    extra_config_dirs = _field("extraConfigDirs")
    refresh_interval = _field("refreshInterval")
    show_percent_in_menu_bar = _field("showPercentInMenuBar")
    launch_at_login = _field("launchAtLogin")

    # -- derived -----------------------------------------------------------

    def usage_color(self, percent):
        # type: (float) -> tuple
        if percent < self.warn_threshold:
            return COLOR_GREEN
        if percent < self.crit_threshold:
            return COLOR_ORANGE
        return COLOR_RED

    def usage_color_name(self, percent):
        # type: (float) -> str
        if percent < self.warn_threshold:
            return "green"
        if percent < self.crit_threshold:
            return "orange"
        return "red"

    @property
    def panel_alpha(self):
        # type: () -> float
        """Background opacity for the stats panel (1.0 = fully opaque)."""
        if self.opaque_background:
            return 1.0
        return max(0.35, min(1.0, 1.0 - 0.6 * float(self.transparency)))

    # -- launch at login ---------------------------------------------------

    def apply_launch_at_login(self):
        if self.launch_at_login:
            ensure_dir(os.path.dirname(AUTOSTART_FILE))
            entry = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=trackai\n"
                "Comment=Claude Code usage monitor\n"
                "Exec={exec}\n"
                "Icon=trackai\n"
                "Terminal=false\n"
                "X-GNOME-Autostart-enabled=true\n"
                "X-GNOME-Autostart-Delay=5\n"
            ).format(exec=launcher_command())
            try:
                with open(AUTOSTART_FILE, "w", encoding="utf-8") as fh:
                    fh.write(entry)
            except OSError:
                pass
        else:
            try:
                os.remove(AUTOSTART_FILE)
            except OSError:
                pass


def color_metric_label(metric):
    # type: (str) -> str
    for key, label in COLOR_METRICS:
        if key == metric:
            return label
    return metric


def rgba_css(rgb, alpha=1.0):
    # type: (tuple, float) -> str
    return "rgba({}, {}, {}, {:.3f})".format(
        int(round(rgb[0] * 255)), int(round(rgb[1] * 255)), int(round(rgb[2] * 255)), alpha
    )


def desktop_quote(value):
    """Quote one argument for the freedesktop Exec grammar (not a shell)."""
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
