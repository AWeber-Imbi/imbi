# Prompts

The **Prompts** section is Imbi's prompt CMS. A prompt is a versioned
template. Each version holds the text, the model, and the model
parameters as one unit, and cannot change after it is saved. A **label**
(for example `stable`) points at one version. Consumers ask for
`namespace/slug@label`.

Moving a label changes what consumers run, so it needs the
`prompt:promote` permission. A prompt created by someone without that
permission has no labels: its version 1 exists, but no reference
resolves until a promote holder points a label at a version. Until
then, a consumer such as the assistant keeps using its packaged prompt.

Open the full library at **Admin > Global Admin > Prompts**. The
assistant's prompt is also on the **Prompt** tab of **Admin > Global
Admin > Assistant**.

## Prompts Imbi uses

| Consumer | Prompt | Setting that names it |
|---|---|---|
| imbi-assistant | `imbi-assistant/system@stable` | `IMBI_ASSISTANT_PROMPT_REF` |
| imbi-slackbot | `imbi-slackbot/system@stable` | `IMBI_SLACKBOT_PROMPT_REF` |

Each consumer reads its prompt on every turn, so a promotion takes
effect on the next message. An assistant conversation keeps the model
it started with.

### Create the default prompts

Run this once after an upgrade:

```shell
imbi-api setup-prompts
```

It creates each prompt above from the template packaged with Imbi, with
version 1 and a `stable` label. A prompt that already exists is not
changed. `imbi-api setup` runs the same step on a new install.

Until a prompt exists, its consumer uses the packaged template. If the
CMS version cannot be read or rendered, the consumer logs a warning and
uses the packaged template too, so a broken edit cannot stop the
assistant.

### Template variables

Templates use Jinja syntax: `{{ display_name }}`. The consumers pass:

| Variable | Assistant | Slack bot |
|---|---|---|
| `display_name`, `email` | Yes | Yes |
| `admin_flag` (`  [Admin]` or empty) | Yes | Yes |
| `perms_section` | Yes | No |
| `tools_section` | Yes | Yes |
| `links_section` | Yes | Yes |

A version receives only the variables its schema declares, so you can
remove one from a version without breaking it.

### Model and parameters

When a version sets `max_tokens` or `temperature`, the consumer uses
them. When a version names a catalog model, the consumer uses it only if
the model is enabled and an **Anthropic** provider serves it; otherwise
it logs a warning and uses its configured model (`IMBI_ASSISTANT_MODEL`,
`IMBI_SLACKBOT_MODEL`). A request that names a model explicitly still
wins.

### Environment override

`IMBI_ASSISTANT_SYSTEM_PROMPT` and `IMBI_SLACKBOT_SYSTEM_PROMPT` replace
both the CMS and the packaged template.

!!! warning
    These overrides now use Jinja syntax. An override written for an
    earlier release with `{display_name}` must change to
    `{{ display_name }}`. An override that does not render is ignored,
    and the packaged template is used.

## Decision prompts

A prompt has a kind, chosen when it is created and fixed after that:

- **generative**: a system prompt and messages for a text model.
- **decision**: a state and typed questions for a decision model, such
  as a TypeSafe System One model (`jev-latest`).

Every version of a prompt has the prompt's kind, so moving a label never
changes the shape of the answer a consumer receives. A decision version
must use a decision model, and a generative version a generative model.

### State

The state is one template. When it renders to a JSON object or array,
it is sent as JSON; otherwise it is sent as text. Use `tojson` to place
values safely:

```text
{"service": {{ service | tojson }}, "ticket": {{ ticket | tojson }}}
```

### Questions

Each question has an id (a code identifier), instructions, and criteria
for its type. Instructions and criteria are templates too.

| Type | Answer | Criteria |
|---|---|---|
| `noul` | Probability of yes | Optional: what yes and no mean |
| `choice` | One of the options, with probabilities | 1 to 255 named options; a description is optional |
| `score` | A position on ordered levels | 2 to 10 levels, lowest first |

The same template limits apply as for generative prompts.

### Run

The editor's Run panel renders the version on screen, saved or not, and
calls its decision model with the provider's stored API key. It shows
each typed answer, the token usage, and the request that was sent.
Running needs `prompt:update`, because each run uses provider credit.
The API is `POST /api/organizations/{org}/prompts/run`, with either a
`ref` or an unsaved `draft`, plus `variables`.
