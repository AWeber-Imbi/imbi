"""Find the catalog model that a call uses (ADR 0018).

The order is: the explicit model, the team default, the organization
default, then the environment. The first level that names a model wins.
When that model cannot be used, :class:`ModelUnusable` is raised and no
other level is tried. The environment applies only when no level names
a model.

A model with a ``monthly_spend_cap`` cannot be used when its spend of
the calendar month (UTC) is at or over the cap (:func:`month_spend`).

The catalog is per organization: every query reads only the models
that ``BELONGS_TO`` the organizations of the call. The defaults are
``Organization -[:USES_DEFAULT_MODEL]-> AIModel`` and
``Team -[:USES_DEFAULT_MODEL]-> AIModel``, for a team of that
organization.
"""

import collections.abc
import dataclasses
import decimal
import typing

import fastapi
import psycopg

from imbi.common import graph, models
from imbi.common.prompts import resolve as prompt_resolve

#: ``provider_credentials_unavailable`` is for a consumer that has no
#: credential for the provider; :func:`resolve_model` does not raise it.
Reason = typing.Literal[
    'not_found',
    'disabled',
    'provider_disabled',
    'not_allowed',
    'spend_cap',
    'unsupported_driver',
    'provider_credentials_unavailable',
]
Source = typing.Literal['explicit', 'team', 'org', 'env']

#: The model by id or by slug, in the organizations ``org_ids``. The
#: same slug can be in more than one organization; the rows are in
#: organization slug order, and the first enabled one is used.
EXPLICIT_QUERY: typing.LiteralString = """
MATCH (m:AIModel)-[:BELONGS_TO]->(o:Organization)
WHERE o.id IN {org_ids} AND (m.id = {model} OR m.slug = {model})
OPTIONAL MATCH (m)-[:SERVED_BY]->(p:AIProvider)
RETURN m, p, o, m.enabled AS enabled
ORDER BY o.slug
"""

#: The model by its vendor ``model_id``, in the organizations
#: ``org_ids``, in the order of :data:`EXPLICIT_QUERY`.
MODEL_ID_QUERY: typing.LiteralString = """
MATCH (m:AIModel)-[:BELONGS_TO]->(o:Organization)
WHERE o.id IN {org_ids} AND m.model_id = {model_id}
OPTIONAL MATCH (m)-[:SERVED_BY]->(p:AIProvider)
RETURN m, p, o, m.enabled AS enabled
ORDER BY o.slug
"""

#: The default model of the team ``{team}`` (``tm``, ``tp``) and of the
#: organization (``om``, ``op``). The team must be in the organization.
DEFAULTS_QUERY: typing.LiteralString = """
MATCH (o:Organization {{id: {org}}})
OPTIONAL MATCH (o)<-[:BELONGS_TO]-(:Team {{id: {team}}})
      -[:USES_DEFAULT_MODEL]->(tm:AIModel)-[:BELONGS_TO]->(o)
OPTIONAL MATCH (tm)-[:SERVED_BY]->(tp:AIProvider)
OPTIONAL MATCH (o)-[:USES_DEFAULT_MODEL]->(om:AIModel)-[:BELONGS_TO]->(o)
OPTIONAL MATCH (om)-[:SERVED_BY]->(op:AIProvider)
RETURN o, tm, tp, om, op
"""

#: The cost of each AI model in the calendar month (UTC), from the
#: prompt runs (``ai_runtime``) and the agent usage reports
#: (``tickets``). Both schemas are in the graph database; imbi-api
#: creates them. A row with an unknown cost adds nothing.
MONTH_SPEND_QUERY: typing.LiteralString = """
WITH month AS (
    SELECT date_trunc('month', NOW() AT TIME ZONE 'UTC')
           AT TIME ZONE 'UTC' AS start
)
SELECT ai_model_id, SUM(cost) FROM (
    SELECT ai_model_id, cost_usd AS cost FROM ai_runtime.ai_model_calls
     WHERE ai_model_id = ANY(%(ids)s)
       AND started_at >= (SELECT start FROM month)
    UNION ALL
    SELECT ai_model_id, cost FROM tickets.budget_ledger
     WHERE ai_model_id = ANY(%(ids)s)
       AND recorded_at >= (SELECT start FROM month)
    UNION ALL
    SELECT ai_model_id, cost FROM tickets.deleted_model_spend
     WHERE ai_model_id = ANY(%(ids)s)
       AND recorded_at >= (SELECT start FROM month)
) AS spend
GROUP BY ai_model_id
"""


class ModelUnusable(Exception):
    """The model that a level names cannot be used."""

    def __init__(self, reason: Reason, model: str, message: str) -> None:
        super().__init__(message)
        self.reason: Reason = reason
        self.model = model
        self.message = message


def http_error(error: ModelUnusable) -> fastapi.HTTPException:
    """The HTTP error of an endpoint for ``error``: ``403``
    (``model_not_allowed``) for ``not_allowed``, else ``422``."""
    if error.reason == 'not_allowed':
        return prompt_resolve.ModelNotAllowed(error.message)
    return fastapi.HTTPException(status_code=422, detail=error.message)


@dataclasses.dataclass(frozen=True)
class ResolvedModel:
    """The model a call uses, and the level that named it."""

    source: Source
    #: ``None`` for ``env``: the caller uses its configured model.
    model: models.AIModel | None = None


