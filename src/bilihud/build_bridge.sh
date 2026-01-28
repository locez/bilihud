#!/bin/bash
set -e

# --- UX Utilities ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

print_help_and_exit() {
    log_error "$1"
    echo ""
    echo -e "${YELLOW}Missing dependencies? Please install them:${NC}"
    echo "  - Debian/Ubuntu: sudo apt install qt6-base-dev qt6-base-private-dev libwayland-dev liblayershellqt-dev"
    echo "  - Arch Linux: sudo pacman -S qt6-base layer-shell-qt"
    echo "  - Fedora: sudo dnf install qt6-qtbase-devel layer-shell-qt-devel"
    echo ""
    echo -e "For full instructions, please check the README:"
    echo -e "${BLUE}https://github.com/locez/bilihud/blob/main/README.md${NC}"
    exit 1
}

# --- Setup Paths ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_FILE="$SCRIPT_DIR/layer_shell_bridge.cpp"
OUTPUT_FILE="$SCRIPT_DIR/libbili-layer.so"

log_info "Building Wayland Bridge..."
log_info "Source: $SOURCE_FILE"
log_info "Target: $OUTPUT_FILE"

# --- Dependency Check ---
command_exists() { command -v "$1" >/dev/null 2>&1; }

# 1. Check for QMake
if command_exists qmake6; then QMAKE=qmake6
elif command_exists qmake-qt6; then QMAKE=qmake-qt6
elif command_exists qmake; then QMAKE=qmake
else
    print_help_and_exit "Qt6 qmake not found."
fi
log_info "Found qmake: $QMAKE"

# 2. Check for Pkg-Config
if ! command_exists pkg-config; then
    print_help_and_exit "pkg-config not found."
fi

# 3. Check for Wayland Client
if ! pkg-config --exists wayland-client; then
    print_help_and_exit "wayland-client development headers not found."
fi

# 4. Check for Qt6 Core/Gui
if ! pkg-config --exists Qt6Core Qt6Gui; then
    print_help_and_exit "Qt6 Core/Gui development headers not found."
fi

# 5. Check for LayerShellQt
LAYERSHELL_CFLAGS=""
LAYERSHELL_LIBS=""
if pkg-config --exists LayerShellQtInterface; then
    LAYERSHELL_CFLAGS=$(pkg-config --cflags LayerShellQtInterface)
    LAYERSHELL_LIBS=$(pkg-config --libs LayerShellQtInterface)
elif pkg-config --exists LayerShellQt; then
    LAYERSHELL_CFLAGS=$(pkg-config --cflags LayerShellQt)
    LAYERSHELL_LIBS=$(pkg-config --libs LayerShellQt)
else
    # Fallback for manual installs or weird distros
    if [ -d "/usr/include/LayerShellQt" ]; then
        log_warn "LayerShellQt pkg-config not found, using fallback path."
        LAYERSHELL_CFLAGS="-I/usr/include/LayerShellQt"
        LAYERSHELL_LIBS="-lLayerShellQtInterface"
    else
        print_help_and_exit "LayerShellQt development headers not found."
    fi
fi

# 6. Check for Private Headers (Critical for QPlatformNativeInterface)
QT_INSTALL_HEADERS=$($QMAKE -query QT_INSTALL_HEADERS)
QT_VERSION=$($QMAKE -query QT_VERSION)
QT_PRIVATE_HEADERS="$QT_INSTALL_HEADERS/QtGui/$QT_VERSION/QtGui"

# Handle Arch/Flat structure vs Debian Nested structure
if [ ! -d "$QT_PRIVATE_HEADERS" ]; then
    # Fallback search
    FOUND_HEADERS=$(find "$QT_INSTALL_HEADERS/QtGui" -maxdepth 2 -name "QtGui" 2>/dev/null | grep "/[0-9]\.[0-9]\+\.[0-9]\+/QtGui$" | head -n 1)
    if [ -n "$FOUND_HEADERS" ]; then
        QT_PRIVATE_HEADERS="$FOUND_HEADERS"
        log_info "Found Qt Private Headers at fallback: $FOUND_HEADERS"
    else
        print_help_and_exit "Qt Private Headers (qpa/qplatformnativeinterface.h) not found. Missing qt6-base-private-dev?"
    fi
fi

# --- Compilation ---
log_info "Compiling..."

# Static libstdc++ for portability (optional env var to disable)
LINK_FLAGS="-static-libstdc++ -static-libgcc"
if [ "$USE_SYSTEM_LIBS" == "1" ]; then
    log_info "Using system libraries (dynamic linking)"
    LINK_FLAGS=""
fi

g++ -fPIC -shared -o "$OUTPUT_FILE" "$SOURCE_FILE" \
    $LINK_FLAGS \
    $(pkg-config --cflags --libs Qt6Gui Qt6Core wayland-client) \
    $LAYERSHELL_CFLAGS $LAYERSHELL_LIBS \
    -I"$QT_PRIVATE_HEADERS" \
    || print_help_and_exit "Compilation failed."

log_success "Build complete: $OUTPUT_FILE"
log_info "You can now run bilihud."
