"""``/create-ticket``: the New ticket dialog of the UI, as a Slack modal.

The modal has the fields of the dialog. It reads its choices from
imbi-api and creates the ticket through imbi-api as the Slack user who
ran the command, so the API checks the permissions of that user and
records the ``slack`` channel.

Slack sends the values of a modal only on a dispatched action and on
submit. Each change that alters the form (organization, assignee kind,
type, priority, labels, prerequisites, roles) builds the view again
from the current values. The custom fields come from the ticket schema
of the organization, type, priority, and labels, the same as in the UI.

"""

from __future__ import annotations

import datetime
import logging
import re
import time
import typing
import uuid
from collections import abc

import httpx
import orjson
from slack_sdk import errors
from slackwright import blocks as block_kit

from imbi.common import labels as ticket_labels
from imbi.slackbot import identity, links

SlackClient = typing.Any
type Json = dict[str, typing.Any]

LOGGER = logging.getLogger(__name__)

COMMAND = '/create-ticket'
CALLBACK_ID = 'ct:form'

# Each input uses the id as its action id. The block id is the same,
# except after a change of organization (see ``_block_id``).
ORG = 'ct:org'
SUBJECT = 'ct:subject'
DESCRIPTION = 'ct:description'
KIND = 'ct:kind'
AGENT = 'ct:agent'
PERSON = 'ct:person'
TYPE = 'ct:type'
PRIORITY = 'ct:priority'
DUE = 'ct:due'
PROJECTS = 'ct:projects'
LABELS = 'ct:labels'
OWNER = 'ct:owner'
TEAM = 'ct:team'
ROLE_NAME = 'ct:role-name:'
ROLE_PERSON = 'ct:role-person:'
ROLE_ADD = 'ct:role-add'
ROLE_REMOVE = 'ct:role-remove'
PARENT = 'ct:parent'
REQUIRES = 'ct:requires'
GATING = 'ct:gating'
FIELD = 'ct:field:'
#: The inputs whose values do not name things of an organization.
_STABLE = frozenset({ORG, SUBJECT, DESCRIPTION, KIND, TYPE, PRIORITY, DUE})

#: The actions that build the view again. An input with one of these
#: ids dispatches its changes.
DISPATCH = re.compile(
    r'^ct:(org|kind|type|priority|labels|requires|role-add|role-remove)$'
)
#: The selects that search imbi-api as the person types.
SEARCH = re.compile(
    r'^ct:(agent|person|owner|role-person:\d+|projects|labels|team'
    r'|parent|requires)$'
)

TYPES = (('bug', 'Bug'), ('task', 'Task'), ('feature', 'Feature'))
PRIORITIES = ('low', 'normal', 'high', 'urgent')
#: The limits of the API.
MAX_ROLES = 10
MAX_LABELS = 20
MAX_LINKS = 50
#: The tickets that a ticket search shows, as in the UI.
TICKETS_SHOWN = 8
#: The most text that a Slack option shows.
_OPTION_TEXT = 75
_OPTION_VALUE = 150
_MAX_OPTIONS = 100
#: Seconds that a response of imbi-api stays in the cache.
_CACHE_TTL = 60.0
#: The state key and the initial value key of each Slack element kind.
_SLOTS = {
    'datepicker': ('selected_date', 'initial_date'),
    'plain_text_input': ('value', 'initial_value'),
    'number_input': ('value', 'initial_value'),
}
_MANY = ('selected_options', 'initial_options')
_ONE = ('selected_option', 'initial_option')

_NO_USER = (
    'There is no Imbi user with your Slack email. Ask an Imbi '
    'administrator to make sure that your account exists and is active.'
)
_NO_ORG = 'You are not a member of an Imbi organization.'
_UNAVAILABLE = 'Imbi is not available. Try again.'
_PLACEHOLDER = (
    'The outcome you want. Paste a Sentry issue, pull request, or Slack '
    'thread link to use it as the source.'
)

#: ponytail: one entry per user and list, removed only when read after
#: it expires; add a size bound if the slackbot serves many users.
_cache: dict[tuple[str, str, str], tuple[float, typing.Any]] = {}


def register(app: typing.Any) -> None:
    """Add the listeners of the command and its modal to a Bolt app."""
    app.command(COMMAND)(on_command)
    app.action(DISPATCH)(on_action)
    app.options(SEARCH)(on_options)
    app.view(CALLBACK_ID)(on_submit)


