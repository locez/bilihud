#!/bin/bash
set -e

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_FILE="$SCRIPT_DIR/layer_shell_bridge.cpp"
OUTPUT_FILE="$SCRIPT_DIR/libbili-layer.so"

echo "Building bridge from: $SOURCE_FILE"
echo "Output to: $OUTPUT_FILE"

# Function to check for command existence
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Find qmake
if command_exists qmake6; then
    QMAKE=qmake6
elif command_exists qmake-qt6; then
    QMAKE=qmake-qt6
elif command_exists qmake; then
    QMAKE=qmake
else
    echo "Error: qmake6, qmake-qt6, or qmake not found. Please install Qt6 development tools."
    exit 1
fi

echo "Using qmake: $QMAKE"

# Get Qt paths and version
QT_INSTALL_HEADERS=$($QMAKE -query QT_INSTALL_HEADERS)
QT_VERSION=$($QMAKE -query QT_VERSION)

if [ -z "$QT_INSTALL_HEADERS" ] || [ -z "$QT_VERSION" ]; then
    echo "Error: Could not query Qt paths or version using $QMAKE."
    exit 1
fi

# Construct private include path
# Usually, private headers are in $QT_INSTALL_HEADERS/QtGui/$QT_VERSION/QtGui
# or sometimes just headers are flat. But for private headers specifically:
QT_PRIVATE_HEADERS="$QT_INSTALL_HEADERS/QtGui/$QT_VERSION/QtGui"

if [ ! -d "$QT_PRIVATE_HEADERS" ]; then
    echo "Warning: Private header directory $QT_PRIVATE_HEADERS does not exist."
    echo "Please ensure you have qt6-base-private-dev (Debian/Ubuntu) or qt6-base (Arch) installed."
    # Attempt to continue, though it likely won't work if this path is wrong for the specific distro layout
fi

# Find LayerShellQt
# Try pkg-config first
LAYERSHELL_CFLAGS=""
LAYERSHELL_LIBS=""

if command_exists pkg-config; then
    if pkg-config --exists LayerShellQtInterface; then
        LAYERSHELL_CFLAGS=$(pkg-config --cflags LayerShellQtInterface)
        LAYERSHELL_LIBS=$(pkg-config --libs LayerShellQtInterface)
    elif pkg-config --exists LayerShellQt; then
        LAYERSHELL_CFLAGS=$(pkg-config --cflags LayerShellQt)
        LAYERSHELL_LIBS=$(pkg-config --libs LayerShellQt)
    else
        echo "Warning: LayerShellQt not found via pkg-config. Trying default paths."
        # Fallback to defaults or user specified locations if needed
        # Assuming standard install might work with -lLayerShellQtInterface
        LAYERSHELL_LIBS="-lLayerShellQtInterface"
        # Common include path
        if [ -d "/usr/include/LayerShellQt" ]; then
             LAYERSHELL_CFLAGS="-I/usr/include/LayerShellQt"
        fi
    fi
else
    echo "Warning: pkg-config not found. Using default paths for LayerShellQt."
    LAYERSHELL_LIBS="-lLayerShellQtInterface"
    if [ -d "/usr/include/LayerShellQt" ]; then
            LAYERSHELL_CFLAGS="-I/usr/include/LayerShellQt"
    fi
fi

echo "Compiling libbili-layer.so..."

g++ -fPIC -shared -o "$OUTPUT_FILE" "$SOURCE_FILE" \
    -static-libstdc++ -static-libgcc \
    $(pkg-config --cflags --libs Qt6Gui Qt6Core wayland-client) \
    $LAYERSHELL_CFLAGS $LAYERSHELL_LIBS \
    -I"$QT_PRIVATE_HEADERS"

echo "Build complete."
