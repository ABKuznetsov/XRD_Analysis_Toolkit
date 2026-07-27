#!/bin/zsh
set -e

APP_NAME="XRD Phase Finder"
SOURCE_ROOT="$(cd "$(dirname "$0")" && pwd)"
SOURCE_APP_ROOT="$SOURCE_ROOT/XRD_Finder"
SCI_ROOT="$HOME/Library/Application Support/Sci"
INSTALLED_SOURCE_ROOT="$SCI_ROOT/app"

if [ "$(uname -m)" = "arm64" ] || [ "$(sysctl -in sysctl.proc_translated 2>/dev/null || true)" = "1" ]; then
    SCI_ARCH="arm64"
else
    SCI_ARCH="x86_64"
fi

SCI_ENV="$SCI_ROOT/env-$SCI_ARCH"
XRD_FINDER_USER_ROOT="$SCI_ROOT/XRD_Finder"
SCI_LOGS="$SCI_ROOT/logs"
if [ -n "$XRD_FINDER_INSTALL_DIR" ]; then
    INSTALL_DIR="$XRD_FINDER_INSTALL_DIR"
elif [ -w "/Applications" ]; then
    INSTALL_DIR="/Applications"
else
    INSTALL_DIR="$HOME/Applications"
fi
APP_BUNDLE="$INSTALL_DIR/$APP_NAME.app"
CONTENTS_DIR="$APP_BUNDLE/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

cd "$SOURCE_ROOT"

echo "Installing $APP_NAME for macOS"
echo "Source folder: $SOURCE_ROOT"
echo "User runtime: $SCI_ROOT"
echo "Runtime architecture: $SCI_ARCH"
echo "Application folder: $INSTALL_DIR"
echo

if [ ! -d "$SOURCE_APP_ROOT" ]; then
    echo "Cannot find XRD_Finder folder next to this installer."
    read "?Press Enter to close..."
    exit 1
fi

echo "Copying application payload..."
mkdir -p "$INSTALLED_SOURCE_ROOT"
rsync -a --delete \
    --exclude ".git/" \
    --exclude ".DS_Store" \
    --exclude "__MACOSX/" \
    --exclude "__pycache__/" \
    --exclude "*.pyc" \
    --exclude "*.pyo" \
    --exclude ".venv/" \
    --exclude "build/" \
    --exclude "dist/" \
    --exclude "*.egg-info/" \
    --exclude "XRD_Finder/data/" \
    "$SOURCE_ROOT/" "$INSTALLED_SOURCE_ROOT/"