# --- Listeners ---------------------------------------------------------


async def on_command(ack: typing.Any, body: Json, client: SlackClient) -> None:
    """Open the modal. The text after the command is the description."""
    await ack()
    # A trigger id expires after 3 seconds, so the modal opens before
    # the calls to imbi-api.
    opened = await client.views_open(
        trigger_id=body['trigger_id'], view=message_view('Loading…')
    )
    view_id = opened['view']['id']
    try:
        user = await identity.resolve(client, body['user_id'])
        if user is None:
            await _show(client, view_id, message_view(_NO_USER))
            return
        me = await _get(user, '/users/me')
        memberships: list[Json] = me.get('organizations') or []
        orgs = [
            [
                m['organization_slug'],
                m['organization_name'],
                bool(me.get('is_admin'))
                or 'ticket:manage' in (m.get('permissions') or ()),
            ]
            for m in memberships
        ]
        if not orgs:
            await _show(client, view_id, message_view(_NO_ORG))
            return
        meta: Json = {
            'org': orgs[0][0],
            'orgs': orgs,
            'me': [user.email, user.display_name],
            'roles': 0,
            'extra': {},
            # One key for each form, so that a submit again after a
            # timeout does not create a second ticket.
            'key': f'slack:{uuid.uuid4()}',
        }
        values: Json = {DESCRIPTION: (body.get('text') or '').strip()}
        sections = await _schema(user, meta['org'], values)
        await _show(client, view_id, form_view(meta, values, sections))
    except Exception:
        LOGGER.exception('Could not open %s', COMMAND)
        await _show(client, view_id, message_view(_UNAVAILABLE))


async def on_action(ack: typing.Any, body: Json, client: SlackClient) -> None:
    """Build the view again after a change that alters the form."""
    await ack()
    view = body['view']
    meta = _meta(view)
    values = read_values(view)
    values[GATING] = gating(view, values)
    action = body['actions'][0]['action_id']
    if action == ORG:
        meta['org'] = _value(values, ORG) or meta['org']
        meta['extra'] = {}
        meta['gen'] = meta.get('gen', 0) + 1
        # The other fields name things of the old organization.
        values = {
            k: values.get(k)
            for k in (SUBJECT, DESCRIPTION, KIND, TYPE, PRIORITY, DUE)
        }
    elif action == ROLE_ADD:
        meta['roles'] = min(meta['roles'] + 1, MAX_ROLES)
    elif action == ROLE_REMOVE:
        meta['roles'] = max(meta['roles'] - 1, 0)
    user = await identity.resolve(client, body['user']['id'])
    if user is None:
        return
    sections: list[Json] = []
    try:
        sections = await _schema(user, meta['org'], values)
    except Exception:
        LOGGER.exception('Could not read the ticket schema')
    try:
        await client.views_update(
            view_id=view['id'],
            hash=view['hash'],
            view=form_view(meta, values, sections),
        )
    except errors.SlackApiError as err:
        response: typing.Any = err.response
        # A faster second change already replaced the view.
        if response.get('error') != 'hash_conflict':
            raise


async def on_options(ack: typing.Any, body: Json, client: SlackClient) -> None:
    """Return the choices of a search select."""
    options: list[Json] = []
    try:
        user = await identity.resolve(client, body['user']['id'])
        if user is not None:
            options = await search(
                user,
                _meta(body['view'])['org'],
                body['action_id'],
                (body.get('value') or '').strip(),
            )
    except Exception:
        LOGGER.exception('Could not search for %s', body.get('action_id'))
    await ack(options=options[:_MAX_OPTIONS])


async def on_submit(ack: typing.Any, body: Json, client: SlackClient) -> None:
    """Create the ticket, then show it, or show the form with errors."""
    view = body['view']
    meta = _meta(view)
    values = read_values(view)
    # The submit can come before the view that shows the gating input.
    values[GATING] = gating(view, values)
    problems = check(meta, values)
    if problems:
        errors = {_block_id(meta, k): v for k, v in problems.items()}
        await ack(response_action='errors', errors=errors)
        return
    # The subject can need the model, which takes longer than the 3
    # seconds that Slack waits for an answer.
    await ack(response_action='update', view=message_view('Creating…'))
    view_id = view['id']
    try:
        user = await identity.resolve(client, body['user']['id'])
        if user is None:
            await _show(client, view_id, message_view(_NO_USER))
            return
        result = await create(user, meta, values)
    except Exception:
        LOGGER.exception('Could not create a ticket')
        result = form_view(meta, values, [], notice=_UNAVAILABLE)
    await _show(client, view_id, result)


