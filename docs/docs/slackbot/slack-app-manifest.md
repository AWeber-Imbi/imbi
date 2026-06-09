# Slack App Setup

`imbi-slackbot` connects to Slack over **Socket Mode**, so it needs no public
URL. Create a Slack app from the manifest below (Slack → *Your Apps* →
*Create New App* → *From an app manifest*), install it to the workspace, then
provide the two tokens to the service.

## Tokens

| Env var | Where to find it |
|---|---|
| `SLACK_BOT_TOKEN` | *OAuth & Permissions* → *Bot User OAuth Token* (`xoxb-…`) after install |
| `SLACK_APP_TOKEN` | *Basic Information* → *App-Level Tokens* → create one with the `connections:write` scope (`xapp-…`) |

The bot also needs `ANTHROPIC_API_KEY`, the shared `IMBI_AUTH_JWT_SECRET`, and
`IMBI_INTERNAL_API_URL` / `POSTGRES_URL` (see the README).

## Required scopes & why

- `app_mentions:read` — receive `@imbi` mentions in channels.
- `chat:write` — post replies and the transient "thinking…" status message.
- `users:read` + `users:read.email` — **the identity bridge**: resolve the
  Slack user to their email, which is matched against the Imbi `User` record.
  `users:read` also resolves display names for thread attribution.
- `im:history`, `im:read` — read and respond in direct messages.
- `channels:history`, `groups:history` — read thread context
  (`conversations.replies`) when mentioned in public/private channels.
- `reactions:write` — add/remove the status-emoji reaction shown while a
  request is being processed.
- `files:read` — download files a user attaches (images, PDFs, text) so they
  can be passed to the model.
- `files:write` — upload long code blocks and oversized tables as file
  snippets.
- `canvases:write` — render Markdown tables as a channel canvas (falls back
  to a `files:write` snippet when unavailable).

## Manifest

```yaml
display_information:
  name: Imbi
  description: Query and manage Imbi from Slack
features:
  bot_user:
    display_name: imbi
    always_online: true
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - chat:write
      - users:read
      - users:read.email
      - im:history
      - im:read
      - channels:history
      - groups:history
      - reactions:write
      - files:read
      - files:write
      - canvases:write
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.im
  socket_mode_enabled: true
  org_deploy_enabled: false
  token_rotation_enabled: false
```
