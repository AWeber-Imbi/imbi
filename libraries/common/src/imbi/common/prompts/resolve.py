"""Read prompts and versions from the graph, and resolve references.

A reference is ``namespace/slug``, ``namespace/slug@label``, or
``namespace/slug@n``. ``@n`` names a version. A label the prompt does
not have, or no ``@`` at all, falls back to the prompt's default label.
"""

import collections.abc
import re
import typing

import fastapi

from imbi.common import graph, models

#: ``namespace/slug``, then ``@label`` or ``@n``.
REF_PATTERN = re.compile(
    r'^(?P<namespace>[a-z0-9][a-z0-9._-]*)/(?P<slug>[a-z0-9][a-z0-9._-]*)'
    r'(?:@(?P<label>[a-z0-9][a-z0-9._-]*))?$'
)

PROMPT_QUERY: typing.LiteralString = """
MATCH (p:Prompt {{namespace: {namespace}, slug: {slug}}})
OPTIONAL MATCH (v:PromptVersion)-[:VERSION_OF]->(p)
RETURN p, max(v.n) AS latest
"""

LIST_NAMESPACE_QUERY: typing.LiteralString = """
MATCH (p:Prompt {{namespace: {namespace}}})
WHERE p.archived_at IS NULL
OPTIONAL MATCH (v:PromptVersion)-[:VERSION_OF]->(p)
RETURN p, max(v.n) AS latest
"""

VERSION_QUERY: typing.LiteralString = """
MATCH (v:PromptVersion {{prompt_id: {prompt_id}, n: {n}}})
      -[:VERSION_OF]->(:Prompt {{id: {prompt_id}}})
RETURN v
"""

#: The AI model catalog is per organization. Each catalog query reads
#: only the organizations in ``org_ids``: the organization of the
#: caller, or for a consumer with no organization (a global system
#: prompt of an imbi-api helper) each organization of the user
#: (:func:`member_org_ids`).
MODEL_DRIVER_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{slug: {slug}}})-[:BELONGS_TO]->(o:Organization)
WHERE o.id IN {org_ids}
MATCH (m)-[:SERVED_BY]->(p:AIProvider)
RETURN m.model_id AS model_id, m.enabled AS enabled, p.driver AS driver,
       m.access_scope AS access_scope
ORDER BY o.slug
"""

ALLOWED_MEMBER_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{slug: {slug}}})-[:BELONGS_TO]->(o:Organization)
WHERE o.id IN {org_ids}
MATCH (m)-[:ALLOWED_FOR]->(t:Team)<-[:MEMBER_OF]-(:User {{email: {email}}})
RETURN t.id AS id
"""

MODEL_ID_SCOPES_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{model_id: {model_id}}})-[:BELONGS_TO]->(o:Organization)
WHERE o.id IN {org_ids}
RETURN m.slug AS slug, m.access_scope AS access_scope, m.enabled AS enabled,
       o.id AS org_id
"""

ALLOWED_TEAM_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{slug: {slug}}})-[:BELONGS_TO]->(o:Organization)
WHERE o.id IN {org_ids}
MATCH (m)-[:ALLOWED_FOR]->(t:Team {{id: {team}}})
RETURN t.id AS id
"""

MEMBER_ORGS_QUERY: typing.LiteralString = """
MATCH (:User {{email: {email}}})-[:MEMBER_OF]->(o:Organization)
RETURN o.id AS id
"""

#: The organization ids of one catalog lookup.
OrgIds = collections.abc.Sequence[str]


def first_enabled(
    records: list[dict[str, typing.Any]],
) -> dict[str, typing.Any]:
    """The first enabled row, else the first row.

    The same slug can be in more than one organization. The query
    orders the rows by organization slug, so the choice is stable.
    """
    return next(
        (r for r in records if graph.parse_agtype(r['enabled']) is not False),
        records[0],
    )


class PromptError(Exception):
    """A reference cannot be resolved."""


class InvalidRef(PromptError):
    """The reference is not ``namespace/slug[@label|@n]``."""


class PromptNotFound(PromptError):
    """The prompt, version, or a usable label does not exist."""


