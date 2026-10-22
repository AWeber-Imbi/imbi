# Search and the assistant

The top bar has a search box and an assistant button. Search finds
projects, documents, and catalog items in the selected organization. The
assistant answers questions and does tasks with the Imbi API.

## Search

### Find something

1. Press **Cmd+K** (macOS) or **Ctrl+K** (other systems) on any page. The
   search box in the top bar gets the focus. You can also click the box.
2. Type some words, for example `payment service`.
3. Use the **Up** and **Down** arrow keys to select a result.
4. Press **Enter** to open the selected result.

| Key | What it does |
|---|---|
| **Cmd+K** or **Ctrl+K** | Puts the focus in the search box and selects its text |
| **Up**, **Down** | Moves the selection through the results and the **Ask Imbi** row |
| **Enter** | Opens the selected result. On the **Ask Imbi** row, asks the assistant. When the list is closed, opens it again |
| **Tab** | Asks the assistant. See [Ask the assistant from search](#ask-the-assistant-from-search) |
| **Esc** | Closes the list |

Search starts 200 ms after you stop typing.

### Results

Search is semantic: it compares the meaning of your words with the
meaning of the stored text. A result does not need to contain your exact
words.

The list shows the results in groups. **Projects** is first, then
**Documents**, then the other types. The other groups are **Project
types**, **Link definitions**, and **Document templates**, plus each other
type that the search can open. Each group shows a maximum of 5 results.
A project result also shows the project score.

The search covers the items of the selected organization:

- The organization, its teams, environments, project types, integrations,
  tags, document templates, and link definitions.
- Projects, their releases, and the packages they use.
- Documents of projects, project types, and users, and their comments.

Search does not show items of archived projects. The list shows only
results that it can open, and only results with a close enough match.

When nothing matches, the list shows **No results.** When the search
fails, it shows **Search failed. Try again.**

Search needs the `search:read` permission. The `admin`, `developer`,
`default`, and `readonly` roles have it. The API is
`GET /organizations/{org}/search?q=<text>`.

Imbi updates the search index when you save an item. If search does not
find an item that exists, an administrator can rebuild the index with the
**Reindex Search** maintenance operation. See
[Maintenance](../admin/maintenance.md).

### Ask the assistant from search

The last row of the list is **Ask Imbi about "\<your text\>"**. Press
**Tab**, or select the row and press **Enter**. Imbi then:

1. Starts a new assistant conversation.
2. Opens the assistant panel.
3. Sends your text to the assistant, together with the first 3 search
   results as context.

## The assistant

### Open the assistant

Click the sparkles button in the top bar (its label is **Assistant**). The
assistant panel opens on the right side of the page. Click the button
again, or click **Close** in the panel, or press **Esc** in the panel, to
close it.

The panel stays open when you go to other pages. The page content moves
to the left to make space for it.

### Send a message

1. Type your question in the box at the bottom of the panel. For example:
   `Which projects of the payments team have no PagerDuty service?`
2. Press **Enter** to send. Press **Shift+Enter** to add a new line.
3. Read the answer. The assistant streams it while it writes.

While the assistant works, the panel shows what it does, for example
**Searching projects** or **Running \<tool name\>**. After the answer, the
panel lists the tools that the assistant used.

To stop an answer, click the stop button. Imbi keeps the text that the
assistant wrote before you stopped it.

Each message has these buttons:

| Button | What it does |
|---|---|
| Copy to clipboard | Copies the message text |
| Retry | On an answer: removes the answer and sends the question again |

Each message that you send includes a context block with your name, email
address, roles, and the selected organization. The panel does not show
this block.

### Conversations

Imbi stores each conversation. Only you can see your conversations. The
assistant makes a short title for a conversation from the first question
and answer.

In the panel:

| Button | What it does |
|---|---|
| **History** | Lists your 10 most recent conversations. **All conversations…** opens the full page |
| **New conversation** | Starts an empty conversation |
| **Open full page** | Opens the current conversation at `/assistant/<conversation id>` |

The full page, `/assistant`, lists all your conversations in the groups
**Today**, **Previous 7 days**, and **Older**. Use **Search conversations**
to filter the list by title. Click **New conversation** to start one.
Click **Open in side panel** to go back to the page that you were on, with
the panel open.

The UI cannot rename, archive, or delete a conversation. The assistant API
can: `PATCH /conversations/{id}` renames or archives, and
`DELETE /conversations/{id}` deletes.

A conversation can have a maximum of 100 messages. Then the assistant
answers that the conversation reached the maximum number of turns. Start a
new conversation.

### What the assistant can do

The assistant acts as you. It uses your access token for each call to the
Imbi API. Thus it can read and change only what your roles let you read
and change. The assistant can make changes, for example create a project
or edit a team. It does not ask you to confirm a change first. Read its
plan before you ask it to change something.

The assistant gets its tools from these sources:

| Source | Tools |
|---|---|
| Imbi API | One tool for each API operation, made from the API's OpenAPI document. The sign-in, MFA, and status operations, and each operation marked as not for AI, are not tools |
| MCP servers | The tools of each enabled MCP server in **Admin**. Their names have the form `mcp_<prefix>_<tool>`. See [Assistant and MCP servers](../admin/assistant-and-mcp-servers.md) |
| Browser tools | `navigate_to` opens a page of Imbi in your browser. `refresh_data` reloads the data on the page after a change |
| `refresh_openapi_spec` | Reloads the API tools and reconnects to the MCP servers, without a restart |

In one answer, the assistant can do a maximum of 10 rounds of tool calls
(`IMBI_ASSISTANT_MAX_TOOL_ROUNDS`).

The system prompt comes from the `imbi-assistant/system` prompt in the
prompt CMS. A new conversation uses the model of that prompt version. If
the prompt version has no model, it uses `IMBI_ASSISTANT_MODEL`. A
conversation keeps its model after it starts. An administrator changes
the prompt and the model in the CMS. See [Prompts](../admin/prompts.md). For the service and its settings, see
[Assistant](../assistant/index.md).
