# Assistant

`imbi-assistant` is the chat service behind the assistant panel in the top
bar and the **Assistant** page of the UI. It answers questions with live
Imbi data. It uses a Claude model through the Anthropic API.

The assistant runs on port 8002. The all-in-one image serves it under
`/assistant`. For how a person uses it, see
[Search and the Assistant](../user-guide/search-and-assistant.md).

## What it does

For each message, the assistant sends the conversation to the model with a
system prompt and a set of tools. The model can call tools for up to
`IMBI_ASSISTANT_MAX_TOOL_ROUNDS` rounds. Then the assistant streams the
answer to the browser as server-sent events.

The tools come from four sources:

| Source | Tools |
|---|---|
| imbi-api | One tool for each operation in the imbi-api OpenAPI spec. The auth, MFA, status, and thumbnail routes, and the operations that imbi-api marks as not for AI, are not tools |
| The assistant | `refresh_openapi_spec`: reads the spec again and reconnects to the MCP servers |
| The browser | `navigate_to` opens a page of the UI. `refresh_data` reloads the data on the page. The UI runs these tools, not the server |
| MCP servers | The tools of each enabled MCP server at **Admin > Global Admin > Assistant > MCP Servers** |

The assistant calls imbi-api with the token of the person who sent the
message. So imbi-api applies that person's permissions to each tool call.
The assistant does not remove the tools that the person cannot use. A call
without the permission gets `403` from imbi-api.

The system prompt tells the model the name and the permissions of the
person, the names of the tools, and the URL patterns of the UI. The
assistant reads the URL patterns from `llms.txt` of the UI at startup.

## Conversations

The assistant stores each conversation and its messages in the graph. A
conversation belongs to one user. Other users cannot read it.

A conversation has a model. A new conversation uses the first of these that
is set:

1. The model in the request.
2. The model of the prompt version, when the assistant can call it.
3. `IMBI_ASSISTANT_MODEL`.

A conversation stops at `IMBI_ASSISTANT_MAX_CONVERSATION_TURNS` messages.
Then the person must start a new conversation.

## The system prompt

The assistant reads its prompt from the [prompt CMS](../admin/prompts.md),
at `IMBI_ASSISTANT_PROMPT_REF` (default `imbi-assistant/system@stable`).

- When the CMS has no usable version, the assistant uses the prompt in the
  `imbi-common` package.
- `IMBI_ASSISTANT_SYSTEM_PROMPT` replaces both. It uses Jinja syntax, for
  example `{{ display_name }}`.

When the prompt version names the conversation's model, its max tokens and
temperature apply. Otherwise `IMBI_ASSISTANT_MAX_TOKENS` applies.

To edit the prompt and the MCP servers, see
[Assistant and MCP Servers](../admin/assistant-and-mcp-servers.md).

## Authentication

Each request needs a bearer token of an Imbi user: the access token of the
UI session, or an `ik_` API key of a user. The assistant verifies it with
`IMBI_AUTH_JWT_SECRET`, as imbi-api does. A service account cannot use the
assistant, because a conversation must belong to a user.

## Settings

The full list is in [Configuration](../api/configuration.md).

| Variable | Default | What it is |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | The Anthropic API key. When it is set, the assistant turns on |
| `IMBI_ASSISTANT_ENABLED` | `false` | Turns the assistant on. A set `ANTHROPIC_API_KEY` also turns it on |
| `IMBI_ASSISTANT_MODEL` | `claude-sonnet-4-6` | The model when the prompt names none |
| `IMBI_ASSISTANT_MAX_TOKENS` | `16384` | The maximum output tokens of one answer |
| `IMBI_ASSISTANT_MAX_CONVERSATION_TURNS` | `100` | The maximum messages in one conversation |
| `IMBI_ASSISTANT_MAX_TOOL_ROUNDS` | `10` | The maximum tool rounds for one message |
| `IMBI_ASSISTANT_MAX_TOOL_RESULT_CHARS` | `120000` | A longer tool result is cut, with a notice to the model |
| `IMBI_ASSISTANT_PROMPT_REF` | `imbi-assistant/system@stable` | The CMS prompt |
| `IMBI_ASSISTANT_SYSTEM_PROMPT` | none | Replaces the CMS prompt |
| `IMBI_ASSISTANT_URL` | none | The public URL of the assistant, for example `https://imbi.example.com/assistant`. Its path is the route prefix |
| `IMBI_INTERNAL_API_URL` | `http://localhost:8000` | Where the assistant connects to imbi-api |
| `IMBI_UI_URL` | none | The public URL of the UI, for links in answers |
| `IMBI_INTERNAL_UI_URL` | none | Where the assistant reads `llms.txt`. The default is `IMBI_UI_URL` |

The assistant also needs `POSTGRES_URL` (the graph) and
`IMBI_AUTH_JWT_SECRET`. It decrypts the credentials of MCP servers with
`IMBI_CONFIG_ENCRYPTION_KEY`.

When the assistant is off, or has no API key, the conversation endpoints
return `503`.

## Endpoints

The paths are relative to the path of `IMBI_ASSISTANT_URL`, for example
`/assistant`.

| Method | Path | What it does |
|---|---|---|
| `POST` | `/conversations` | Creates a conversation |
| `GET` | `/conversations` | Lists your conversations |
| `GET` | `/conversations/{id}` | Gets a conversation with its messages |
| `PATCH` | `/conversations/{id}` | Changes the title, or archives the conversation |
| `DELETE` | `/conversations/{id}` | Deletes a conversation |
| `POST` | `/conversations/{id}/messages` | Sends a message. The answer is a `text/event-stream` |
| `GET` | `/status` | The health check. It has no prefix |

To show the assistant in the **System health** card of the Admin overview,
set `IMBI_INTERNAL_ASSISTANT_URL` on imbi-api, for example
`http://imbi-assistant:8002`.
