#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <version> <arch> [artifacts_dir]" >&2
  exit 1
fi

version="$1"
arch="$2"
artifacts_dir="${3:-artifacts}"

app_name="SmartSwitch Explorer.app"
app_path="dist/${app_name}"

if [[ ! -d "$app_path" ]]; then
  echo "Missing app bundle: $app_path" >&2
  exit 1
fi

mkdir -p "$artifacts_dir"

dmg_path="$artifacts_dir/smartswitch-explorer-${version}-macos-${arch}.dmg"
pkg_path="$artifacts_dir/smartswitch-explorer-${version}-macos-${arch}.pkg"

hdiutil create \
  -volname "SmartSwitch Explorer" \
  -srcfolder "$app_path" \
  -ov \
  -format UDZO \
  "$dmg_path"

pkgbuild \
  --identifier io.github.sachk.smartswitch-explorer \
  --version "$version" \
  --install-location /Applications \
  --component "$app_path" \
  "$pkg_path"

echo "Created: $dmg_path"
echo "Created: $pkg_path"
