#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <version> <arch> [artifacts_dir]" >&2
  exit 1
fi

version="$1"
arch="$2"
artifacts_dir="${3:-artifacts}"

dist_dir="dist/smartswitch-explorer"
if [[ ! -d "$dist_dir" ]]; then
  echo "Missing PyInstaller directory build: $dist_dir" >&2
  exit 1
fi

appdir="AppDir"
rm -rf "$appdir"
mkdir -p "$appdir/usr/lib/smartswitch-explorer"
mkdir -p "$appdir/usr/bin"
mkdir -p "$appdir/usr/share/applications"
mkdir -p "$appdir/usr/share/icons/hicolor/256x256/apps"

cp -a "$dist_dir"/. "$appdir/usr/lib/smartswitch-explorer/"
install -Dm755 packaging/linux/appimage/smartswitch-explorer-wrapper.sh "$appdir/usr/bin/smartswitch-explorer"
install -Dm755 packaging/linux/appimage/AppRun "$appdir/AppRun"
install -Dm644 packaging/linux/smartswitch-explorer.desktop "$appdir/smartswitch-explorer.desktop"
install -Dm644 src/gui/assets/app_icon.png "$appdir/smartswitch-explorer.png"
install -Dm644 packaging/linux/smartswitch-explorer.desktop "$appdir/usr/share/applications/smartswitch-explorer.desktop"
install -Dm644 src/gui/assets/app_icon.png "$appdir/usr/share/icons/hicolor/256x256/apps/smartswitch-explorer.png"
ln -sf "smartswitch-explorer.png" "$appdir/.DirIcon"

# Strip debug symbols from bundled ELF files to reduce AppImage size.
if command -v strip >/dev/null 2>&1; then
  while IFS= read -r -d '' candidate; do
    if file -b "$candidate" | grep -q "ELF"; then
      strip --strip-unneeded "$candidate" || true
    fi
  done < <(find "$appdir/usr/lib/smartswitch-explorer" -type f -print0)
fi

case "$arch" in
  x86_64)
    tool_url="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    ;;
  aarch64)
    tool_url="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-aarch64.AppImage"
    ;;
  *)
    echo "Unsupported AppImage arch: $arch" >&2
    exit 1
    ;;
esac

mkdir -p "$artifacts_dir"
output="$artifacts_dir/smartswitch-explorer-${version}-linux-${arch}.AppImage"
appimage_comp="${APPIMAGE_COMP:-zstd}"
appimage_zstd_level="${APPIMAGE_ZSTD_LEVEL:-18}"

tool_path="/tmp/appimagetool-${arch}.AppImage"
curl -fsSL "$tool_url" -o "$tool_path"
chmod +x "$tool_path"

appimagetool_args=(--appimage-extract-and-run --comp "$appimage_comp")
compression_label="$appimage_comp"
if [[ "$appimage_comp" == "zstd" ]]; then
  appimagetool_args+=(
    --mksquashfs-opt
    -Xcompression-level
    --mksquashfs-opt
    "$appimage_zstd_level"
  )
  compression_label="$appimage_comp level $appimage_zstd_level"
fi

echo "AppImage squashfs compression: $compression_label"
ARCH="$arch" "$tool_path" "${appimagetool_args[@]}" "$appdir" "$output"

echo "Created: $output"