# --- Create ------------------------------------------------------------


async def create(user: identity.ImbiUser, meta: Json, values: Json) -> Json:
    """Create the ticket. Return the view to show: the ticket or the form
    with the errors."""
    org = meta['org']
    sections = await _schema(user, org, values)
    fields = required_fields(sections, meta['extra'])
    custom, field_errors = custom_fields(fields, values)
    if field_errors:
        return form_view(meta, values, sections, field_errors)
    description = (values.get(DESCRIPTION) or '').strip()
    gates = set(_values_of(values, GATING))
    body: Json = {
        'title': (values.get(SUBJECT) or '').strip(),
        'description': description,
        'type': _value(values, TYPE) or 'task',
        'priority': _value(values, PRIORITY) or 'normal',
        'due_date': values.get(DUE) or None,
        'project_ids': _values_of(values, PROJECTS),
        'labels': _values_of(values, LABELS),
        'team': _value(values, TEAM),
        'roles': roles(meta, values),
        'requires': [
            {'short_id': short_id, 'gates': short_id in gates}
            for short_id in _values_of(values, REQUIRES)
        ],
        'custom_fields': custom,
        'idempotency_key': meta.get('key'),
    }
    if _person(values):
        body.update(assignee_kind='person', assignee=_value(values, PERSON))
    else:
        body.update(assignee_kind='agent', agent_slug=_value(values, AGENT))
    async with identity.api_client(user) as client:
        if not body['title']:
            # The API writes the first line when the model cannot.
            response = await client.post(
                f'{_tickets(org)}/subject', json={'description': description}
            )
            if not response.is_success:
                return form_view(
                    meta, values, sections, notice=error_text(response)
                )
            body['title'] = response.json()['subject']
        response = await client.post(f'{_tickets(org)}/', json=body)
        if not response.is_success:
            return _refused(meta, values, sections, response)
        ticket: Json = response.json()
        short_id = ticket['short_id']
        warnings: list[str] = []
        parent = _value(values, PARENT)
        if parent:
            warnings += await _step(
                client.put(
                    f'{_ticket(org, short_id)}/parent', json={'parent': parent}
                )
            )
        owner = _value(values, OWNER)
        if owner and owner != meta['me'][0]:
            warnings += await _step(
                client.post(
                    f'{_ticket(org, short_id)}/reassign', json={'owner': owner}
                )
            )
    return created_view(org, ticket, _assignee_name(values), warnings)


async def _step(call: abc.Awaitable[httpx.Response]) -> list[str]:
    """Run a step after the create. A failure is a warning, as in the UI."""
    try:
        response = await call
    except httpx.HTTPError:
        return [_UNAVAILABLE]
    return [] if response.is_success else [error_text(response)]


def _refused(
    meta: Json, values: Json, sections: list[Json], response: httpx.Response
) -> Json:
    """Return the form with the errors of a refused create."""
    detail = identity.response_detail(response)
    found = typing.cast('Json', detail) if isinstance(detail, dict) else {}
    if found.get('error') != 'custom_fields_invalid':
        return form_view(meta, values, sections, notice=error_text(response))
    field_errors: dict[str, str] = {}
    # The schema here can be older than the one of the API: ask for each
    # field that the API says is missing.
    missing: list[Json] = found.get('missing') or []
    invalid: list[Json] = found.get('invalid') or []
    for item in missing:
        prop: Json = dict(item)
        key = prop.pop('field')
        meta['extra'][key] = prop
        field_errors[FIELD + key] = 'Required'
    for item in invalid:
        field_errors[FIELD + item['field']] = item['message']
    return form_view(meta, values, sections, field_errors)


# --- Checks ------------------------------------------------------------


