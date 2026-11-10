#!/bin/sh
# Write the seed inputs into the fuzz corpus directories.
#
#   proxy/fuzz/seed.sh
#
# The seeds are written here, not committed as files, because the
# pre-commit hooks add a final newline and git changes CRLF, and both
# change the input.
set -eu
dir=$(cd "$(dirname "$0")" && pwd)/corpus
mkdir -p "$dir/target" "$dir/parse"
for target in 10.1.2.3:443 0x0a.1:443 2130706433:443 \
  zoekt.pse.example.cloud:443 'bücher.example.com:443'; do
  printf '%s' "$target" > "$dir/target/seed-$(printf '%s' "$target" | cksum | cut -d' ' -f1)"
  printf 'CONNECT %s HTTP/1.1\r\nHost: %s\r\n\r\n' "$target" "$target" \
    > "$dir/parse/seed-$(printf '%s' "$target" | cksum | cut -d' ' -f1)"
done
