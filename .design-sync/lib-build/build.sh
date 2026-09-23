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
# Declarations: emit errors in app files do not block the .d.ts output.
node_modules/.bin/tsc -p "$SRC/tsconfig.json" > "$SRC/tsc.log" 2>&1 || true
node "$HERE/fix-dts.mjs" "$OUT/types" $MODULES

ln -sfn "$UI/node_modules" "$OUT/node_modules"
# Brand fonts: the app names Inter and JetBrains Mono but loads neither.
# Designs get the OFL @fontsource builds (sync-only, not app dependencies).
FONTS="$ROOT/.design-sync/.cache/fonts"
if [ ! -d "$FONTS/node_modules/@fontsource/inter" ]; then
  mkdir -p "$FONTS"
  echo '{"private":true}' > "$FONTS/package.json"
  npm i --prefix "$FONTS" --no-audit --no-fund \
    @fontsource/inter@5 @fontsource/jetbrains-mono@5 > /dev/null
fi

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