TOOLKIT_ROOT="$INSTALLED_SOURCE_ROOT"
APP_ROOT="$TOOLKIT_ROOT/XRD_Finder"
chmod +x "$TOOLKIT_ROOT"/install_macos.command "$TOOLKIT_ROOT"/update_macos.command "$TOOLKIT_ROOT"/toolkit/*.command "$TOOLKIT_ROOT"/XRD_Finder/*.command 2>/dev/null || true

echo "Preparing scientific Python environment..."
"$TOOLKIT_ROOT/toolkit/setup_sci_env.command"
VERSION="$(/usr/bin/arch "-$SCI_ARCH" "$SCI_ENV/bin/python" -c \
    'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' \
    "$TOOLKIT_ROOT/pyproject.toml")"

echo "Creating application bundle: $APP_BUNDLE"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

if [ -f "$APP_ROOT/icon.png" ]; then
    cp "$APP_ROOT/icon.png" "$RESOURCES_DIR/icon.png"
    if command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
        ICONSET_DIR="$RESOURCES_DIR/icon.iconset"
        rm -rf "$ICONSET_DIR"
        mkdir -p "$ICONSET_DIR"
        sips -z 16 16 "$APP_ROOT/icon.png" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null 2>&1 || true
        sips -z 32 32 "$APP_ROOT/icon.png" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null 2>&1 || true
        sips -z 32 32 "$APP_ROOT/icon.png" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null 2>&1 || true
        sips -z 64 64 "$APP_ROOT/icon.png" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null 2>&1 || true
        sips -z 128 128 "$APP_ROOT/icon.png" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null 2>&1 || true
        sips -z 256 256 "$APP_ROOT/icon.png" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null 2>&1 || true
        sips -z 256 256 "$APP_ROOT/icon.png" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null 2>&1 || true
        sips -z 512 512 "$APP_ROOT/icon.png" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null 2>&1 || true
        sips -z 512 512 "$APP_ROOT/icon.png" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null 2>&1 || true
        sips -z 1024 1024 "$APP_ROOT/icon.png" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null 2>&1 || true
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
    <string>com.xrdphasefinder.app</string>
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

cat > "$MACOS_DIR/xrd-phase-finder" <<LAUNCHER
#!/bin/zsh
set -e

APP_ROOT="$TOOLKIT_ROOT"
SCI_ROOT="$SCI_ROOT"
SCI_ENV="$SCI_ENV"
SCI_ARCH="$SCI_ARCH"
XRD_FINDER_USER_ROOT="$XRD_FINDER_USER_ROOT"
SCI_LOGS="$SCI_LOGS"
LOG_FILE="\$SCI_LOGS/xrd_finder_console.log"

mkdir -p "\$SCI_LOGS" "\$XRD_FINDER_USER_ROOT"

if [ -d "\$APP_ROOT/.git" ] && command -v git >/dev/null 2>&1; then
    (
        cd "\$APP_ROOT"
        git fetch origin >/dev/null 2>&1 || exit 0
        LOCAL_REV="\$(git rev-parse @ 2>/dev/null || true)"
        UPSTREAM_REV="\$(git rev-parse @{u} 2>/dev/null || git rev-parse origin/main 2>/dev/null || true)"
        BASE_REV="\$(git merge-base @ "\$UPSTREAM_REV" 2>/dev/null || true)"
        if [ -n "\$LOCAL_REV" ] && [ -n "\$UPSTREAM_REV" ] && [ "\$LOCAL_REV" != "\$UPSTREAM_REV" ] && [ "\$LOCAL_REV" = "\$BASE_REV" ]; then
            git pull --ff-only >/dev/null 2>&1
            "\$APP_ROOT/toolkit/setup_sci_env.command" >/dev/null 2>&1
        fi
    ) || true
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$APP_ROOT/XRD_Finder\${PYTHONPATH+:\$PYTHONPATH}"
export XRD_FINDER_DATA_DIR="\$XRD_FINDER_USER_ROOT/data"
export MPLCONFIGDIR="\$XRD_FINDER_USER_ROOT/matplotlib"
export QT_MAC_WANTS_LAYER=1
cd "\$APP_ROOT"
echo "[\$(date)] Starting XRD Phase Finder" > "\$LOG_FILE"
exec /usr/bin/arch "-\$SCI_ARCH" "\$SCI_ENV/bin/python" -m xrd_finder.apps.finder_gui "\$@" >> "\$LOG_FILE" 2>&1
LAUNCHER

chmod +x "$MACOS_DIR/xrd-phase-finder"
xattr -dr com.apple.quarantine "$APP_BUNDLE" >/dev/null 2>&1 || true
touch "$APP_BUNDLE" >/dev/null 2>&1 || true

LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [ -x "$LSREGISTER" ]; then
    "$LSREGISTER" -f "$APP_BUNDLE" >/dev/null 2>&1 || true
fi

echo
echo "$APP_NAME installed:"
echo "  $APP_BUNDLE"
echo
echo "You can launch it from Applications, Launchpad, Spotlight, or Finder:"
echo "  $INSTALL_DIR"
echo "or run:"
echo "  open \"$APP_BUNDLE\""
echo
echo "Preview launcher:"
echo "  $TOOLKIT_ROOT/toolkit/launch_xrd_finder_preview.command"
echo "Manual update:"
echo "  $TOOLKIT_ROOT/update_macos.command"
echo
read "?Press Enter to close..."
