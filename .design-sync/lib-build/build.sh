#!/usr/bin/env bash
# Build ui/src/components/ui as a library for design-sync.
# Output: .design-sync/.cache/lib-dist/{index.js,style.css,types/,package.json}
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
UI="$ROOT/ui"
SRC="$ROOT/.design-sync/.cache/lib-src"
OUT="$ROOT/.design-sync/.cache/lib-dist"

rm -rf "$SRC"
mkdir -p "$SRC"

# Every primitive module; stories, tests, and hook/policy helpers stay out.
MODULES=$(cd "$UI/src" && find components/ui \( -name '*.tsx' -o -name '*.ts' \) \
  -not -name '*.stories.tsx' -not -name '*.test.ts*' -not -name '*.d.ts' \
  -not -path '*/__tests__/*' | sed -E 's/\.tsx?$//' | sort)

{
  echo "import '@/index.css'"
  for m in $MODULES; do echo "export * from '@/$m'"; done
  # EditableKeyValueMap takes its `state` from this hook.
  echo "export * from '@/hooks/useEditableKeyValueMap'"
  echo "export { ImbiProvider } from '$HERE/ImbiProvider'"
} > "$SRC/index.tsx"

cat > "$SRC/tsconfig.json" <<JSON
{
  "extends": "$UI/tsconfig.json",
  "compilerOptions": {
    "noEmit": false,
    "declaration": true,
    "emitDeclarationOnly": true,
    "noUnusedLocals": false,
    "rootDir": "$UI/src",
    "outDir": "$OUT/types"
  },
  "include": [],
  "files": [$(for m in $MODULES; do f="$UI/src/$m.tsx"; [ -f "$f" ] || f="$UI/src/$m.ts"; printf '"%s",' "$f"; done)"$UI/src/hooks/useEditableKeyValueMap.ts"],
  "references": []
}
JSON

cd "$UI"
# api/client.ts throws at import time without an API URL.
VITE_API_URL=/api node_modules/.bin/vite build --config "$HERE/vite.config.ts" --logLevel warn
# Declarations: tsc reports type errors in app files (vite-only globals such
# as import.meta.glob) but still emits every .d.ts. Tolerate the errors, and
# fail only when a primitive's declaration is missing.
node_modules/.bin/tsc -p "$SRC/tsconfig.json" > "$SRC/tsc.log" 2>&1 || true
missing=0
for m in $MODULES hooks/useEditableKeyValueMap; do
  if [ ! -f "$OUT/types/$m.d.ts" ]; then
    echo "missing declaration: $OUT/types/$m.d.ts" >&2
    missing=1
  fi
done
if [ "$missing" -ne 0 ]; then
  echo "tsc did not emit all declarations; see $SRC/tsc.log" >&2
  exit 1
fi
node "$HERE/fix-dts.mjs" "$OUT/types" $MODULES

ln -sfn "$UI/node_modules" "$OUT/node_modules"
VERSION=$(node -p "require('$UI/package.json').version")
cat > "$OUT/package.json" <<JSON
{
  "name": "imbi-ui",
  "version": "$VERSION",
  "type": "module",
  "module": "index.js",
  "types": "types/index.d.ts"
}
JSON
echo "built $OUT ($(echo "$MODULES" | wc -l | tr -d ' ') modules)"
