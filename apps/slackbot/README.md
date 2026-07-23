# imbi-slackbot

A Slack bot for the [Imbi](https://github.com/AWeber-Imbi/imbi) DevOps service
management platform. It behaves like the
[Imbi assistant](https://github.com/AWeber-Imbi/imbi-assistant) — giving Claude
live access to Imbi data and actions through tools — but speaks Slack and acts
*as the Slack user who asked*, so every answer and action respects that user's
Imbi permissions.

## How It Works

The bot connects to Slack over [Socket Mode](https://api.slack.com/apis/socket-mode)
(an outbound websocket, so no public ingress is required). When a user mentions
the bot or DMs it, the bot:

1. **Resolves the Slack user to an Imbi user.** It looks up the Slack user's
   email (`users.info`), finds the matching active Imbi `User` in the graph, and
   mints a short-lived per-user JWT access token signed with the shared
   `IMBI_AUTH_JWT_SECRET` — exactly the token the Imbi API issues at login. The
   resolution is cached with a TTL. Users with no matching Imbi account get a
   friendly explanation instead.
2. **Reconstructs the thread context** from Slack (`conversations.replies`) so
   follow-up questions in a thread keep their history. Nothing is persisted
   server-side; the Slack thread *is* the conversation.
3. **Runs Claude with the Imbi toolset.** Tools are built at startup from the
   Imbi API's `openapi.json` via an in-process
   [FastMCP](https://github.com/jlowin/fastmcp) server, using the shared
   `imbi_common.mcp` exclusion policy (auth/MFA/status/thumbnail and any
   `x-imbi-ai-tool: false` operations are filtered out). The user's minted token
   is forwarded on every tool call, so the API enforces their permissions.
4. **Replies in-thread** with Claude's answer.

A tiny FastAPI app exposes `/status` (port 8004) for health checks; the Socket
Mode connection runs as a background task alongside it.

## Configuration

| Environment variable | Purpose |
|---|---|
| `SLACK_BOT_TOKEN` | Slack bot token (`xoxb-…`) |
| `SLACK_APP_TOKEN` | Slack app-level token for Socket Mode (`xapp-…`) |
| `ANTHROPIC_API_KEY` | Anthropic API key (enables the bot when set) |
| `IMBI_AUTH_JWT_SECRET` | Shared HS256 secret used to mint per-user tokens |
| `IMBI_INTERNAL_API_URL` | In-cluster base URL of the Imbi API |
| `IMBI_UI_URL` | Public base URL of the Imbi UI, used to build deep links |
| `IMBI_INTERNAL_UI_URL` | In-cluster UI address for fetching `llms.txt` (e.g. the Caddy frontend); falls back to `IMBI_UI_URL` |
| `POSTGRES_URL` | Imbi graph (Apache AGE) connection URL |
| `IMBI_SLACKBOT_MODEL` | Claude model (default `claude-sonnet-4-6`) |

See `src/imbi_slackbot/settings.py` for the full set.

## Development

```bash
moon run root:setup      # install deps + pre-commit hooks
moon run slackbot:test   # run the test suite with coverage
moon run slackbot:lint slackbot:typecheck slackbot:format   # ruff + basedpyright + format check
uv run --env-file .env.test imbi-slackbot serve   # run the bot
```

## Releasing

`[project].version` in `pyproject.toml` is the single source of truth (the git
tag does not set it). To cut a release:

1. Bump the version and re-lock in one step: `uv version <new-version>`
   (updates `pyproject.toml` and `uv.lock`). If a shared-library pin changed
   (e.g. `imbi-common==<version>`), update it first so the re-lock picks it up.
2. Commit, open a PR, and merge to `main` once CI is green.
3. Create a GitHub release whose tag is `v<version>` matching the bumped
   version. Publishing the release runs `.github/workflows/publish.yml`, which
   verifies the tag matches the package version before building and uploading to
   PyPI — so an un-bumped release fails fast instead of trying to re-publish an
   existing filename (which PyPI rejects with a 400).
