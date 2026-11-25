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
`IMBI_INTERNAL_API_URL` / `POSTGRES_URL`.

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
- `files:write` — upload a single code block or table that is too long
  for one message as a file.
- `channels:read`, `groups:read` — find the Slack channel of an agent by
  name, to post the forms of tickets that need input.
- `im:write` — send those forms as a direct message to the ticket owner.
- `commands` — the `/create-ticket` slash command. It opens the New ticket
  dialog of the UI as a modal and creates the ticket as the Slack user who
  ran it. The text after the command fills in the description.

## Home tab

The `features.app_home` block and the `app_home_opened` event turn on the
[Home tab](index.md#home-tab). The tab needs no new scope: `views.publish`
and `views.open` use the bot token. Interactivity must be on, for the
buttons and the Customize Home dialog.

An app that you made from an older manifest does not show the Home tab.
Update the app configuration with this manifest (*App Manifest* in the app
settings) first. Then reinstall the app if Slack asks you to. A reinstall
alone does not apply the manifest, and the Home tab stays disabled.

## Manifest

```yaml
display_information:
  name: Imbi
  description: Query and manage Imbi from Slack
features:
  app_home:
    home_tab_enabled: true
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
  bot_user:
    display_name: imbi
    always_online: true
  slash_commands:
    - command: /create-ticket
      description: Create an Imbi ticket
      usage_hint: "[describe the work]"
      should_escape: false
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
      - channels:read
      - groups:read
      - im:write
      - commands
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - app_home_opened
      - message.im
  interactivity:
    is_enabled: true
  socket_mode_enabled: true
  org_deploy_enabled: false
  token_rotation_enabled: false
```