class ModelNotAllowed(fastapi.HTTPException):
    """A ``restricted`` model does not allow the caller or the team
    (403 ``model_not_allowed``)."""

    def __init__(self, message: str) -> None:
        super().__init__(
            status_code=403,
            detail={
                'error': 'model_not_allowed',
                'retry': False,
                'message': message,
            },
        )


def vertex_props(raw: typing.Any) -> dict[str, typing.Any] | None:
    """Return an agtype vertex's properties, or ``None`` for a null."""
    parsed: typing.Any = graph.parse_agtype(raw)
    if not isinstance(parsed, dict):
        return None
    return typing.cast('dict[str, typing.Any]', parsed)


def parse_prompt(props: dict[str, typing.Any]) -> models.Prompt:
    return models.Prompt.model_validate(props)


def parse_version(
    props: dict[str, typing.Any], prompt: models.Prompt
) -> models.PromptVersion:
    return models.PromptVersion.model_validate({**props, 'prompt': prompt})


def parse_ref(ref: str) -> tuple[str, str, str | None]:
    """Split ``namespace/slug@label`` into its parts.

    Raises:
        InvalidRef: The reference is not valid.

    """
    match = REF_PATTERN.match(ref)
    if match is None:
        raise InvalidRef(
            f'Invalid prompt reference {ref!r}; expected '
            'namespace/slug, namespace/slug@label, or namespace/slug@n'
        )
    return match['namespace'], match['slug'], match['label']


async def fetch_prompt(
    db: graph.Graph, namespace: str, slug: str
) -> tuple[models.Prompt, int]:
    """Read a prompt and its newest version number.

    Raises:
        PromptNotFound: No such prompt.

    """
    records = await db.execute(
        PROMPT_QUERY,
        {'namespace': namespace, 'slug': slug},
        ['p', 'latest'],
    )
    props = vertex_props(records[0]['p']) if records else None
    if props is None:
        raise PromptNotFound(f'Prompt {namespace}/{slug} not found')
    latest = graph.parse_agtype(records[0]['latest'])
    return parse_prompt(props), int(latest or 0)


async def fetch_version(
    db: graph.Graph, prompt: models.Prompt, n: int
) -> models.PromptVersion:
    """Read version ``n`` of a prompt.

    Raises:
        PromptNotFound: The prompt has no version ``n``.

    """
    records = await db.execute(
        VERSION_QUERY, {'prompt_id': prompt.id, 'n': n}, ['v']
    )
    props = vertex_props(records[0]['v']) if records else None
    if props is None:
        raise PromptNotFound(
            f'Prompt {prompt.namespace}/{prompt.slug} has no version {n}'
        )
    return parse_version(props, prompt)


async def resolve(
    db: graph.Graph, ref: str
) -> tuple[models.Prompt, models.PromptVersion, str | None]:
    """Find the version a reference names.

    Returns:
        The prompt, the version, and the label used (``None`` when the
        reference named a version number).

    Raises:
        InvalidRef: The reference is not valid.
        PromptNotFound: The prompt, version, or a usable label does not
            exist.

    """
    namespace, slug, selector = parse_ref(ref)
    prompt, _latest = await fetch_prompt(db, namespace, slug)
    if selector is not None and selector.isascii() and selector.isdigit():
        return prompt, await fetch_version(db, prompt, int(selector)), None
    by_name = {label.name: label for label in prompt.labels}
    label = by_name.get(selector or '') or by_name.get(prompt.default_label)
    if label is None:
        raise PromptNotFound(
            f'Prompt {namespace}/{slug} has no label {selector!r} '
            f'and no default label {prompt.default_label!r}'
        )
    version = await fetch_version(db, prompt, label.version)
    return prompt, version, label.name


class ModelInfo(typing.NamedTuple):
    model_id: str
    enabled: bool
    driver: str
    #: ``organization`` or ``restricted`` (only the allowed teams).
    access_scope: str | None = None


async def member_org_ids(db: graph.Graph, email: str) -> list[str]:
    """Return the ids of the organizations of the user ``email``."""
    records = await db.execute(MEMBER_ORGS_QUERY, {'email': email}, ['id'])
    return [str(graph.parse_agtype(record['id'])) for record in records]


