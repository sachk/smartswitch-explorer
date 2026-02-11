#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_ICON="${1:-$ROOT_DIR/src/gui/assets/smartswitch_base.png}"
OUTPUT_ICON="${2:-$ROOT_DIR/src/gui/assets/app_icon.png}"

if [ ! -f "$SOURCE_ICON" ]; then
  echo "Source icon not found: $SOURCE_ICON" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_ICON")"

nix-shell -p imagemagick --run "
  magick '$SOURCE_ICON' \
    -resize 512x512^ -gravity center -extent 512x512 \
    -modulate 100,110,100 \
    \( -size 512x512 xc:none \
       -fill '#0ea5e980' -draw 'roundrectangle 28,328 484,500 40,40' \
       -fill '#f8fafc' -font DejaVu-Sans-Bold -pointsize 72 -gravity south -annotate +0+24 'DX' \
    \) -compose over -composite \
    \( -size 512x512 xc:none \
       -fill '#22c55e' -draw 'polygon 340,96 436,96 436,170 478,170 388,260 298,170 340,170' \
    \) -compose over -composite \
    '$OUTPUT_ICON'
"

echo "Wrote $OUTPUT_ICON"
