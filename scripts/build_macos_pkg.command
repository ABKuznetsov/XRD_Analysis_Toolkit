#!/bin/zsh
set -e
export COPYFILE_DISABLE=1

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$("$ROOT"/.venv/bin/python -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$ROOT/pyproject.toml" 2>/dev/null || python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$ROOT/pyproject.toml")"
APP_NAME="XRD Phase Finder"
IDENTIFIER="com.xrdphasefinder.app"
PKG_IDENTIFIER="com.xrdphasefinder.pkg"
PKG_NAME="XRD_Phase_Finder_macOS_${VERSION}.pkg"
DIST_DIR="$ROOT/dist"
STAGE_ROOT="$DIST_DIR/macos_pkg"
PAYLOAD_ROOT="$STAGE_ROOT/payload"
SCRIPTS_DIR="$STAGE_ROOT/scripts"
APP_BUNDLE="$PAYLOAD_ROOT/Applications/$APP_NAME.app"
CONTENTS_DIR="$APP_BUNDLE/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
APP_PAYLOAD_DIR="$RESOURCES_DIR/app"
COMPONENT_PKG="$STAGE_ROOT/${APP_NAME}.component.pkg"
PKG_PATH="$DIST_DIR/$PKG_NAME"

cd "$ROOT"

if ! command -v pkgbuild >/dev/null 2>&1; then
    echo "pkgbuild was not found. Install Xcode Command Line Tools."
    exit 1
fi

if ! command -v productbuild >/dev/null 2>&1; then
    echo "productbuild was not found. Install Xcode Command Line Tools."
    exit 1
fi

echo "Building macOS PKG: $PKG_PATH"
rm -rf "$STAGE_ROOT"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$APP_PAYLOAD_DIR" "$SCRIPTS_DIR" "$DIST_DIR"

rsync -a \
    --exclude ".git/" \
    --exclude ".DS_Store" \
    --exclude "._*" \
    --exclude "__MACOSX/" \
    --exclude "__pycache__/" \
    --exclude "*.pyc" \
    --exclude "*.pyo" \
    --exclude ".venv/" \
    --exclude ".pytest_cache/" \
    --exclude "build/" \
    --exclude "dist/" \
    --exclude "*.egg-info/" \
    --exclude "PORTABLE_CHANGES.md" \
    --exclude "PORTABLE_README.md" \
    --exclude "manuscript_assets/" \
    --exclude "manuscript_work/" \
    --exclude "install_xrd_finder_windows_runtime.bat" \
    --exclude "scripts/manuscript/" \
    --exclude "XRD_Finder/benchmark_results/" \
    --exclude "XRD_Finder/install_windows_runtime_direct.bat" \
    --exclude "XRD_Finder/requirements-dev.txt" \
    --exclude "XRD_Finder/scripts/" \
    --exclude "XRD_Finder/tests/" \
    --exclude "XRD_Finder/data/" \
    --exclude "XRD_Finder/xrd_finder.zip" \
    --exclude "XRD_Finder/xrd_finder/app.py" \
    --exclude "XRD_Finder/xrd_finder/io/exporters.py" \
    --exclude "XRD_Finder/xrd_finder/services/thermo_service.py" \
    --exclude "XRD_Finder/xrd_finder/services/solid_solution_service.py" \
    --exclude "XRD_Finder/xrd_finder/services/structure_service.py" \
    --exclude "XRD_Finder/xrd_finder/ui/legacy_windows.py" \
    --exclude "XRD_Finder/xrd_finder/ui/main_window.py" \
    "$ROOT/" "$APP_PAYLOAD_DIR/"

for required_module in \
    "XRD_Finder/xrd_finder/core/refinement.py" \
    "XRD_Finder/xrd_finder/core/series.py"
do
    if [ ! -f "$APP_PAYLOAD_DIR/$required_module" ]; then
        echo "Required Finder module is missing from the package: $required_module"
        exit 1
    fi
done

