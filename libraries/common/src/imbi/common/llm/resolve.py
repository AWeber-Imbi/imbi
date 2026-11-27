"""Find the catalog model that a call uses (ADR 0018).

The order is: the explicit model, the team default, the organization
default, then the environment. The first level that names a model wins.
When that model cannot be used, :class:`ModelUnusable` is raised and no
other level is tried. The environment applies only when no level names
a model.

The catalog is per organization: every query reads only the models
that ``BELONGS_TO`` the organizations of the call. The defaults are
``Organization -[:USES_DEFAULT_MODEL]-> AIModel`` and
``Team -[:USES_DEFAULT_MODEL]-> AIModel``, for a team of that
organization.
"""

import dataclasses
import typing

from imbi.common import graph, models
from imbi.common.prompts import resolve as prompt_resolve

#: ``unsupported_driver`` is for a consumer that can call only some
#: drivers; :func:`resolve_model` does not raise it.
Reason = typing.Literal[
    'not_found',
    'disabled',
    'provider_disabled',
    'not_allowed',
    'unsupported_driver',
]
Source = typing.Literal['explicit', 'team', 'org', 'env']

#: The model by id or by slug, in the organizations ``org_ids``. The
#: same slug can be in more than one organization; the rows are in
#: organization slug order (:func:`prompt_resolve.first_enabled`).
EXPLICIT_QUERY: typing.LiteralString = """
MATCH (m:AIModel)-[:BELONGS_TO]->(o:Organization)
WHERE o.id IN {org_ids} AND (m.id = {model} OR m.slug = {model})
OPTIONAL MATCH (m)-[:SERVED_BY]->(p:AIProvider)
RETURN m, p, o, m.enabled AS enabled
ORDER BY o.slug
"""

TEAM_DEFAULT_QUERY: typing.LiteralString = """
MATCH (o:Organization {{id: {org}}})<-[:BELONGS_TO]-(:Team {{id: {team}}})
      -[:USES_DEFAULT_MODEL]->(m:AIModel)-[:BELONGS_TO]->(o)
OPTIONAL MATCH (m)-[:SERVED_BY]->(p:AIProvider)
RETURN m, p, o, m.enabled AS enabled
"""

ORG_DEFAULT_QUERY: typing.LiteralString = """
MATCH (o:Organization {{id: {org}}})-[:USES_DEFAULT_MODEL]->(m:AIModel)
      -[:BELONGS_TO]->(o)
OPTIONAL MATCH (m)-[:SERVED_BY]->(p:AIProvider)
RETURN m, p, o, m.enabled AS enabled
"""


class ModelUnusable(Exception):
    """The model that a level names cannot be used."""

    def __init__(self, reason: Reason, model: str, message: str) -> None:
        super().__init__(message)
        self.reason: Reason = reason
        self.model = model
        self.message = message


@dataclasses.dataclass(frozen=True)
class ResolvedModel:
    """The model a call uses, and the level that named it."""

    source: Source
    #: ``None`` for ``env``: the caller uses its configured model.
    model: models.AIModel | None = None

    @property
    def provider(self) -> models.AIProvider | None:
        return None if self.model is None else self.model.provider


async def resolve_model(
    db: graph.Graph,
    org_ids: prompt_resolve.OrgIds,
    *,
    model: str | None = None,
    team_id: str | None = None,
    email: str | None = None,
    admin: bool = False,
) -> ResolvedModel:
    """Return the model for a call in the organizations ``org_ids``.

    Parameters:
        org_ids: The organization of the call. A consumer with no
            organization (a global system prompt) passes each
            organization of the user; then only the explicit model is
            read.
        model: The explicit model, by id or slug.
        team_id: The team of the call. Its default is the second level,
            and a ``restricted`` model must allow it.
        email: The user of the call. A ``restricted`` model must allow
            one of the user's teams.
        admin: An admin may use a ``restricted`` model.

    Raises:
        ModelUnusable: The model that the first level names is missing,
            disabled, served by a disabled provider, or not allowed.

    """
    levels: list[tuple[Source, str, dict[str, typing.Any]]] = []
    if model is not None:
        params = {'model': model, 'org_ids': list(org_ids)}
        levels.append(('explicit', EXPLICIT_QUERY, params))
    elif len(org_ids) == 1:
        if team_id is not None:
            params = {'org': org_ids[0], 'team': team_id}
            levels.append(('team', TEAM_DEFAULT_QUERY, params))
        levels.append(('org', ORG_DEFAULT_QUERY, {'org': org_ids[0]}))
    for source, query, params in levels:
        records = await db.execute(query, params, ['m', 'p', 'o', 'enabled'])
        if not records:
            if source == 'explicit':
                raise ModelUnusable(
                    'not_found',
                    str(model),
                    f'AI model {model!r} is not in the catalog',
                )
            continue
        record = prompt_resolve.first_enabled(records)
        found = _parse(record, str(model))
        await _check(db, found, team_id, email, admin=admin)
        return ResolvedModel(source=source, model=found)
    return ResolvedModel(source='env')


def _parse(record: dict[str, typing.Any], name: str) -> models.AIModel:
    props = prompt_resolve.vertex_props(record['m']) or {}
    provider = prompt_resolve.vertex_props(record['p'])
    if provider is None:
        name = str(props.get('slug', name))
        raise ModelUnusable(
            'not_found', name, f'AI model {name!r} has no provider'
        )
    org = prompt_resolve.vertex_props(record['o']) or {}
    return models.AIModel.model_validate(
        {
            **props,
            'organization': org,
            'provider': {**provider, 'organization': org},
        }
    )


async def _check(
    db: graph.Graph,
    model: models.AIModel,
    team_id: str | None,
    email: str | None,
    *,
    admin: bool,
) -> None:
    slug = model.slug
    if not model.enabled:
        raise ModelUnusable('disabled', slug, f'AI model {slug!r} is disabled')
    if not model.provider.enabled:
        raise ModelUnusable(
            'provider_disabled',
            slug,
            f'AI provider {model.provider.slug!r} of AI model {slug!r} '
            'is disabled',
        )
    if admin or model.access_scope != 'restricted':
        return
    allowed = (
        (email is not None or team_id is not None)
        and (
            email is None
            or await prompt_resolve.member_allowed(
                db, slug, email, org_ids=[model.organization.id]
            )
        )
        and (
            team_id is None
            or await prompt_resolve.team_allowed(
                db, slug, team_id, org_ids=[model.organization.id]
            )
        )
    )
    if not allowed:
        raise ModelUnusable(
            'not_allowed',
            slug,
            f'The model {slug!r} is restricted to teams that do not '
            'include the caller',
        )
