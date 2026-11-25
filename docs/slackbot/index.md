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

The bot sends the form as a direct message to the person on the ticket:
the assignee of a person ticket, else the owner.

When the agent has a **Human response SLA** and the request is still open
after it, the bot also posts the form to a team Slack channel. The channel
is the first one that applies:

1. The Slack channel of the owner team of the ticket's first project.
2. The **Slack channel** of the agent.
3. The Slack channel of the agent's owner team.

A team with no Slack channel uses its slug as the channel name. The bot
also posts to that channel at once when it cannot send the direct message
(for example, the person has no Slack user). With no SLA, there is no
later post to the channel, but this post still occurs. Invite the bot to the channel first. The bot looks up a
channel name that it did not find again after 15 minutes.

Any person who can see the form can send it. The bot resolves the request
as that person, so the person needs `ticket:resolve`, and the ticket records
`slack` as the channel. When imbi-api refuses the answer, the bot tells
you why. When someone can still answer (for example, you do not have
`ticket:resolve`), the form opens again. When no one can (someone answered
in the UI first, or the ticket closed), the form closes and shows the
reason. A form stays open for 7 days.

When a person resolves the request, in the UI or in Slack, each form of the
request changes to show the decision and who resolved it. Only a form in a
direct message also shows the answer. A hand-off or a close of the ticket
withdraws its open requests, and their forms show `withdrawn`. Forms that
the bot posted before this release do not change.

## Link previews

When you post a link to an Imbi ticket
(`/tickets/{org}/{short_id}`) or project (`/projects/{id}`), the bot adds a
preview card: a Slack Work Object. A ticket card shows the title, the type
and ID, the status, the priority, and the assignee. A project card shows
the name, the slug, the description, the team, the project types, the
health score, the drift, and the release in the last environment of the
pipeline, with when it was deployed. The drift shows one chip for each
environment, in pipeline order. An environment that is behind the one
before it is red, with the number of days that its oldest change has
waited; the others are green. A red **Release** chip shows unreleased
commits for a releasable project. The drift uses the same rule as the
**Projects** page. Each card has an **Open in Imbi** button; a project
with a deployment plugin also has a **Deployments** button.

The bot reads the item as you, so the card shows only what you can read.
Everyone in the channel sees the card. The bot makes no card in a Slack
Connect channel, or when you have no Imbi account or cannot read the item.
See [Slack App Setup](slack-app-manifest.md#link-previews) for the setup.

## Home tab

Open the Imbi app in Slack and select **Home**. The tab shows what waits on
you in Imbi, for one organization:

| Section | What it shows |
|---|---|
| Needs attention | Incidents on the projects of your teams, agent requests on your tickets, held tickets, critical advisories on packages that your teams' projects deploy, and workflow runs that you started that failed or are stuck. |
| My tickets | Person tickets assigned to you that are not closed, by priority, then rank. |
| Pull requests | Open pull requests that wait on your review, and your open pull requests. You must connect GitHub in Imbi (*Settings*). |
| Merged, not deployed | Your pull requests merged in the last 90 days that are not in production. |
| Release drift | Projects of your teams with commits since the latest tag. |
| My projects | Score, incidents, and advisories of the projects of your teams. |
| Agent activity | Your agent tickets that run, are paused, or are queued. |
| Document comments | Comments that mention you, or are on your documents, that you did not acknowledge. |

Each section shows 5 items (or 10, see below), then a link to the full list
in Imbi. The bot reads the data as you, so you see only what you can see in
the UI. When the bot cannot read a section, the section shows **Retry**.
The other sections show as usual.

The bot updates the tab when you open it and after each button you click.
**New ticket** opens the `/create-ticket` form. Most other buttons open the
item in Imbi or GitHub. To act on an item, use Imbi.

### Change the layout

- The menu of a section header has **Collapse**, **Hide from Home**,
  **Move up**, **Move down**, and **Customize Home**. You cannot hide
  Needs attention, but you can collapse it.
- **Customize Home** (in the header and in each menu) sets each section to
  Expanded, Collapsed, or Hidden, and sets these options:
    - Hide sections with nothing in them (on by default).
    - Show at most 5 items per section (when off, 10).
    - Count only expanded sections in the header.
- When you are a member of more than one organization, select the
  organization in the header.

Imbi stores the layout in your Imbi profile, so it is the same on each
device.

### Turn on the Home tab

An existing Slack app does not show the tab until you update its
configuration. Add `features.app_home` and the `app_home_opened` event from
[Slack App Setup](slack-app-manifest.md#home-tab) to the app, or reinstall
the app from the new manifest.

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
servers at startup. A server that you disable stops at the next message.
After you add a server or change its settings, restart imbi-slackbot.

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

### Skills

The bot adds the [skills](../admin/prompts.md#skills) of the prompt CMS
to its system prompt, with the description of each skill, and loads the
instructions of a skill when a request matches it. Ask the bot to create
or change a skill, and it writes the prompt for you.

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