chmod +x "$APP_PAYLOAD_DIR"/install_macos.command "$APP_PAYLOAD_DIR"/update_macos.command "$APP_PAYLOAD_DIR"/toolkit/*.command "$APP_PAYLOAD_DIR"/XRD_Finder/*.command 2>/dev/null || true

if [ -f "$APP_PAYLOAD_DIR/XRD_Finder/icon.png" ]; then
    cp "$APP_PAYLOAD_DIR/XRD_Finder/icon.png" "$RESOURCES_DIR/icon.png"
    if command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
        ICONSET_DIR="$RESOURCES_DIR/icon.iconset"
        rm -rf "$ICONSET_DIR"
        mkdir -p "$ICONSET_DIR"
        sips -z 16 16 "$APP_PAYLOAD_DIR/XRD_Finder/icon.png" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null 2>&1 || true
        sips -z 32 32 "$APP_PAYLOAD_DIR/XRD_Finder/icon.png" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null 2>&1 || true
        sips -z 32 32 "$APP_PAYLOAD_DIR/XRD_Finder/icon.png" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null 2>&1 || true
        sips -z 64 64 "$APP_PAYLOAD_DIR/XRD_Finder/icon.png" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null 2>&1 || true
        sips -z 128 128 "$APP_PAYLOAD_DIR/XRD_Finder/icon.png" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null 2>&1 || true
        sips -z 256 256 "$APP_PAYLOAD_DIR/XRD_Finder/icon.png" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null 2>&1 || true
        sips -z 256 256 "$APP_PAYLOAD_DIR/XRD_Finder/icon.png" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null 2>&1 || true
        sips -z 512 512 "$APP_PAYLOAD_DIR/XRD_Finder/icon.png" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null 2>&1 || true
        sips -z 512 512 "$APP_PAYLOAD_DIR/XRD_Finder/icon.png" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null 2>&1 || true
        sips -z 1024 1024 "$APP_PAYLOAD_DIR/XRD_Finder/icon.png" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null 2>&1 || true
        iconutil -c icns "$ICONSET_DIR" -o "$RESOURCES_DIR/icon.icns" >/dev/null 2>&1 || true
        rm -rf "$ICONSET_DIR"
    fi
fi

cat > "$CONTENTS_DIR/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleExecutable</key>
    <string>xrd-phase-finder</string>
    <key>CFBundleIdentifier</key>
    <string>$IDENTIFIER</string>
    <key>CFBundleIconFile</key>
    <string>icon.icns</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

cat > "$MACOS_DIR/xrd-phase-finder" <<'LAUNCHER'
#!/bin/zsh
set -e

APP_BUNDLE="$(cd "$(dirname "$0")/../.." && pwd)"
APP_ROOT="$APP_BUNDLE/Contents/Resources/app"
exec "$APP_ROOT/toolkit/launch_xrd_finder_preview.command" "$@"
LAUNCHER

chmod +x "$MACOS_DIR/xrd-phase-finder"
xattr -cr "$APP_BUNDLE" >/dev/null 2>&1 || true
xattr -dr com.apple.quarantine "$APP_BUNDLE" >/dev/null 2>&1 || true

cat > "$SCRIPTS_DIR/postinstall" <<POSTINSTALL
#!/bin/zsh
set -e

APP_BUNDLE="/Applications/$APP_NAME.app"
xattr -dr com.apple.quarantine "\$APP_BUNDLE" >/dev/null 2>&1 || true
touch "\$APP_BUNDLE" >/dev/null 2>&1 || true

LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [ -x "\$LSREGISTER" ]; then
    "\$LSREGISTER" -f "\$APP_BUNDLE" >/dev/null 2>&1 || true
fi

exit 0
POSTINSTALL
chmod +x "$SCRIPTS_DIR/postinstall"

rm -f "$COMPONENT_PKG" "$PKG_PATH"
pkgbuild \
    --root "$PAYLOAD_ROOT" \
    --install-location "/" \
    --identifier "$PKG_IDENTIFIER" \
    --version "$VERSION" \
    --scripts "$SCRIPTS_DIR" \
    --filter '(^|/)\._[^/]*$' \
    --filter '(^|/)\.DS_Store$' \
    --filter '(^|/)\.git($|/)' \
    --filter '(^|/)__pycache__($|/)' \
    --filter '\.pyc$' \
    "$COMPONENT_PKG"

productbuild \
    --package "$COMPONENT_PKG" \
    "$PKG_PATH"

echo "$PKG_PATH"
