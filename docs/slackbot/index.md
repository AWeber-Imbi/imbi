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
ready. The answer uses Slack's native Markdown, so tables, code blocks,
and links show as written. A long answer is split into more than one
message. Broadcast mentions such as `@here` in an answer do not notify
the channel.

### Start an agent task

Ask the bot to make an agent task, for example: "@imbi create a task to fix
the issue in this thread and give it to mender". You own the task. See
[Tickets](../admin/tickets.md#slack).

### Answer a ticket that needs input

When an agent asks for input (`request_input`) or for an approval, the bot
posts a form with the same choices as the "Waiting on you" box of the ticket:

- A question with options: pick an option, or write an answer. A written
  answer replaces the option.
- A question with no options: write an answer.
- An approval: Approve or Reject. The form lists the artifacts.

The bot posts the form to the **Slack channel** of the agent (`#name` or a
channel id). When the agent has no channel, or the bot cannot find it, the
bot sends the form as a direct message to the owner of the ticket. Invite
the bot to the channel first. The bot looks up a channel name that it did
not find again after 15 minutes.

Any person who can see the form can send it. The bot resolves the request
as that person, so the person needs `ticket:resolve`, and the ticket records
`slack` as the channel. When imbi-api refuses the answer, the bot tells
you why. When someone can still answer (for example, you do not have
`ticket:resolve`), the form opens again. When no one can (someone answered
in the UI first, or the ticket closed), the form closes and shows the
reason. A form stays open for 7 days.

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

The bot also has the tools of each enabled MCP server at
**Admin > Global Admin > Assistant > MCP Servers**, the same as the
assistant. See
[Assistant and MCP Servers](../admin/assistant-and-mcp-servers.md). These
calls use the credentials of the server, not your token. The bot reads the
servers at startup. After you change a server, restart imbi-slackbot.

The bot also has Slack tools from
[slackwright](https://github.com/gmr/slackwright). They work only in the
thread of the message:

- `slack_post_markdown` and `slack_post_blocks` post a message, for example
  a table or a layout with a header. The bot can post 5 messages for each
  message that you send.
- `slack_create_form` posts a form with buttons or a modal. The bot asks
  for structured answers with it, one form for each message that you send.
  When the user who asked for the form submits it, the bot reads the
  answers as a new message in the thread and continues. When another user
  submits it, the bot does not continue: it says so in the thread. A turn
  never mixes the text of one user with the permissions of another. A form expires after seven days. Forms need
  Slack interactivity (see the [app manifest](slack-app-manifest.md)) and
  `VALKEY_URL`.

## The system prompt

The bot reads its prompt from the [prompt CMS](../admin/prompts.md), at
`IMBI_SLACKBOT_PROMPT_REF` (default `imbi-slackbot/system@stable`).
To change the prompt or the model, open **Admin > Global Admin >
Slackbot**. Select the model on the version, then point the `stable`
label at that version.

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
| `IMBI_SLACKBOT_API_TOKEN` | none | The API key of the `imbi-slackbot` service account. When it is set, the bot uses the token of its AI provider ([workload identity](../admin/ai-models.md#imbi-services)) instead of `ANTHROPIC_API_KEY` |
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
| `IMBI_API_URL` | none | The public URL of imbi-api. The bot uses its path, for example `/api`, as the route prefix. It must be an absolute URL |
| `IMBI_UI_URL` | none | The public URL of the UI, for links in answers |
| `IMBI_INTERNAL_UI_URL` | none | Where the bot reads `llms.txt`. The default is `IMBI_UI_URL` |

The bot also needs `POSTGRES_URL` (the graph, to find users), `VALKEY_URL`
(the forms that it posts), and `IMBI_AUTH_JWT_SECRET`. Use the same JWT
secret as imbi-api. With a different secret, imbi-api refuses every tool
call.
It decrypts the credentials of MCP servers with
`IMBI_CONFIG_ENCRYPTION_KEY`. Use the same key as imbi-api.

When the bot is off, or a Slack token is missing, the service starts but
does not connect to Slack.

To show the bot in the **System health** card of the Admin overview, set
`IMBI_INTERNAL_SLACKBOT_URL` on imbi-api, for example
`http://imbi-slackbot:8004`.
