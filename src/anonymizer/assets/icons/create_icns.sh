#!/bin/bash
set -e

test -n "$1"
name="${1%.*}"

iconset="${name}.iconset"
rm -rf "${iconset}"
mkdir -p "${iconset}"

for s in 16 32 128 256 512; do
  d=$(($s*2))
  sips -Z $s "$1" --out "${iconset}/icon_${s}x$s.png"
  sips -Z $d "$1" --out "${iconset}/icon_${s}x$s@2x.png"
done

iconutil -c icns "${iconset}" -o "${name}.icns"
rm -r "${iconset}"