def check(meta: Json, values: Json) -> dict[str, str]:
    """Return the errors that need no call to imbi-api, by block id."""
    problems: dict[str, str] = {}
    due = values.get(DUE)
    today = datetime.datetime.now(datetime.UTC).date()
    if due and datetime.date.fromisoformat(due) < today:
        problems[DUE] = 'Pick today or a later date.'
    for i in range(meta['roles']):
        name = (values.get(ROLE_NAME + str(i)) or '').strip()
        person = values.get(ROLE_PERSON + str(i))
        if name and not person:
            problems[ROLE_PERSON + str(i)] = 'Pick a person for the role.'
        elif person and not name:
            problems[ROLE_NAME + str(i)] = 'Name the role.'
    parent = _value(values, PARENT)
    if parent and parent in _values_of(values, REQUIRES):
        problems[PARENT] = 'The parent cannot also be a prerequisite.'
    return problems


def roles(meta: Json, values: Json) -> dict[str, str]:
    """Return the roles of the role rows, as ``{name: email}``."""
    result: dict[str, str] = {}
    for i in range(meta['roles']):
        name = (values.get(ROLE_NAME + str(i)) or '').strip()
        email = _value(values, ROLE_PERSON + str(i))
        if name and email:
            result[name] = email
    return result


# --- Custom fields -----------------------------------------------------


def required_fields(sections: list[Json], extra: Json) -> Json:
    """Return the required custom fields with no default, by key
    (``requiredBlueprintFields`` of the UI), and the ``extra`` fields
    that the API said are missing."""
    fields: Json = {}
    for section in sections:
        required: list[str] = section.get('required') or []
        properties: Json = section.get('properties') or {}
        for key, prop in properties.items():
            if key not in required or prop.get('default') is not None:
                fields.pop(key, None)
            else:
                fields[key] = prop
    return {**fields, **extra}


def custom_fields(fields: Json, values: Json) -> tuple[Json, dict[str, str]]:
    """Return the custom field values of the form, and the errors."""
    result: Json = {}
    problems: dict[str, str] = {}
    for key, prop in fields.items():
        try:
            value = _field_value(prop, values.get(FIELD + key))
        except ValueError as err:
            problems[FIELD + key] = str(err)
            continue
        if value is not None:
            result[key] = value
    return result, problems


def _field_value(prop: Json, raw: typing.Any) -> typing.Any:  # noqa: PLR0911
    kind = prop.get('type')
    # An unchecked required boolean means false, not "not set".
    if kind == 'boolean' and not prop.get('enum'):
        return bool(raw)
    if raw in (None, '', []):
        return None
    if prop.get('enum'):
        return orjson.loads(raw['value'])
    items: Json = prop.get('items') or {}
    if kind == 'array':
        if items.get('enum'):
            return [orjson.loads(o['value']) for o in raw]
        return [line.strip() for line in raw.splitlines() if line.strip()]
    if kind == 'integer':
        return int(raw)
    if kind == 'number':
        return float(raw)
    if kind == 'object':
        try:
            value = orjson.loads(raw)
        except orjson.JSONDecodeError:
            value = None
        if not isinstance(value, dict):
            raise ValueError('Enter a JSON object.')
        return typing.cast('Json', value)
    return raw


def _field_element(prop: Json, title: str) -> tuple[Json, str | None]:
    """Return the element of a custom field, and its hint."""
    kind = prop.get('type')
    items: Json = prop.get('items') or {}
    enum: list[typing.Any] = prop.get('enum') or items.get('enum') or []
    if enum:
        options = [_option(str(v), orjson.dumps(v).decode()) for v in enum]
        many = kind == 'array'
        return {
            'type': 'multi_static_select' if many else 'static_select',
            'options': options[:_MAX_OPTIONS],
        }, None
    if kind == 'boolean':
        return {
            'type': 'checkboxes',
            'options': [_option(title, 'true')],
        }, None
    if kind in ('integer', 'number'):
        element: Json = {
            'type': 'number_input',
            'is_decimal_allowed': kind == 'number',
        }
        for limit, name in (
            ('minimum', 'min_value'),
            ('maximum', 'max_value'),
        ):
            if prop.get(limit) is not None:
                element[name] = str(prop[limit])
        return element, None
    if kind == 'string' and prop.get('format') == 'date':
        return {'type': 'datepicker'}, None
    if kind in ('array', 'object'):
        hint = 'One per line.' if kind == 'array' else 'A JSON object.'
        return {'type': 'plain_text_input', 'multiline': True}, hint
    return {'type': 'plain_text_input'}, None


# --- Views -------------------------------------------------------------


def message_view(text: str) -> Json:
    return {
        'type': 'modal',
        'title': _text('New ticket'),
        'close': _text('Close'),
        'blocks': [{'type': 'section', 'text': _md(text)}],
    }


