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
