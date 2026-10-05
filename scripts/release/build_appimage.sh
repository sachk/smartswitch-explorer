#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <version> <arch> [artifacts_dir] [variant]" >&2
  exit 1
fi

version="$1"
arch="$2"
artifacts_dir="${3:-artifacts}"
variant="${4:-}"

if [[ -n "$variant" && ! "$variant" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "Invalid AppImage variant: $variant" >&2
  exit 1
fi

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

# Digests from the upstream release asset API; update versions and hashes together.
tool_version="1.9.1"
runtime_version="20251108"
case "$arch" in
  x86_64)
    tool_sha256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
    runtime_sha256="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"
    ;;
  aarch64)
    tool_sha256="f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158"
    runtime_sha256="00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444"
    ;;
  *)
    echo "Unsupported AppImage arch: $arch" >&2
    exit 1
    ;;
esac
tool_url="https://github.com/AppImage/appimagetool/releases/download/${tool_version}/appimagetool-${arch}.AppImage"
runtime_url="https://github.com/AppImage/type2-runtime/releases/download/${runtime_version}/runtime-${arch}"

mkdir -p "$artifacts_dir"
variant_suffix=""
if [[ -n "$variant" ]]; then
  variant_suffix="-${variant}"
fi
output="$artifacts_dir/smartswitch-explorer-${version}-linux-${arch}${variant_suffix}.AppImage"
appimage_comp="${APPIMAGE_COMP:-zstd}"
appimage_zstd_level="${APPIMAGE_ZSTD_LEVEL:-18}"

# Never share executable download paths between builds or publish tools as artifacts.
tool_dir="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/smartswitch-appimage.XXXXXX")"
trap 'rm -rf -- "$tool_dir"' EXIT
tool_path="$tool_dir/appimagetool-${arch}.AppImage"
runtime_path="$tool_dir/runtime-${arch}"
curl --proto '=https' --proto-redir '=https' -fsSL "$tool_url" -o "$tool_path"
curl --proto '=https' --proto-redir '=https' -fsSL "$runtime_url" -o "$runtime_path"
printf '%s  %s\n' "$tool_sha256" "$tool_path" "$runtime_sha256" "$runtime_path" | sha256sum --check -
chmod +x "$tool_path"

if ! command -v file >/dev/null 2>&1; then
  echo "Missing required dependency: 'file' command (install package: file)" >&2
  exit 1
fi

# Supplying the verified runtime prevents appimagetool downloading a moving one.
appimagetool_args=(--appimage-extract-and-run --runtime-file "$runtime_path" --comp "$appimage_comp")
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
TMPDIR="$tool_dir" ARCH="$arch" "$tool_path" "${appimagetool_args[@]}" "$appdir" "$output"

echo "Created: $output"