def created_view(
    org: str, ticket: Json, assignee: str, warnings: list[str]
) -> Json:
    """The view after the create: the ticket, and what happens next
    (``FooterHint`` of the UI)."""
    short_id = ticket['short_id']
    url = links.ticket_url(org, short_id)
    name = f'<{url}|{short_id}>' if url else short_id
    if ticket.get('status') == 'held':
        next_step = 'Starts held: it waits on its gating prerequisites.'
    elif ticket.get('assignee_kind') == 'person':
        next_step = f'Assigned to {assignee}.'
    else:
        next_step = f'Runs now with {assignee}.'
    blocks: list[Json] = [
        {
            'type': 'section',
            'text': _md(f'*{name}* · {_escape(ticket.get("title") or "")}'),
        },
        {'type': 'context', 'elements': [_md(_escape(next_step))]},
    ]
    blocks += [
        {
            'type': 'context',
            'elements': [
                _md(f':warning: {short_id} was created, but: {_escape(w)}')
            ],
        }
        for w in warnings
    ]
    return {
        'type': 'modal',
        'title': _text('Ticket created'),
        'close': _text('Done'),
        'blocks': blocks,
    }


def form_view(
    meta: Json,
    values: Json,
    sections: list[Json],
    problems: dict[str, str] | None = None,
    notice: str | None = None,
) -> Json:
    """Return the modal of the form with ``values`` filled in.

    A view that Slack shows with ``views.update`` cannot mark an input
    as wrong, so ``problems`` show as the hint of each input.

    """
    problems = problems or {}

    def field(
        block_id: str,
        label: str,
        element: Json,
        *,
        optional: bool = False,
        hint: str | None = None,
    ) -> Json:
        return _field(
            meta, values, problems, block_id, label, element, optional, hint
        )

    blocks: list[Json] = []
    if notice:
        blocks.append(
            {'type': 'section', 'text': _md(f':warning: {_escape(notice)}')}
        )
    if len(meta['orgs']) > 1:
        org_options = [_option(name, slug) for slug, name, _ in meta['orgs']]
        values[ORG] = _pick(org_options, None, meta['org'])
        blocks.append(
            field(
                ORG,
                'Organization',
                {'type': 'static_select', 'options': org_options},
            )
        )
    kinds = [_option('Agent', 'agent'), _option('Person', 'person')]
    values[KIND] = _pick(kinds, values.get(KIND), 'agent')
    blocks += [
        field(
            SUBJECT,
            'Subject',
            {'type': 'plain_text_input', 'max_length': 500},
            optional=True,
            hint='Leave empty to have it written from the description.',
        ),
        field(
            DESCRIPTION,
            'Describe the work',
            {
                'type': 'plain_text_input',
                'multiline': True,
                'placeholder': _text(_PLACEHOLDER),
            },
        ),
        field(KIND, 'Assign to', {'type': 'radio_buttons', 'options': kinds}),
        field(
            PERSON,
            'Person',
            _search('Choose a person'),
            hint='Starts open. Person tickets have no agent, budget, or '
            'run controls.',
        )
        if _person(values)
        else field(AGENT, 'Agent', _search('Choose an agent')),
    ]
    type_options = [_option(label, value) for value, label in TYPES]
    priority_options = [_option(p.capitalize(), p) for p in PRIORITIES]
    values[TYPE] = _pick(type_options, values.get(TYPE), 'task')
    values[PRIORITY] = _pick(priority_options, values.get(PRIORITY), 'normal')
    blocks += [
        field(
            TYPE, 'Type', {'type': 'static_select', 'options': type_options}
        ),
        field(
            PRIORITY,
            'Priority',
            {'type': 'static_select', 'options': priority_options},
        ),
        field(DUE, 'Due', {'type': 'datepicker'}, optional=True),
        field(
            PROJECTS,
            'Projects',
            _search('Search projects', limit=MAX_LINKS),
            optional=True,
        ),
        field(
            LABELS,
            'Labels',
            _search('Add labels', limit=MAX_LABELS),
            optional=True,
        ),
    ]
    for key, prop in required_fields(sections, meta['extra']).items():
        title = str(prop.get('title') or key)
        element, hint = _field_element(prop, title)
        blocks.append(
            field(
                FIELD + key,
                title,
                element,
                # Slack cannot require a checkbox: unchecked is false.
                optional=element['type'] == 'checkboxes',
                hint=hint or prop.get('description'),
            )
        )
    blocks.append({'type': 'divider'})
    blocks.append(_owner_block(meta, values, field))
    blocks += [
        field(
            TEAM,
            'Team',
            _search('Choose a team'),
            optional=True,
            hint='The team that owns the work.',
        ),
        *_role_blocks(meta, values, problems),
        field(
            PARENT,
            'Parent',
            _search('Search tickets by ID or title'),
            optional=True,
            hint='Optional. Closed parents are allowed.',
        ),
        field(
            REQUIRES,
            'Prerequisites',
            _search('Add a prerequisite ticket', limit=MAX_LINKS),
            optional=True,
        ),
    ]
    requires: list[Json] = values.get(REQUIRES) or []
    if requires:
        blocks.append(
            field(
                GATING,
                'Gating',
                # Checkboxes show at most 10 options.
                {'type': 'multi_static_select', 'options': requires},
                optional=True,
                hint='A gating prerequisite holds the ticket until it closes '
                'as done.',
            )
        )
    return {
        'type': 'modal',
        'callback_id': CALLBACK_ID,
        'title': _text('New ticket'),
        'submit': _text('Create ticket'),
        'close': _text('Cancel'),
        'private_metadata': orjson.dumps(meta).decode(),
        'blocks': blocks,
    }


