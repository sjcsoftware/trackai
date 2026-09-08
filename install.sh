#!/bin/bash
# trackai installer — https://github.com/sjcsoftware/trackai
# Usage: curl -fsSL https://raw.githubusercontent.com/sjcsoftware/trackai/main/install.sh | bash
#
# One command for both systems: this script detects macOS or Linux and installs
# the matching build — the SwiftUI menu bar app, or the GTK tray app.
set -euo pipefail

REPO="sjcsoftware/trackai"
# Branch or tag the payloads are fetched from. Override to install from a branch:
#   curl -fsSL .../<branch>/install.sh | TRACKAI_REF=<branch> bash
REF="${TRACKAI_REF:-main}"
PYTHON="${TRACKAI_PYTHON:-/usr/bin/python3}"
MAC_ZIP="TrackAI.zip"
LINUX_TARBALL="trackai-linux.tar.gz"

APP_DEST="/Applications/TrackAI.app"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
LINUX_APP_DEST="$DATA_HOME/trackai"
ICON_ROOT="$DATA_HOME/icons/hicolor"
DESKTOP_DIR="$DATA_HOME/applications"

have() { command -v "$1" >/dev/null 2>&1; }

case "$(uname -s)" in
    Darwin) PLATFORM="macos" ;;
    Linux)  PLATFORM="linux" ;;
    *) echo "trackai supports macOS and Linux only." >&2; exit 1 ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# A checkout is only a checkout when this script is a real file on disk that
# sits next to the sources; `curl | bash` always downloads instead.
SELF_DIR=""
if [ -f "${BASH_SOURCE[0]:-}" ]; then
    SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
is_checkout() {
    [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/bin/trackai" ] && [ -d "$SELF_DIR/linux/src/trackai" ]
}

# Installs the platform CLI from $1 and reports the path it landed in.
install_cli() {
    local cli_src="$1" dir installed=""
    local candidates=()
    if [ "$PLATFORM" = "macos" ]; then
        candidates=(/opt/homebrew/bin /usr/local/bin)
    else
        mkdir -p "$HOME/.local/bin"
        candidates=("$HOME/.local/bin")
    fi
    for dir in "${candidates[@]}"; do
        if [ -d "$dir" ] && [ -w "$dir" ]; then
            install -m 0755 "$cli_src" "$dir/trackai"
            installed="$dir/trackai"
            break
        fi
    done
    if [ -z "$installed" ]; then
        mkdir -p "$HOME/.local/bin"
        install -m 0755 "$cli_src" "$HOME/.local/bin/trackai"
        installed="$HOME/.local/bin/trackai"
        case ":$PATH:" in
            *":$HOME/.local/bin:"*) ;;
            # stderr, so it never pollutes the path this function returns.
            *) echo "note: add \$HOME/.local/bin to your PATH to use the 'trackai' command." >&2 ;;
        esac
    fi
    case ":$PATH:" in
        *":$(dirname "$installed"):"*) ;;
        *) echo "note: add $(dirname "$installed") to PATH, or use the full CLI path below." >&2 ;;
    esac
    echo "$installed"
}

download() {
    local name="$1" out="$2"
    # The chosen ref is authoritative: never silently install an older release
    # or a payload from another branch when testing TRACKAI_REF.
    local url_raw="https://raw.githubusercontent.com/$REPO/$REF/dist/$name"
    curl --retry 3 --connect-timeout 15 -fsSL "$url_raw" -o "$out" \
        || { echo "Download failed ($name from $REF)." >&2; exit 1; }
}

# =============================================================== macOS install

install_macos() {
    local zip="$TMP/$MAC_ZIP"
    if is_checkout && [ -f "$SELF_DIR/dist/$MAC_ZIP" ]; then
        echo "Installing from local checkout: $SELF_DIR"
        cp "$SELF_DIR/dist/$MAC_ZIP" "$zip"
    else
        download "$MAC_ZIP" "$zip"
    fi

    # Quit a running copy before replacing it.
    osascript -e 'quit app "TrackAI"' >/dev/null 2>&1 || true

    ditto -x -k "$zip" "$TMP/extracted"
    [ -d "$TMP/extracted/TrackAI.app" ] || { echo "Downloaded archive looks wrong." >&2; exit 1; }
    rm -rf "$APP_DEST"
    mv "$TMP/extracted/TrackAI.app" "$APP_DEST"
    xattr -dr com.apple.quarantine "$APP_DEST" 2>/dev/null || true

    # The CLI ships inside the bundle; a checkout has the newer copy.
    local cli_src="$APP_DEST/Contents/Resources/trackai-cli"
    if is_checkout; then
        cli_src="$SELF_DIR/bin/trackai"
    fi
    CLI_INSTALLED="$(install_cli "$cli_src")"
    INSTALL_SUMMARY="$APP_DEST"
}

# =============================================================== Linux install

GI_OK='import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk'
CAIRO_OK='import cairo; import gi; gi.require_foreign("cairo")'
IND_OK='import gi
ok = False
for name in ("AyatanaAppIndicator3", "AppIndicator3"):
    try:
        gi.require_version(name, "0.1")
        __import__("gi.repository." + name)
        ok = True
        break
    except Exception:
        pass
raise SystemExit(0 if ok else 1)'

py_has() { "$PYTHON" -c "$1" >/dev/null 2>&1; }

missing_deps() {
    local missing=()
    [ -x "$PYTHON" ] || missing+=("python3")
    py_has "$GI_OK" || missing+=("python3-gi" "gir1.2-gtk-3.0")
    py_has "$CAIRO_OK" || missing+=("python3-gi-cairo" "python3-cairo")
    py_has "$IND_OK" || missing+=("indicator")
    printf '%s\n' "${missing[@]:-}"
}

