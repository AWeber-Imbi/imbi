"""``MAPS_TO`` traversal helper for the AWS plugin.

At call time, ``materialize`` (or any sibling plugin's handler) needs to
pick a single :class:`imbi_plugin_aws.models.AwsAccount` from the
actor's context.  Operators model the mapping declaratively as
``(:Environment | :Project | :ProjectType | :Organization)-[:MAPS_TO]->
(:AwsAccount)`` edges; this module walks them in selector order and
returns the first match.
"""

from __future__ import annotations

import logging
import typing

from imbi_common.plugins.base import PluginContext

from imbi_plugin_aws.errors import AccountNotResolvedError
from imbi_plugin_aws.models import AwsAccount

LOGGER = logging.getLogger(__name__)

DEFAULT_SELECTOR: list[str] = [
    'project',
    'environment',
    'project_type',
    'organization',
]

_LABEL_FOR_ANCHOR: dict[str, str] = {
    'project': 'Project',
    'environment': 'Environment',
    'project_type': 'ProjectType',
    'organization': 'Organization',
}


async def resolve_account(
    db: typing.Any,
    ctx: PluginContext,
    options: dict[str, typing.Any],
) -> AwsAccount:
    """Return the first ``AwsAccount`` reachable via ``MAPS_TO`` from
    the actor's context anchors, in selector order.

    Tag filters narrow the candidate set per anchor: each candidate's
    ``tags`` dict must be a superset of every entry in
    ``options['tag_filters']``.

    Raises:
        AccountNotResolvedError: No anchor produced a matching account.
    """
    selector = list(options.get('account_selector', DEFAULT_SELECTOR))
    tag_filters: dict[str, str] = options.get('tag_filters', {}) or {}

    anchors_checked: list[str] = []
    for anchor in selector:
        label = _LABEL_FOR_ANCHOR.get(anchor)
        if label is None:
            continue
        anchor_id = _anchor_id_from_ctx(anchor, ctx)
        if not anchor_id:
            continue
        anchors_checked.append(anchor)
        candidates = await _candidates_for_anchor(db, label, anchor_id)
        for candidate in candidates:
            if _matches_tag_filters(candidate.tags, tag_filters):
                return candidate

    raise AccountNotResolvedError(
        selector=selector,
        anchors_checked=anchors_checked,
    )


def _anchor_id_from_ctx(anchor: str, ctx: PluginContext) -> str | None:
    """Look up the id of ``anchor`` from the request's
    :class:`PluginContext`.

    The host populates ``project_id`` / ``project_slug`` / ``org_slug``
    today; ``environment`` is a slug, not an id, and ``project_type`` is
    not yet on the context — those anchors are no-ops in Phase 1 and
    will be reachable once the host extends ``PluginContext``.
    """
    if anchor == 'project':
        return ctx.project_id or None
    # Environment / project_type / organization arrive as slugs from
    # the host, not ids; the calling plugin must perform the slug→id
    # lookup before passing them in.  Phase 1 only resolves via
    # project_id; the other anchors return None.
    return None


async def _candidates_for_anchor(
    db: typing.Any,
    label: str,
    anchor_id: str,
) -> list[AwsAccount]:
    """Walk ``MAPS_TO`` from a labeled node id to its ``AwsAccount``
    targets.

    Uses the same Cypher template the host uses elsewhere — ``{}``
    placeholders are SQL-format-style, ``{{`` / ``}}`` escape Cypher
    map literals.
    """
    query = (
        'MATCH (n:' + label + ' {{id: {anchor_id}}})'
        '-[:MAPS_TO]->(a:AwsAccount)'
        ' RETURN a{{.*}} AS account'
    )
    rows = await db.execute(query, {'anchor_id': anchor_id}, ['account'])
    accounts: list[AwsAccount] = []
    for row in rows:
        raw = row.get('account')
        if raw is None:
            continue
        # ``parse_agtype`` is the host's helper.  Imported lazily to
        # avoid coupling this module to imbi_common's import order
        # in tests that stub the db.
        try:
            from imbi_common.graph import parse_agtype
        except ImportError:
            data = raw
        else:
            data = parse_agtype(raw)
        try:
            accounts.append(AwsAccount.model_validate(data))
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                'AwsAccount row %r failed validation', data, exc_info=True
            )
    return accounts


def _matches_tag_filters(
    tags: dict[str, str], tag_filters: dict[str, str]
) -> bool:
    return all(tags.get(k) == v for k, v in tag_filters.items())