def _field(
    meta: Json,
    values: Json,
    problems: dict[str, str],
    action_id: str,
    label: str,
    element: Json,
    optional: bool = False,
    hint: str | None = None,
) -> Json:
    """Return an input block with its value from ``values``."""
    element = {**element, 'action_id': action_id}
    value = values.get(action_id)
    if value not in (None, '', []):
        element[_slot(element['type'])[1]] = value
    block: Json = {
        'type': 'input',
        'block_id': _block_id(meta, action_id),
        'label': _text(label),
        'optional': optional,
        'element': element,
    }
    if action_id in problems:
        hint = f'⚠ {problems[action_id]}'
    if hint:
        block['hint'] = _text(hint)
    if DISPATCH.match(action_id):
        block['dispatch_action'] = True
    return block


def _block_id(meta: Json, action_id: str) -> str:
    """Return the block id of an input. Slack keeps the value of an
    input whose block id does not change, so each change of organization
    gives new block ids to the inputs of the organization."""
    gen = meta.get('gen', 0)
    if not gen or action_id in _STABLE:
        return action_id
    return f'{action_id}@{gen}'


def _owner_block(
    meta: Json, values: Json, field: abc.Callable[..., Json]
) -> Json:
    """Return the owner select, or a note when the user cannot pick
    another owner."""
    email, display_name = meta['me']
    if not next(m for s, _, m in meta['orgs'] if s == meta['org']):
        return {
            'type': 'context',
            'elements': [
                _md(
                    '*Owner:* you. Accountable for the outcome. Another '
                    'owner needs ticket:manage.'
                )
            ],
        }
    values[OWNER] = values.get(OWNER) or _option(
        f'You ({display_name})', email
    )
    return field(
        OWNER,
        'Owner',
        _search('Choose the owner'),
        hint='Accountable for the outcome. Defaults to you; can differ from '
        'the assignee.',
    )


def _role_blocks(
    meta: Json, values: Json, problems: dict[str, str]
) -> list[Json]:
    blocks: list[Json] = [
        {
            'type': 'section',
            'text': _md(
                '*Roles*\nWorkflows read roles and can hand the ticket to '
                'the person in a role.'
            ),
        }
    ]
    for i in range(meta['roles']):
        blocks += [
            _field(
                meta,
                values,
                problems,
                ROLE_NAME + str(i),
                f'Role {i + 1}',
                {
                    'type': 'plain_text_input',
                    'max_length': 100,
                    'placeholder': _text('reviewer, qa, approver…'),
                },
                optional=True,
            ),
            _field(
                meta,
                values,
                problems,
                ROLE_PERSON + str(i),
                f'Person in role {i + 1}',
                _search('Choose a person'),
                optional=True,
            ),
        ]
    buttons: list[Json] = []
    if meta['roles'] < MAX_ROLES:
        buttons.append(_button('Add role', ROLE_ADD))
    if meta['roles']:
        buttons.append(_button('Remove last role', ROLE_REMOVE))
    blocks.append({'type': 'actions', 'elements': buttons})
    return blocks


