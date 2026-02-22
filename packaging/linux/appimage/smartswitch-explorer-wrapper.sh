#!/bin/sh
set -eu

APP_ROOT="${APPDIR:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}"
APP_LIB="$APP_ROOT/usr/lib/smartswitch-explorer"

export LD_LIBRARY_PATH="$APP_LIB:${LD_LIBRARY_PATH:-}"
export QT_PLUGIN_PATH="$APP_LIB/PySide6/Qt/plugins"
export QT_QPA_PLATFORM_PLUGIN_PATH="$APP_LIB/PySide6/Qt/plugins/platforms"

exec "$APP_LIB/smartswitch-explorer" "$@"
