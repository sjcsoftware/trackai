#!/bin/bash
# Builds TrackAI.app, dist/TrackAI.zip and the testable ./trackai binary.
# Requires macOS with the Xcode Command Line Tools (Swift 5.9+).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[ "$(uname -s)" = "Darwin" ] || { echo "The Mac app build requires macOS. On Linux run ./linux/scripts/build.sh." >&2; exit 1; }

VERSION="${1:-0.1.0}"
APP_NAME="TrackAI"
BUNDLE_ID="com.chaseungjoon.trackai"
DIST="$ROOT/dist"
APP="$DIST/$APP_NAME.app"

echo "==> Building release binaries (arm64 + x86_64)..."
swift build -c release --triple arm64-apple-macosx13.0
swift build -c release --triple x86_64-apple-macosx13.0
mkdir -p "$DIST"
BIN="$DIST/trackai-universal"
lipo -create -output "$BIN" \
    .build/arm64-apple-macosx/release/trackai \
    .build/x86_64-apple-macosx/release/trackai
[ -x "$BIN" ] || { echo "build failed: $BIN missing" >&2; exit 1; }

echo "==> Assembling ${APP}..."
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/trackai"
cp "$ROOT/bin/trackai" "$APP/Contents/Resources/trackai-cli"
chmod +x "$APP/Contents/Resources/trackai-cli"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key><string>trackai</string>
    <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
    <key>CFBundleName</key><string>$APP_NAME</string>
    <key>CFBundleDisplayName</key><string>trackai</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSHumanReadableCopyright</key><string>© 2026 Cha Seungjoon · MIT License</string>
</dict>
</plist>
PLIST

echo "==> Generating icon..."
ICONSET="$DIST/AppIcon.iconset"
rm -rf "$ICONSET"
swift "$ROOT/scripts/gen-icon.swift" "$ICONSET" >/dev/null
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET"

echo "==> Ad-hoc code signing..."
codesign --force --deep -s - "$APP"

echo "==> Zipping..."
ditto -c -k --keepParent "$APP" "$DIST/$APP_NAME.zip"

echo "==> Dropping the testable binary at ./trackai..."
cp "$BIN" "$ROOT/trackai"
chmod +x "$ROOT/trackai"
rm -f "$BIN"

echo "==> Done:"
ls -lh "$DIST/$APP_NAME.zip" "$ROOT/trackai"
lipo -info "$APP/Contents/MacOS/trackai" 2>/dev/null || true
