# Slack Bot

`imbi-slackbot` lets people ask Imbi questions in Slack. It answers with live
Imbi data, as the person who asked. It uses a Claude model through the
Anthropic API.

The bot connects to Slack with **Socket Mode**, so it needs no public URL.
It runs on port 8004, which serves only `GET /status`. To create the Slack
app, see [Slack App Setup](slack-app-manifest.md).

## Use the bot

- **In a channel:** mention the bot, for example
  `@imbi which projects does the platform team own?`. The bot answers in a
  thread.
- **In a direct message:** write to the bot. You do not need to mention it.

A thread is one conversation. For each message, the bot reads the last
`IMBI_SLACKBOT_MAX_THREAD_MESSAGES` messages of the thread (default `30`)
and sends them to the model. The bot stores nothing between messages.

In a channel thread, each follow-up must mention the bot again. The bot
reads only mentions in channels. In a direct message, the bot reads every
message.

You can attach files: images (GIF, JPEG, PNG, WebP), PDFs, and text files,
up to 10 MB each.

While the bot works, it adds a reaction to your message and posts a status
message that names the tools it runs. It removes both when the answer is
ready. The answer uses Slack formatting. The bot posts a large Markdown
table as a canvas, and a code block as a file snippet.

### Start an agent task

Ask the bot to make an agent task, for example: "@imbi create a task to fix
the issue in this thread and give it to mender". You own the task. See
[Agent Tasks](../admin/agent-tasks.md#slack).

## How the bot knows who you are

1. The bot reads the email of your Slack profile (`users.info`).
2. It finds the active Imbi user with that email.
3. It makes a short-lived Imbi access token for that user, signed with
   `IMBI_AUTH_JWT_SECRET`, as imbi-api does at login.
4. It calls imbi-api with that token. So each tool call has your
   permissions, and imbi-api records `slack` as the channel.

When no active Imbi user has your email, the bot tells you so and does
nothing else. Ask an Imbi admin to make or activate your account.

The bot keeps each result, also "no user", for
`IMBI_SLACKBOT_IDENTITY_CACHE_TTL` seconds (default `900`). A new or
activated account can take that long to work.

The bot never answers a message that it posted, so it cannot loop on its own
replies.

## Tools

The bot has the same imbi-api tools as the [assistant](../assistant/index.md):
one tool for each operation in the imbi-api OpenAPI spec, except the auth,
MFA, status, and thumbnail routes and the operations that imbi-api marks as
not for AI. The bot reads the spec at startup. It does not remove the tools
that you cannot use. A call without the permission gets `403`.

The bot can call tools for up to `IMBI_SLACKBOT_MAX_TOOL_ROUNDS` rounds for
one message. A tool result longer than `IMBI_SLACKBOT_MAX_TOOL_RESULT_CHARS`
is replaced with an error.

## The system prompt

The bot reads its prompt from the [prompt CMS](../admin/prompts.md), at
`IMBI_SLACKBOT_PROMPT_REF` (default `imbi-slackbot/system@stable`).

- When the CMS has no usable version, the bot uses the prompt in the
  `imbi-common` package.
- `IMBI_SLACKBOT_SYSTEM_PROMPT` replaces both. It uses Jinja syntax, for
  example `{{ display_name }}`.
- The model, the max tokens, and the temperature of the prompt version
  apply. When the version names no model, `IMBI_SLACKBOT_MODEL` applies.
  When it sets no max tokens, `IMBI_SLACKBOT_MAX_TOKENS` applies.

The prompt tells the model the name of the person, the tools, and the URL
patterns of the UI. The bot reads the URL patterns from `llms.txt` of the
UI.

## Settings

The full list is in [Configuration](../api/configuration.md).

| Variable | Default | What it is |
|---|---|---|
| `SLACK_BOT_TOKEN` | none | The bot token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | none | The app-level token (`xapp-...`) for Socket Mode |
| `ANTHROPIC_API_KEY` | none | The Anthropic API key |
| `IMBI_SLACKBOT_ENABLED` | `false` | Turns the bot on. When the three variables above are set, the bot turns on |
| `IMBI_SLACKBOT_MODEL` | `claude-sonnet-4-6` | The model when the prompt names none |
| `IMBI_SLACKBOT_MAX_TOKENS` | `16384` | The maximum output tokens of one answer |
| `IMBI_SLACKBOT_MAX_TOOL_ROUNDS` | `10` | The maximum tool rounds for one message |
| `IMBI_SLACKBOT_MAX_TOOL_RESULT_CHARS` | `200000` | A longer tool result is replaced with an error |
| `IMBI_SLACKBOT_MAX_THREAD_MESSAGES` | `30` | The thread messages that the bot reads |
| `IMBI_SLACKBOT_PROGRESS_UPDATES` | `true` | Shows the status reaction and the status message |
| `IMBI_SLACKBOT_STATUS_EMOJI` | `hourglass_flowing_sand` | The status reaction |
| `IMBI_SLACKBOT_IDENTITY_CACHE_TTL` | `900` | Seconds to keep a Slack user to Imbi user result |
| `IMBI_SLACKBOT_PROMPT_REF` | `imbi-slackbot/system@stable` | The CMS prompt |
| `IMBI_SLACKBOT_SYSTEM_PROMPT` | none | Replaces the CMS prompt |
| `IMBI_INTERNAL_API_URL` | `http://localhost:8000` | Where the bot connects to imbi-api |
| `IMBI_UI_URL` | none | The public URL of the UI, for links in answers |
| `IMBI_INTERNAL_UI_URL` | none | Where the bot reads `llms.txt`. The default is `IMBI_UI_URL` |

The bot also needs `POSTGRES_URL` (the graph, to find users) and
`IMBI_AUTH_JWT_SECRET`. Use the same JWT secret as imbi-api. With a
different secret, imbi-api refuses every tool call.

When the bot is off, or a Slack token is missing, the service starts but
does not connect to Slack.

To show the bot in the **System health** card of the Admin overview, set
`IMBI_INTERNAL_SLACKBOT_URL` on imbi-api, for example
`http://imbi-slackbot:8004`.
