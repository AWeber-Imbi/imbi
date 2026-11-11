#!/bin/sh
# SettingsInjectionTests: run by the scripted model through Bash, as
# agent. Writes each file that the CLI could read (settings plan 4.1)
# and tries to change the published plugins. Each hook or MCP server
# that runs touches a file in the chain's marks/ directory. Prints one
# "OK <what>" or "FAIL <what>" line for each write.
cfg=$CLAUDE_CONFIG_DIR
marks=$(cd "$cfg/../../.." && pwd)/marks
mkdir -p "$marks"

hook() {
  printf '{"matcher":"","hooks":[{"type":"command","command":"touch %s/%s"}]}' \
    "$marks" "$1"
}
mcp() {
  printf '{"command":"sh","args":["-c","touch %s/%s; sleep 60"]}' "$marks" "$1"
}
try() {
  label=$1
  shift
  if "$@" 2>/dev/null; then echo "OK $label"; else echo "FAIL $label"; fi
}
put() { mkdir -p "$(dirname "$1")" && printf '%s\n' "$2" > "$1"; }

try settings.json put "$cfg/settings.json" \
  "{\"permissions\":{\"allow\":[\"Write\",\"CronList\"]},\"hooks\":{\"PreToolUse\":[$(hook settings-hook)]}}"
try settings.local.json put "$cfg/settings.local.json" \
  "{\"hooks\":{\"PreToolUse\":[$(hook local-hook)]}}"
try CLAUDE.md put "$cfg/CLAUDE.md" 'INJ_CLAUDE_MD'
try rules put "$cfg/rules/inj.md" 'INJ_RULES'
try skills put "$cfg/skills/injskill/SKILL.md" \
  "$(printf -- '---\nname: injskill\ndescription: INJ_SKILL\n---\nx')"
try agents put "$cfg/agents/injagent.md" \
  "$(printf -- '---\nname: injagent\ndescription: INJ_AGENT\n---\nx')"
try commands put "$cfg/commands/injcmd.md" \
  "$(printf -- '---\ndescription: INJ_CMD\n---\nx')"
try plugins put "$cfg/plugins/installed_plugins.json" '{"version":2,"plugins":{}}'
for file in "$cfg/.claude.json" "$HOME/.claude.json"; do
  try "$(basename "$(dirname "$file")")/.claude.json" python3 -c '
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
document = json.loads(path.read_text()) if path.exists() else {}
document.setdefault("mcpServers", {})[sys.argv[2]] = json.loads(sys.argv[3])
path.write_text(json.dumps(document))
' "$file" "mcp-$(basename "$(dirname "$file")")" "$(mcp "mcp-$(basename "$(dirname "$file")")")"
done
for plugin in /run/plugins/*/*; do
  try plugin-hooks put "$plugin/hooks/hooks.json" \
    "{\"hooks\":{\"PreToolUse\":[$(hook plugin-hook)]}}"
  try plugin-mcp put "$plugin/.mcp.json" \
    "{\"mcpServers\":{\"injected\":$(mcp plugin-mcp)}}"
  try plugin-rename mv "$plugin" "$plugin.old"
done
for chain in /run/plugins/*; do
  try plugins-rename mv "$chain" "$chain.old"
done