# --- State -------------------------------------------------------------


def read_values(view: Json) -> Json:
    """Return the values of the inputs of ``view``, by action id.

    A select gives its option, a multi-select and checkboxes give a list
    of options, a text or number input gives a string.

    """
    values: Json = {}
    root: Json = view.get('state') or {}
    state: dict[str, Json] = root.get('values') or {}
    for actions in state.values():
        for action_id, entry in actions.items():
            key = _slot(entry['type'])[0]
            values[action_id] = entry.get(key)
            if key == _MANY[0]:
                values[action_id] = values[action_id] or []
    return values


def gating(view: Json, values: Json) -> list[Json]:
    """Return the gating prerequisites: each prerequisite except those
    that the person unchecked. A new prerequisite gates, as in the UI."""
    listed: set[str] = set()
    blocks: list[Json] = view.get('blocks') or []
    for block in blocks:
        element: Json = block.get('element') or {}
        if element.get('action_id') == GATING:
            listed = {o['value'] for o in block['element']['options']}
    unchecked = listed - set(_values_of(values, GATING))
    requires: list[Json] = values.get(REQUIRES) or []
    return [o for o in requires if o['value'] not in unchecked]


def _slot(kind: str) -> tuple[str, str]:
    """Return the state key and the initial value key of an element."""
    if kind in _SLOTS:
        return _SLOTS[kind]
    return _MANY if kind.startswith('multi_') or kind == 'checkboxes' else _ONE


def _meta(view: Json) -> Json:
    return typing.cast(
        'Json', orjson.loads(view.get('private_metadata') or '{}')
    )


def _person(values: Json) -> bool:
    return _value(values, KIND) == 'person'


def _value(values: Json, block_id: str) -> str | None:
    option = values.get(block_id)
    return option['value'] if option else None


def _values_of(values: Json, block_id: str) -> list[str]:
    options: list[Json] = values.get(block_id) or []
    return [o['value'] for o in options]


def _assignee_name(values: Json) -> str:
    option: Json = values.get(PERSON if _person(values) else AGENT) or {}
    text: Json = option.get('text') or {}
    return str(text.get('text') or 'the assignee')


# --- Search ------------------------------------------------------------


async def search(  # noqa: PLR0911
    user: identity.ImbiUser, org: str, action_id: str, query: str
) -> list[Json]:
    """Return the options of a search select that match ``query``."""
    q = query.lower()
    o = f'/organizations/{org}'
    if action_id == AGENT:
        return _matching(
            await _get(user, f'{o}/agents/'),
            q,
            text=lambda a: (
                f'{a["name"]} — {a["description"]}'
                if a.get('description')
                else a['name']
            ),
            value=lambda a: a['slug'],
            hay=lambda a: (
                f'{a["name"]} {a["slug"]} {a.get("description") or ""}'
            ),
            key=lambda a: a['name'].lower(),
            keep=lambda a: bool(a.get('enabled')),
        )
    if action_id in (PERSON, OWNER) or action_id.startswith(ROLE_PERSON):
        return _matching(
            await _get(user, f'{o}/members'),
            q,
            text=lambda m: (
                f'{m["display_name"]} ({m["email"]})'
                if m.get('display_name')
                else m['email']
            ),
            value=lambda m: m['email'],
            hay=lambda m: f'{m.get("display_name") or ""} {m["email"]}',
            key=lambda m: (m.get('display_name') or m['email']).lower(),
            keep=lambda m: bool(m.get('is_active', True)),
        )
    if action_id == PROJECTS:
        return _matching(
            await _get(user, f'{o}/projects/', slim='true'),
            q,
            text=lambda p: p['slug'],
            value=lambda p: p['id'],
            hay=lambda p: p['slug'],
            key=lambda p: p['slug'],
            keep=lambda p: not p.get('archived'),
        )
    if action_id == TEAM:
        return _matching(
            await _get(user, f'{o}/teams/'),
            q,
            text=lambda t: t['name'],
            value=lambda t: t['slug'],
            hay=lambda t: f'{t["name"]} {t["slug"]}',
            key=lambda t: t['name'].lower(),
        )
    if action_id == LABELS:
        return await _label_options(user, org, query)
    if action_id in (PARENT, REQUIRES):
        params = {'limit': str(TICKETS_SHOWN)}
        if query:
            params['q'] = query
        tickets = await _get(
            user, f'{_tickets(org)}/', cache=not query, **params
        )
        return [
            _option(f'{t["short_id"]} · {t["title"]}', t['short_id'])
            for t in tickets
        ]
    return []


