"""Read prompts and versions from the graph, and resolve references.

A reference is ``namespace/slug``, ``namespace/slug@label``, or
``namespace/slug@n``. ``@n`` names a version. A label the prompt does
not have, or no ``@`` at all, falls back to the prompt's default label.
"""

import re
import typing

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

VERSION_QUERY: typing.LiteralString = """
MATCH (v:PromptVersion {{prompt_id: {prompt_id}, n: {n}}})
      -[:VERSION_OF]->(:Prompt {{id: {prompt_id}}})
RETURN v
"""

MODEL_DRIVER_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{slug: {slug}}})-[:SERVED_BY]->(p:AIProvider)
RETURN m.model_id AS model_id, m.enabled AS enabled, p.driver AS driver,
       m.access_scope AS access_scope
"""

ALLOWED_MEMBER_QUERY: typing.LiteralString = """
MATCH (:AIModel {{slug: {slug}}})-[:ALLOWED_FOR]->(t:Team)
      <-[:MEMBER_OF]-(:User {{email: {email}}})
RETURN t.id AS id
"""

MODEL_ID_SCOPES_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{model_id: {model_id}}})
RETURN m.slug AS slug, m.access_scope AS access_scope
"""

ALLOWED_TEAM_QUERY: typing.LiteralString = """
MATCH (:AIModel {{slug: {slug}}})-[:ALLOWED_FOR]->(t:Team {{id: {team}}})
RETURN t.id AS id
"""


class PromptError(Exception):
    """A reference cannot be resolved."""


class InvalidRef(PromptError):
    """The reference is not ``namespace/slug[@label|@n]``."""


class PromptNotFound(PromptError):
    """The prompt, version, or a usable label does not exist."""


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


async def model_info(db: graph.Graph, slug: str) -> ModelInfo | None:
    """Return the catalog model ``slug`` and its provider's driver."""
    records = await db.execute(
        MODEL_DRIVER_QUERY,
        {'slug': slug},
        ['model_id', 'enabled', 'driver', 'access_scope'],
    )
    if not records:
        return None
    record = records[0]
    return ModelInfo(
        model_id=str(graph.parse_agtype(record['model_id'])),
        enabled=graph.parse_agtype(record['enabled']) is not False,
        driver=str(graph.parse_agtype(record['driver'])),
        access_scope=graph.parse_agtype(record.get('access_scope')),
    )


async def member_allowed(db: graph.Graph, slug: str, email: str) -> bool:
    """Whether the user ``email`` is a member of a team that a
    ``restricted`` model allows."""
    params = {'slug': slug, 'email': email}
    return bool(await db.execute(ALLOWED_MEMBER_QUERY, params, ['id']))


async def member_may_use_model_id(
    db: graph.Graph, model_id: str, email: str
) -> bool:
    """Whether the user ``email`` may use the provider model id
    ``model_id``.

    Refused only when the catalog has the id, every catalog model with
    the id is ``restricted``, and none of them allows the user. An id
    that is not in the catalog is not refused here.
    """
    records = await db.execute(
        MODEL_ID_SCOPES_QUERY, {'model_id': model_id}, ['slug', 'access_scope']
    )
    rows = [{k: graph.parse_agtype(v) for k, v in r.items()} for r in records]
    if not rows or any(r['access_scope'] != 'restricted' for r in rows):
        return True
    for row in rows:
        if await member_allowed(db, str(row['slug']), email):
            return True
    return False


async def team_allowed(db: graph.Graph, slug: str, team_id: str) -> bool:
    """Whether a ``restricted`` model allows the team ``team_id``."""
    params = {'slug': slug, 'team': team_id}
    return bool(await db.execute(ALLOWED_TEAM_QUERY, params, ['id']))