async def model_info(
    db: graph.Graph, slug: str, *, org_ids: OrgIds
) -> ModelInfo | None:
    """Return the catalog model ``slug`` and its provider's driver."""
    records = await db.execute(
        MODEL_DRIVER_QUERY,
        {'slug': slug, 'org_ids': list(org_ids)},
        ['model_id', 'enabled', 'driver', 'access_scope'],
    )
    if not records:
        return None
    record = first_enabled(records)
    return ModelInfo(
        model_id=str(graph.parse_agtype(record['model_id'])),
        enabled=graph.parse_agtype(record['enabled']) is not False,
        driver=str(graph.parse_agtype(record['driver'])),
        access_scope=graph.parse_agtype(record.get('access_scope')),
    )


async def member_allowed(
    db: graph.Graph, slug: str, email: str, *, org_ids: OrgIds
) -> bool:
    """Whether the user ``email`` is a member of a team that a
    ``restricted`` model allows."""
    params = {'slug': slug, 'email': email, 'org_ids': list(org_ids)}
    return bool(await db.execute(ALLOWED_MEMBER_QUERY, params, ['id']))


async def member_may_use_model_id(
    db: graph.Graph,
    model_id: str,
    email: str,
    default: str | None = None,
    *,
    org_ids: OrgIds,
) -> bool:
    """Whether the user ``email`` may use the provider model id
    ``model_id``.

    Only enabled catalog models count. Allowed when one of them is not
    ``restricted`` or a ``restricted`` one allows the user. An id with
    no enabled catalog model is refused, except ``default`` (the
    configured default model, which need not be in the catalog).
    """
    return await _may_use_model_id(
        db,
        model_id,
        default,
        org_ids,
        lambda slug, org_id: member_allowed(db, slug, email, org_ids=[org_id]),
    )


async def team_may_use_model_id(
    db: graph.Graph, model_id: str, team_id: str, *, org_ids: OrgIds
) -> bool:
    """Whether the team ``team_id`` may use the provider model id
    ``model_id``: the rule of :func:`member_may_use_model_id`, with no
    default."""
    return await _may_use_model_id(
        db,
        model_id,
        None,
        org_ids,
        lambda slug, org_id: team_allowed(db, slug, team_id, org_ids=[org_id]),
    )


async def _may_use_model_id(
    db: graph.Graph,
    model_id: str,
    default: str | None,
    org_ids: OrgIds,
    allowed: collections.abc.Callable[
        [str, str], collections.abc.Awaitable[bool]
    ],
) -> bool:
    # Check each grant in the organization of its model row only. A grant
    # for the same slug in a different organization must not authorize it.
    records = await db.execute(
        MODEL_ID_SCOPES_QUERY,
        {'model_id': model_id, 'org_ids': list(org_ids)},
        ['slug', 'access_scope', 'enabled', 'org_id'],
    )
    rows = [{k: graph.parse_agtype(v) for k, v in r.items()} for r in records]
    rows = [r for r in rows if r.get('enabled') is not False]
    if not rows:
        return model_id == default
    if any(r['access_scope'] != 'restricted' for r in rows):
        return True
    for row in rows:
        if await allowed(str(row['slug']), str(row['org_id'])):
            return True
    return False


async def team_allowed(
    db: graph.Graph, slug: str, team_id: str, *, org_ids: OrgIds
) -> bool:
    """Whether a ``restricted`` model allows the team ``team_id``."""
    params = {'slug': slug, 'team': team_id, 'org_ids': list(org_ids)}
    return bool(await db.execute(ALLOWED_TEAM_QUERY, params, ['id']))


async def check_model_teams(
    db: graph.Graph,
    slug: str,
    message: str,
    *,
    org_ids: OrgIds,
    email: str | None = None,
    team_id: str | None = None,
) -> None:
    """Refuse the ``restricted`` model ``slug`` unless it allows the
    user ``email`` and the team ``team_id``. A ``None`` value is not
    checked. With neither, the caller is refused.

    Raises:
        ModelNotAllowed: With ``message``.

    """
    if email is None and team_id is None:
        raise ModelNotAllowed(message)
    if email is not None and not await member_allowed(
        db, slug, email, org_ids=org_ids
    ):
        raise ModelNotAllowed(message)
    if team_id is not None and not await team_allowed(
        db, slug, team_id, org_ids=org_ids
    ):
        raise ModelNotAllowed(message)