async def _label_options(
    user: identity.ImbiUser, org: str, query: str
) -> list[Json]:
    found = await _get(
        user, f'{_tickets(org)}/labels', cache=not query, q=query
    )
    names = [label['name'] for label in found]
    # A label that does not exist yet is made with the ticket.
    new = ticket_labels.normalize_label(query)
    if new and new not in names:
        names.insert(0, new)
    return [_option(name, name) for name in names]


def _matching(
    rows: list[Json],
    q: str,
    *,
    text: abc.Callable[[Json], str],
    value: abc.Callable[[Json], str],
    hay: abc.Callable[[Json], str],
    key: abc.Callable[[Json], str],
    keep: abc.Callable[[Json], bool] = lambda _: True,
) -> list[Json]:
    """Return the options of the rows to keep whose ``hay`` has ``q``."""
    return [
        _option(text(row), value(row))
        for row in sorted(rows, key=key)
        if keep(row) and q in hay(row).lower()
    ]


# --- imbi-api ----------------------------------------------------------


async def _get(
    user: identity.ImbiUser,
    path: str,
    *,
    cache: bool = True,
    **params: str | list[str],
) -> typing.Any:
    """GET ``path`` as ``user``. With ``cache``, keep the result for a
    short time, so that a search does not load a list again for each key
    that the person types."""
    key = (user.email, path, orjson.dumps(params).decode())
    now = time.monotonic()
    cached = _cache.get(key)
    if cache and cached is not None and cached[0] > now:
        return cached[1]
    async with identity.api_client(user) as client:
        response = await client.get(path, params=params)
    response.raise_for_status()
    data = response.json()
    if cache:
        _cache[key] = (now + _CACHE_TTL, data)
    return data


async def _schema(
    user: identity.ImbiUser, org: str, values: Json
) -> list[Json]:
    """Return the sections of the ticket schema for the type, priority,
    and labels of the form."""
    schema = await _get(
        user,
        f'{_tickets(org)}/schema',
        type=_value(values, TYPE) or 'task',
        priority=_value(values, PRIORITY) or 'normal',
        label=_values_of(values, LABELS),
    )
    return schema.get('sections') or []


def _tickets(org: str) -> str:
    return f'/organizations/{org}/tickets'


def _ticket(org: str, short_id: str) -> str:
    return f'{_tickets(org)}/{short_id}'


def error_text(response: httpx.Response) -> str:
    """Return the message of an error response of imbi-api."""
    detail = identity.response_detail(response)
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        # A validation error of FastAPI: a list of {loc, msg, type}.
        return '; '.join(
            str(d.get('msg', d)) for d in typing.cast('list[Json]', detail)
        )
    if isinstance(detail, dict):
        found = typing.cast('Json', detail)
        return str(found.get('message') or found.get('error') or found)
    return f'Imbi refused it ({response.status_code}).'


# --- Block Kit ---------------------------------------------------------


async def _show(client: SlackClient, view_id: str, view: Json) -> None:
    await client.views_update(view_id=view_id, view=view)


_text = block_kit.plain_text


def _md(text: str) -> Json:
    return {'type': 'mrkdwn', 'text': text}


def _escape(text: str) -> str:
    """Escape text for mrkdwn, so it cannot mention or link."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _option(text: str, value: str) -> Json:
    if len(text) > _OPTION_TEXT:
        text = text[: _OPTION_TEXT - 1] + '…'
    return {'text': _text(text), 'value': value[:_OPTION_VALUE]}


def _pick(options: list[Json], current: Json | None, default: str) -> Json:
    value = (current or {}).get('value') or default
    return next(o for o in options if o['value'] == value)


def _button(text: str, action_id: str) -> Json:
    return {'type': 'button', 'text': _text(text), 'action_id': action_id}


def _search(placeholder: str, *, limit: int | None = None) -> Json:
    """Return a select that searches imbi-api; with ``limit``, a
    multi-select of at most ``limit`` options."""
    element: Json = {
        'type': 'external_select'
        if limit is None
        else 'multi_external_select',
        'placeholder': _text(placeholder),
        'min_query_length': 0,
    }
    if limit is not None:
        element['max_selected_items'] = limit
    return element