async def resolve_model(
    db: graph.Graph,
    org_ids: prompt_resolve.OrgIds,
    *,
    model: str | None = None,
    model_id: str | None = None,
    team_id: str | None = None,
    email: str | None = None,
    admin: bool = False,
    drivers: collections.abc.Collection[str] | None = None,
) -> ResolvedModel:
    """Return the model for a call in the organizations ``org_ids``.

    Parameters:
        org_ids: The organization of the call. A consumer with no
            organization (a global system prompt) passes each
            organization of the user; then only the explicit model is
            read.
        model: The explicit model, by id or slug.
        model_id: The explicit model, by its vendor model id (a caller
            that names a model as the provider does).
        team_id: The team of the call. Its default is the second level,
            and a ``restricted`` model must allow it.
        email: The user of the call. A ``restricted`` model must allow
            one of the user's teams.
        admin: An admin may use a ``restricted`` model.
        drivers: The drivers that the consumer can call; ``None`` for
            every driver.

    Raises:
        ModelUnusable: The model that the first level names is missing,
            disabled, served by a disabled provider or by a driver not
            in ``drivers``, not allowed, or at its spend cap.

    """
    source: Source = 'explicit'
    if model is not None or model_id is not None:
        name = str(model or model_id)
        query, key = (
            (EXPLICIT_QUERY, 'model')
            if model is not None
            else (MODEL_ID_QUERY, 'model_id')
        )
        records = await db.execute(
            query,
            {key: name, 'org_ids': list(org_ids)},
            ['m', 'p', 'o', 'enabled'],
        )
        if not records:
            raise ModelUnusable(
                'not_found', name, f'AI model {name!r} is not in the catalog'
            )
        record = prompt_resolve.first_enabled(records)
    elif len(org_ids) == 1:
        records = await db.execute(
            DEFAULTS_QUERY,
            {'org': org_ids[0], 'team': team_id},
            ['o', 'tm', 'tp', 'om', 'op'],
        )
        row = records[0] if records else {}
        if prompt_resolve.vertex_props(row.get('tm')) is not None:
            source, record = 'team', {'m': row['tm'], 'p': row['tp']}
        elif prompt_resolve.vertex_props(row.get('om')) is not None:
            source, record = 'org', {'m': row['om'], 'p': row['op']}
        else:
            return ResolvedModel(source='env')
        record['o'] = row['o']
        name = ''
    else:
        return ResolvedModel(source='env')
    found = _parse(record, name)
    await _check(db, found, team_id, email, admin=admin, drivers=drivers)
    return ResolvedModel(source=source, model=found)


async def over_cap(
    conn: psycopg.AsyncConnection[typing.Any],
    ai_model_id: str | None,
    cap: decimal.Decimal | None,
) -> decimal.Decimal | None:
    """Return the month-to-date spend of the AIModel ``ai_model_id`` when
    it is at or over ``cap``; ``None`` when it is under, or there is no
    model or no cap."""
    if ai_model_id is None or cap is None:
        return None
    spend = (await month_spend(conn, [ai_model_id])).get(
        ai_model_id, decimal.Decimal(0)
    )
    return spend if spend >= cap else None


async def month_spend(
    conn: psycopg.AsyncConnection[typing.Any], ids: list[str]
) -> dict[str, decimal.Decimal]:
    """Return the USD spend of each AI model id of ``ids`` in the
    calendar month (UTC); a model with no spend is not in the result."""
    cursor = await conn.execute(MONTH_SPEND_QUERY, {'ids': ids})
    return {
        model_id: spend
        for model_id, spend in await cursor.fetchall()
        if spend is not None
    }


def _parse(record: dict[str, typing.Any], name: str) -> models.AIModel:
    props = prompt_resolve.vertex_props(record['m']) or {}
    provider = prompt_resolve.vertex_props(record['p'])
    if provider is None:
        name = str(props.get('slug', name))
        # Not ``not_found``: a caller can treat that as "not in the
        # catalog" and use another model.
        raise ModelUnusable(
            'provider_disabled', name, f'AI model {name!r} has no provider'
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
    drivers: collections.abc.Collection[str] | None,
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
    if drivers is not None and model.provider.driver not in drivers:
        raise ModelUnusable(
            'unsupported_driver',
            slug,
            f'AI model {slug!r} is served by driver '
            f'{model.provider.driver!r}; only {", ".join(sorted(drivers))} '
            'can be used here',
        )
    if not admin and model.access_scope == 'restricted':
        try:
            await prompt_resolve.check_model_teams(
                db,
                slug,
                f'The model {slug!r} is restricted to teams that do not '
                'include the caller',
                org_ids=[model.organization.id],
                email=email,
                team_id=team_id,
            )
        except prompt_resolve.ModelNotAllowed as e:
            detail = typing.cast('dict[str, str]', e.detail)
            raise ModelUnusable(
                'not_allowed', slug, detail['message']
            ) from None
    cap = model.monthly_spend_cap
    if cap is None:
        return
    # ponytail: the calls in flight are not counted, so concurrent
    # calls can go over the cap by their cost. Reserve the cost before
    # the call if that overshoot is too large.
    async with db.pool.connection() as conn:
        spend = await over_cap(conn, model.id, cap)
    if spend is not None:
        raise ModelUnusable(
            'spend_cap',
            slug,
            f'AI model {slug!r} reached its monthly spend cap of '
            f'{cap} USD (spend this month: {spend} USD)',
        )