indicator_package() {
    # 22.04+ ships the Ayatana fork; 20.04 has both, preferring ayatana.
    if have apt-cache && apt-cache show gir1.2-ayatanaappindicator3-0.1 >/dev/null 2>&1; then
        echo "gir1.2-ayatanaappindicator3-0.1"
    else
        echo "gir1.2-appindicator3-0.1"
    fi
}

install_deps() {
    local wanted=() pkg
    while read -r pkg; do
        [ -n "$pkg" ] || continue
        if [ "$pkg" = "indicator" ]; then
            wanted+=("$(indicator_package)")
        else
            wanted+=("$pkg")
        fi
    done < <(missing_deps)

    if [ ${#wanted[@]} -eq 0 ]; then
        echo "✓ Dependencies already present"
        return 0
    fi

    if ! have apt-get; then
        echo "Missing dependencies: ${wanted[*]}" >&2
        echo "Install the equivalents for your distribution, then re-run this installer." >&2
        echo "  Fedora:  sudo dnf install python3-gobject gtk3 libappindicator-gtk3 python3-cairo" >&2
        echo "  Arch:    sudo pacman -S python-gobject gtk3 libappindicator-gtk3 python-cairo" >&2
        exit 1
    fi

    echo "Installing dependencies: ${wanted[*]}"
    local sudo_cmd=""
    if [ "$(id -u)" != "0" ]; then
        have sudo || { echo "Need root (or sudo) to install: ${wanted[*]}" >&2; exit 1; }
        sudo_cmd="sudo"
    fi
    $sudo_cmd apt-get update -qq
    $sudo_cmd apt-get install -y "${wanted[@]}"
    if [ -n "$(missing_deps)" ]; then
        echo "Dependencies are still unavailable to $PYTHON. Use /usr/bin/python3." >&2
        exit 1
    fi
}

install_linux() {
    install_deps

    # The tarball mirrors the checkout layout, so one set of paths serves both.
    local root
    if is_checkout; then
        echo "Installing from local checkout: $SELF_DIR"
        root="$SELF_DIR"
    else
        download "$LINUX_TARBALL" "$TMP/$LINUX_TARBALL"
        mkdir -p "$TMP/extracted"
        tar -xzf "$TMP/$LINUX_TARBALL" -C "$TMP/extracted"
        root="$TMP/extracted/trackai-linux"
        [ -d "$root/linux/src/trackai" ] || { echo "Downloaded archive looks wrong." >&2; exit 1; }
    fi

    # Validate the payload before stopping or replacing the installed copy.
    [ -f "$root/linux/bin/trackai" ] && [ -f "$root/linux/src/trackai/__main__.py" ] \
        || { echo "Linux payload is incomplete." >&2; exit 1; }
    if have trackai; then trackai stop; fi

    rm -rf "$LINUX_APP_DEST"
    mkdir -p "$LINUX_APP_DEST"
    cp -R "$root/linux/src/trackai" "$LINUX_APP_DEST/trackai"
    find "$LINUX_APP_DEST" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

    CLI_INSTALLED="$(install_cli "$root/linux/bin/trackai")"

    if py_has "$CAIRO_OK"; then
        "$PYTHON" "$root/linux/scripts/gen-icon.py" "$ICON_ROOT" >/dev/null 2>&1 || true
        have gtk-update-icon-cache && gtk-update-icon-cache -f -t "$ICON_ROOT" >/dev/null 2>&1 || true
    fi

    mkdir -p "$DESKTOP_DIR"
    PYTHONPATH="$LINUX_APP_DEST" "$PYTHON" - "$CLI_INSTALLED" "$root/linux/packaging/trackai.desktop" "$DESKTOP_DIR/trackai.desktop" <<'PYDESKTOP'
import pathlib, sys
from trackai.settings import desktop_quote
source = pathlib.Path(sys.argv[2]).read_text()
pathlib.Path(sys.argv[3]).write_text(source.replace('@EXEC@', desktop_quote(sys.argv[1]) + ' start'))
PYDESKTOP
    chmod 0644 "$DESKTOP_DIR/trackai.desktop"
    have update-desktop-database && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true

    INSTALL_SUMMARY="$LINUX_APP_DEST"
}

# ======================================================================= main

echo "Installing trackai…"

CLI_INSTALLED=""
INSTALL_SUMMARY=""
if [ "$PLATFORM" = "macos" ]; then
    install_macos
else
    install_linux
fi

SURFACE="menu bar"
[ "$PLATFORM" = "linux" ] && SURFACE="system tray"

echo ""
echo "✓ Installed $INSTALL_SUMMARY"
echo "✓ Installed CLI at $CLI_INSTALLED"
echo ""
echo "Now run:"
echo ""
echo "    $CLI_INSTALLED setup"
echo ""
echo "(If you haven't used Claude Code or Codex yet, open another terminal,"
echo " run \`claude\` and/or \`codex\` and log in first — trackai picks up that login automatically.)"

if [ "$PLATFORM" = "linux" ]; then
    case "${XDG_CURRENT_DESKTOP:-}" in
        *GNOME*)
            if ! gnome-extensions list 2>/dev/null | grep -qiE 'appindicator'; then
                echo ""
                echo "note: GNOME needs an AppIndicator extension to show $SURFACE icons."
                echo "      Ubuntu enables one by default; on stock GNOME install:"
                echo "      sudo apt install gnome-shell-extension-appindicator && log out/in"
            fi
            ;;
    esac
fi
