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
mkdir -p \
    "$MACOS_DIR" \
    "$RESOURCES_DIR" \
    "$APP_PAYLOAD_DIR/XRD_Finder/xrd_finder" \
    "$APP_PAYLOAD_DIR/toolkit" \
    "$SCRIPTS_DIR" \
    "$DIST_DIR"

rsync -a \
    --exclude ".DS_Store" \
    --exclude "._*" \
    --exclude "__pycache__/" \
    --exclude "*.pyc" \
    --exclude "*.pyo" \
    --exclude "app.py" \
    --exclude "io/exporters.py" \
    --exclude "services/thermo_service.py" \
    --exclude "services/solid_solution_service.py" \
    --exclude "services/structure_service.py" \
    --exclude "ui/legacy_windows.py" \
    --exclude "ui/main_window.py" \
    "$ROOT/XRD_Finder/xrd_finder/" \
    "$APP_PAYLOAD_DIR/XRD_Finder/xrd_finder/"

for runtime_file in \
    "XRD_Finder/app.json" \
    "XRD_Finder/Entry_96-100-0018.cif" \
    "XRD_Finder/requirements.txt" \
    "XRD_Finder/icon.png" \
    "toolkit/launch_xrd_finder_preview.command" \
    "toolkit/launch_xrd_finder_preview_macos.py" \
    "toolkit/setup_sci_env.command" \
    "toolkit/manifest.json" \
    "LICENSE"
do
    target="$APP_PAYLOAD_DIR/$runtime_file"
    mkdir -p "$(dirname "$target")"
    cp -p "$ROOT/$runtime_file" "$target"
done

FORBIDDEN_PAYLOAD="$(find "$APP_PAYLOAD_DIR" \
    \( -iname '*xrd_craft*' -o -iname '*xrd craft*' -o -iname '*crystal_viewer*' \) \
    -print -quit)"
if [ -n "$FORBIDDEN_PAYLOAD" ]; then
    echo "Forbidden CRAFT payload in Finder package: $FORBIDDEN_PAYLOAD"
    exit 1
fi

FORBIDDEN_NON_RUNTIME="$(find "$APP_PAYLOAD_DIR" \
    \( -type d \( -name docs -o -name tests -o -name installer \) \
    -o -type f \( -name 'RELEASE_NOTES_*' -o -name 'requirements-dev.txt' \) \) \
    -print -quit)"
if [ -n "$FORBIDDEN_NON_RUNTIME" ]; then
    echo "Forbidden non-runtime payload in Finder package: $FORBIDDEN_NON_RUNTIME"
    exit 1
fi

for required_module in \
    "XRD_Finder/xrd_finder/core/refinement.py" \
    "XRD_Finder/xrd_finder/core/series.py"
do
    if [ ! -f "$APP_PAYLOAD_DIR/$required_module" ]; then
        echo "Required Finder module is missing from the package: $required_module"
        exit 1
    fi
done

chmod +x "$APP_PAYLOAD_DIR"/toolkit/*.command

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
