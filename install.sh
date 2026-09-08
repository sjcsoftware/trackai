#!/bin/bash
# trackai installer — https://github.com/sjcsoftware/trackai
# Usage: curl -fsSL https://raw.githubusercontent.com/sjcsoftware/trackai/main/install.sh | bash
set -euo pipefail

REPO="sjcsoftware/trackai"
# Branch or tag the payload is fetched from. Override to install from a branch:
#   curl -fsSL .../<branch>/install.sh | TRACKAI_REF=<branch> bash
REF="${TRACKAI_REF:-main}"
ZIP_NAME="TrackAI.zip"
APP_DEST="/Applications/TrackAI.app"

[ "$(uname -s)" = "Darwin" ] || { echo "trackai supports macOS only." >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# A checkout is only a checkout when this script is a real file on disk sitting
# next to the sources; `curl | bash` always downloads instead.
SELF_DIR=""
if [ -f "${BASH_SOURCE[0]:-}" ]; then
    SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
is_checkout() { [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/bin/trackai" ] && [ -f "$SELF_DIR/Package.swift" ]; }

download() {
    local out="$1"
    local url_release="https://github.com/$REPO/releases/latest/download/$ZIP_NAME"
    local url_raw="https://raw.githubusercontent.com/$REPO/$REF/dist/$ZIP_NAME"
    curl -fsSL "$url_release" -o "$out" 2>/dev/null || curl -fsSL "$url_raw" -o "$out" \
        || { echo "Download failed ($ZIP_NAME)." >&2; exit 1; }
}

# Installs the CLI from $1 and reports where it landed.
install_cli() {
    local cli_src="$1" dir installed=""
    for dir in /opt/homebrew/bin /usr/local/bin; do
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
    echo "$installed"
}

echo "==> Installing trackai..."
ZIP="$TMP/$ZIP_NAME"
if is_checkout && [ -f "$SELF_DIR/dist/$ZIP_NAME" ]; then
    echo "    (from local checkout: $SELF_DIR)"
    cp "$SELF_DIR/dist/$ZIP_NAME" "$ZIP"
else
    download "$ZIP"
fi

# Quit a running copy before replacing it.
osascript -e 'quit app "TrackAI"' >/dev/null 2>&1 || true

ditto -x -k "$ZIP" "$TMP/extracted"
[ -d "$TMP/extracted/TrackAI.app" ] || { echo "Downloaded archive looks wrong." >&2; exit 1; }
rm -rf "$APP_DEST"
mv "$TMP/extracted/TrackAI.app" "$APP_DEST"
xattr -dr com.apple.quarantine "$APP_DEST" 2>/dev/null || true

# The CLI ships inside the bundle; a checkout has the newer copy.
CLI_SRC="$APP_DEST/Contents/Resources/trackai-cli"
is_checkout && CLI_SRC="$SELF_DIR/bin/trackai"
CLI_INSTALLED="$(install_cli "$CLI_SRC")"

cat <<DONE

✓ trackai installed
    app: $APP_DEST
    cli: $CLI_INSTALLED

Next:

    trackai setup

That reads the logins Claude Code and Codex already keep on this Mac — nothing
to copy or paste. If neither is set up yet, run \`claude\` and/or \`codex\` in a
terminal first, then run \`trackai setup\` again.
DONE
