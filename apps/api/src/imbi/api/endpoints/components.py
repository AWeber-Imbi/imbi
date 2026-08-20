"""Component (SBoM package) governance and package reports.

Three routers, all mounted under ``/organizations/{org_slug}``:

- ``components_router`` — package search and the Package Usage payload,
  plus the component-level (all versions) governance mark.
- ``component_releases_router`` — per-version governance: the mark,
  advisories, and notes.
- ``component_reports_router`` — the Problem Packages report.

Components are *shared* identities: the same ``pkg:npm/express`` node is
reachable from every organization whose projects depend on it, and a
governance mark on it is global by design. The ``org_slug`` in the path
is therefore an access check, not a namespace — it scopes *which*
components a caller may see and mark to those the org actually depends
on, using the same traversal the org-scoped search uses
(:mod:`imbi.api.endpoints.search`).

Paths address a component by its nanoid, never by purl: purls carry
``:``, ``/`` and ``@`` and cannot survive as a path segment. Search is
the purl-to-id resolution step.

Every report here is "currently deployed only" — it reads the
``DEPLOYED_IN.current_release`` pointer rather than deriving the current
release from deployment history. A release deployed without an SBoM PUT
carries no component edges and is therefore invisible to these reports.
"""

import asyncio
import datetime
import itertools
import logging
import re
import typing

import fastapi
import nanoid
import pydantic

from imbi.api import component_facts
from imbi.api.auth import permissions
from imbi.common import clickhouse, graph, models

LOGGER = logging.getLogger(__name__)

components_router = fastapi.APIRouter(tags=['Components'])
component_releases_router = fastapi.APIRouter(tags=['Components'])
component_reports_router = fastapi.APIRouter(tags=['Reports'])

#: Default and ceiling for the number of components a search returns.
DEFAULT_SEARCH_LIMIT: typing.Final = 25
MAX_SEARCH_LIMIT: typing.Final = 200

#: Ceiling on Problem Packages rows. Both report endpoints return the
#: full (bounded) result set and every filter is applied client-side,
#: matching every other report in the product.
MAX_PROBLEM_ROWS: typing.Final = 500

#: Sort key for records with no timestamp — they sort oldest, so a
#: note written before ``created_at`` was recorded never displaces a
#: dated one at the head of the list.
_UNDATED: typing.Final = datetime.datetime.min.replace(tzinfo=datetime.UTC)


# ----- Response models ----------------------------------------------


class AdvisoryResponse(pydantic.BaseModel):
    """One advisory recorded against a component version."""

    cve_id: str
    url: str
    title: str | None = None
    created_by: str | None = None
    created_at: datetime.datetime | None = None


class ComponentNoteResponse(pydantic.BaseModel):
    """One note on a component version. Append-only, never edited."""

    id: str
    author: str
    body: str
    created_at: datetime.datetime | None = None


class EnvironmentChip(pydantic.BaseModel):
    """An environment a package version is currently deployed into.

    ``count`` is the number of distinct projects in the row's scope
    running the version in that environment.
    """

    name: str
    slug: str
    label_color: str | None = None
    count: int = 0


class ComponentSearchResult(pydantic.BaseModel):
    """One package in the search dropdown."""

    id: str
    purl_name: str
    name: str
    ecosystem: str
    status: models.ComponentStatus | None = None
    version_count: int = 0
    project_count: int = 0


class ComponentSearchResponse(pydantic.BaseModel):
    """Search hits plus the catalog totals the filter line shows.

    ``ecosystem_totals`` counts every package the org depends on per
    ecosystem, unfiltered by ``q`` — it describes the catalog being
    searched, not the result set.
    """

    data: list[ComponentSearchResult] = []
    ecosystem_totals: dict[str, int] = {}
    total: int = 0


class UsageProject(pydantic.BaseModel):
    """A project currently running a given package version."""

    id: str
    name: str
    slug: str
    team: str | None = None
    team_slug: str | None = None
    project_types: list[str] = []
    environments: list[str] = []


class UsageVersion(pydantic.BaseModel):
    """One version group in the Package Usage table.

    ``status`` is the mark on this version alone; ``effective_status``
    folds in the component-level mark, and ``status_inherited`` is true
    when the component's mark is what makes it non-current.
    """

    id: str
    version: str
    status: models.ComponentStatus | None = None
    status_at: datetime.datetime | None = None
    status_by: str | None = None
    effective_status: models.ComponentStatus | None = None
    status_inherited: bool = False
    first_seen: datetime.datetime | None = None
    advisories: list[AdvisoryResponse] = []
    note_count: int = 0
    project_count: int = 0
    projects: list[UsageProject] = []
    environments: list[EnvironmentChip] = []


class ComponentUsageResponse(pydantic.BaseModel):
    """The Package Usage screen payload for one package."""

    id: str
    purl_name: str
    name: str
    ecosystem: str
    description: str | None = None
    status: models.ComponentStatus | None = None
    status_at: datetime.datetime | None = None
    status_by: str | None = None
    project_count: int = 0
    version_count: int = 0
    deployed_version_count: int = 0
    vulnerable_project_count: int = 0
    newest_deployed_version: str | None = None
    versions: list[UsageVersion] = []


class ComponentStatusRequest(pydantic.BaseModel):
    """Body for the two ``PUT .../status`` endpoints."""

    status: models.ComponentStatus


class ComponentStatusResponse(pydantic.BaseModel):
    """The governance triple after a set or clear."""

    id: str
    status: models.ComponentStatus | None = None
    status_at: datetime.datetime | None = None
    status_by: str | None = None


class ComponentNoteRequest(pydantic.BaseModel):
    """Body for ``POST .../notes``.

    The body is stripped before the length check, so a whitespace-only
    note is a 422 rather than a blank line in the audit trail. The cap
    matches the ``maxLength`` the notes dialog puts on its textarea.
    """

    body: typing.Annotated[
        str,
        pydantic.StringConstraints(
            strip_whitespace=True, min_length=1, max_length=2000
        ),
    ]


class AdvisoryRequest(pydantic.BaseModel):
    """Body for ``PUT .../advisories/{cve_id}``.

    Severity is deliberately absent — see :class:`imbi.common.models.
    Advisory`.
    """

    url: str = pydantic.Field(min_length=1)
    title: str | None = None

    @pydantic.field_validator('url')
    @classmethod
    def _require_http_url(cls, value: str) -> str:
        """Reject anything the advisory chip must not link to.

        Both reports render this value as an anchor href, so a
        ``javascript:`` or ``data:`` URL would run on click.
        """
        stripped = value.strip()
        if not stripped.lower().startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        return stripped


class ProblemPackageRow(pydantic.BaseModel):
    """One ``project + package + version`` finding.

    Environments collapse into ``environments`` rather than multiplying
    the row, matching the report design's row identity.
    """

    project_id: str
    project_name: str
    project_slug: str
    team: str | None = None
    team_slug: str | None = None
    project_types: list[str] = []
    component_id: str
    purl_name: str
    component_name: str
    ecosystem: str
    component_release_id: str
    version: str
    status: models.ComponentStatus | None = None
    status_inherited: bool = False
    advisories: list[AdvisoryResponse] = []
    note_count: int = 0
    environments: list[EnvironmentChip] = []


class ProblemPackagesResponse(pydantic.BaseModel):
    """Every currently-deployed finding across the organization.

    ``truncated`` is true when the row cap was hit, so the UI can say
    the report is partial rather than silently under-reporting.
    """

    rows: list[ProblemPackageRow] = []
    truncated: bool = False


# ----- Cypher --------------------------------------------------------

# Component identity for one version, so an authorization check can
# seek on the ``release_components`` sort key. ``component_id`` leads
# that key and ``component_release_id`` is its fourth column, so
# resolving the parent through one ``HAS_RELEASE`` hop here turns a
# ClickHouse scan into a prefix seek.
_RELEASE_PARENT: typing.LiteralString = """
MATCH (c:Component)-[:HAS_RELEASE]->
      (:ComponentRelease {{id: {component_release_id}}})
RETURN c.id AS component_id
LIMIT 1
"""

# Package search, phase one: which components match the typed text.
#
# The org-membership test used to live here as a second clause, and it
# was an unbounded ``USES_COMPONENT_RELEASE`` fan-in. Membership is now
# a ClickHouse set intersection over the org project set, so this
# clause does only what its name says: match a name against the
# catalog, which is an indexed label scan.
#
# ``ecosystem`` has no null-safe equality in AGE, so the "match
# everything" sentinel is the empty string rather than null.
_SEARCH_COMPONENTS: typing.LiteralString = """
MATCH (c:Component)
WHERE (toLower(c.purl_name) CONTAINS {q} OR toLower(c.name) CONTAINS {q})
  AND ({ecosystem} = '' OR c.ecosystem = {ecosystem})
RETURN c.id AS id,
       c.purl_name AS purl_name,
       c.name AS name,
       c.ecosystem AS ecosystem,
       c.status AS status
"""

_GET_COMPONENT: typing.LiteralString = """
MATCH (c:Component {{id: {component_id}}})
OPTIONAL MATCH (c)-[:HAS_RELEASE]->(cr:ComponentRelease)
RETURN c.id AS id,
       c.purl_name AS purl_name,
       c.name AS name,
       c.ecosystem AS ecosystem,
       c.description AS description,
       c.status AS status,
       c.status_at AS status_at,
       c.status_by AS status_by,
       count(cr) AS version_count
"""

# Every version of the component, deployed or not -- the header's
# version count and the version rows for versions nothing runs today.
_COMPONENT_VERSIONS: typing.LiteralString = """
MATCH (:Component {{id: {component_id}}})-[:HAS_RELEASE]->
      (cr:ComponentRelease)
RETURN cr.id AS component_release_id,
       cr.version AS version,
       cr.status AS version_status,
       cr.status_at AS version_status_at,
       cr.status_by AS version_status_by,
       cr.created_at AS first_seen
"""

# Problem Packages, graph half: every governed component version, with
# the display attributes the report renders. Anchored on a non-null
# status or an advisory edge so it starts from the (indexed, small)
# governed set rather than from every component in the catalog, and
# followed outward only -- the deployment half is a separate, bounded
# read, and ClickHouse intersects the two.
_GOVERNED_VERSIONS: typing.LiteralString = """
MATCH (c:Component)-[:HAS_RELEASE]->(cr:ComponentRelease)
WHERE cr.status IS NOT NULL
   OR c.status IS NOT NULL
   OR EXISTS((cr)-[:HAS_ADVISORY]->(:Advisory))
RETURN c.id AS component_id,
       c.purl_name AS purl_name,
       c.name AS component_name,
       c.ecosystem AS ecosystem,
       c.status AS component_status,
       cr.id AS component_release_id,
       cr.version AS version,
       cr.status AS version_status
"""

_ADVISORIES_FOR_RELEASES: typing.LiteralString = """
MATCH (cr:ComponentRelease)-[:HAS_ADVISORY]->(a:Advisory)
WHERE cr.id IN {ids}
RETURN cr.id AS component_release_id,
       a.cve_id AS cve_id,
       a.url AS url,
       a.title AS title,
       a.created_by AS created_by,
       a.created_at AS created_at
"""

_NOTE_COUNTS_FOR_RELEASES: typing.LiteralString = """
MATCH (cr:ComponentRelease)-[:HAS_NOTE]->(n:ComponentNote)
WHERE cr.id IN {ids}
RETURN cr.id AS component_release_id, count(n) AS note_count
"""

# AGE stores a null assignment as property removal, so the same
# statement both sets and clears the triple -- mirroring
# ``project_deployments._set_release_block``.
_SET_COMPONENT_STATUS: typing.LiteralString = """
MATCH (c:Component {{id: {component_id}}})
SET c.status = {status},
    c.status_at = {status_at},
    c.status_by = {status_by},
    c.updated_at = {now}
RETURN c.id AS id
"""

_SET_RELEASE_STATUS: typing.LiteralString = """
MATCH (cr:ComponentRelease {{id: {component_release_id}}})
SET cr.status = {status},
    cr.status_at = {status_at},
    cr.status_by = {status_by},
    cr.updated_at = {now}
RETURN cr.id AS id
"""

_LIST_NOTES: typing.LiteralString = """
MATCH (:ComponentRelease {{id: {component_release_id}}})-[:HAS_NOTE]->
      (n:ComponentNote)
RETURN n.id AS id,
       n.author AS author,
       n.body AS body,
       n.created_at AS created_at
"""

_CREATE_NOTE: typing.LiteralString = """
MATCH (cr:ComponentRelease {{id: {component_release_id}}})
CREATE (n:ComponentNote {{id: {note_id},
                          author: {author},
                          body: {body},
                          created_at: {now}}})
CREATE (cr)-[:HAS_NOTE]->(n)
RETURN n.id AS id
"""

_LIST_ADVISORIES: typing.LiteralString = """
MATCH (:ComponentRelease {{id: {component_release_id}}})-[:HAS_ADVISORY]->
      (a:Advisory)
RETURN a.cve_id AS cve_id,
       a.url AS url,
       a.title AS title,
       a.created_by AS created_by,
       a.created_at AS created_at
"""

# One Advisory node per CVE, shared across every affected version --
# ``COALESCE`` stands in for the ``ON CREATE SET`` AGE does not have.
_UPSERT_ADVISORY: typing.LiteralString = """
MATCH (cr:ComponentRelease {{id: {component_release_id}}})
MERGE (a:Advisory {{cve_id: {cve_id}}})
SET a.id = COALESCE(a.id, {advisory_id}),
    a.url = {url},
    a.title = {title},
    a.created_by = COALESCE(a.created_by, {created_by}),
    a.created_at = COALESCE(a.created_at, {now}),
    a.updated_at = {now}
MERGE (cr)-[:HAS_ADVISORY]->(a)
RETURN a.cve_id AS cve_id
"""

# Detaching leaves the Advisory node behind when other versions still
# reference it; the DELETE only fires once nothing does.
_DELETE_ADVISORY_EDGE: typing.LiteralString = """
MATCH (:ComponentRelease {{id: {component_release_id}}})-[e:HAS_ADVISORY]->
      (:Advisory {{cve_id: {cve_id}}})
DELETE e
RETURN 1 AS deleted
"""

_GC_ORPHAN_ADVISORY: typing.LiteralString = """
MATCH (a:Advisory {{cve_id: {cve_id}}})
WHERE NOT EXISTS(()-[:HAS_ADVISORY]->(a))
DETACH DELETE a
"""


# ----- Row helpers ---------------------------------------------------


def _text(row: dict[str, typing.Any], key: str) -> str | None:
    """Return a decoded scalar column as a string, or ``None``."""
    value = graph.parse_agtype(row.get(key))
    if value is None:
        return None
    text = str(value)
    return text or None


def _required(row: dict[str, typing.Any], key: str) -> str:
    """Return a decoded scalar column that must be present."""
    return _text(row, key) or ''


def _count(row: dict[str, typing.Any], key: str) -> int:
    """Return a decoded aggregate column as an ``int``."""
    value = graph.parse_agtype(row.get(key))
    try:
        return int(value)  # pyright: ignore[reportArgumentType]
    except (TypeError, ValueError):
        return 0


def _timestamp(
    row: dict[str, typing.Any], key: str
) -> datetime.datetime | None:
    """Return a decoded ISO-8601 column as a datetime, or ``None``.

    The result is always aware. Everything written here carries an
    offset, but a stored value without one would otherwise sort against
    the aware ``_UNDATED`` sentinel and raise ``TypeError``.
    """
    raw = _text(row, key)
    if not raw:
        return None
    try:
        return clickhouse.as_utc(datetime.datetime.fromisoformat(raw))
    except ValueError:
        LOGGER.warning('Unparseable timestamp %r in column %s', raw, key)
        return None


def _string_list(row: dict[str, typing.Any], key: str) -> list[str]:
    """Return a decoded ``collect()`` column as a sorted string list.

    ``OPTIONAL MATCH`` feeds ``collect()`` a null for projects with no
    match, which arrives as a ``None`` entry rather than an empty list.
    """
    value = graph.parse_agtype(row.get(key))
    if not isinstance(value, list):
        return []
    return sorted(
        {str(entry) for entry in typing.cast('list[object]', value) if entry}
    )


def _status(value: str | None) -> models.ComponentStatus | None:
    """Coerce a stored status to the literal, ignoring junk values."""
    if value == 'deprecated':
        return 'deprecated'
    if value == 'forbidden':
        return 'forbidden'
    return None


def _normalize_cve(cve_id: str) -> str:
    """Return the canonical (upper-case, trimmed) advisory identifier."""
    normalized = cve_id.strip().upper()
    if not normalized:
        raise fastapi.HTTPException(
            status_code=400, detail='Advisory identifier must not be empty'
        )
    return normalized


async def _advisories_by_release(
    db: graph.Graph,
    release_ids: list[str],
) -> dict[str, list[AdvisoryResponse]]:
    """Return advisories keyed by component-release id."""
    if not release_ids:
        return {}
    rows = await db.execute(
        _ADVISORIES_FOR_RELEASES,
        {'ids': release_ids},
        [
            'component_release_id',
            'cve_id',
            'url',
            'title',
            'created_by',
            'created_at',
        ],
    )
    out: dict[str, list[AdvisoryResponse]] = {}
    for row in rows:
        out.setdefault(_required(row, 'component_release_id'), []).append(
            AdvisoryResponse(
                cve_id=_required(row, 'cve_id'),
                url=_required(row, 'url'),
                title=_text(row, 'title'),
                created_by=_text(row, 'created_by'),
                created_at=_timestamp(row, 'created_at'),
            )
        )
    for advisories in out.values():
        advisories.sort(key=lambda a: a.cve_id)
    return out


async def _note_counts_by_release(
    db: graph.Graph,
    release_ids: list[str],
) -> dict[str, int]:
    """Return note counts keyed by component-release id."""
    if not release_ids:
        return {}
    rows = await db.execute(
        _NOTE_COUNTS_FOR_RELEASES,
        {'ids': release_ids},
        ['component_release_id', 'note_count'],
    )
    return {
        _required(row, 'component_release_id'): _count(row, 'note_count')
        for row in rows
    }


async def _assert_component_in_org(
    db: graph.Graph,
    org_slug: str,
    component_id: str,
) -> None:
    """404 unless the org depends on ``component_id``."""
    project_ids = await component_facts.org_project_ids(db, org_slug)
    if not await component_facts.component_in_org(project_ids, component_id):
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'No component {component_id!r} in organization',
        )


async def _assert_release_in_org(
    db: graph.Graph,
    org_slug: str,
    component_release_id: str,
) -> None:
    """404 unless the org depends on ``component_release_id``.

    Resolves the owning component first so the ClickHouse probe seeks
    on the sort-key prefix. An unknown version fails here rather than
    on an empty probe, which keeps "no such version" and "version you
    cannot see" the same 404 they have always been.
    """
    project_ids, parent_rows = await asyncio.gather(
        component_facts.org_project_ids(db, org_slug),
        db.execute(
            _RELEASE_PARENT,
            {'component_release_id': component_release_id},
            ['component_id'],
        ),
    )
    in_org = parent_rows and await component_facts.component_release_in_org(
        project_ids,
        _required(parent_rows[0], 'component_id'),
        component_release_id,
    )
    if not in_org:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'No component version {component_release_id!r} in '
                'organization'
            ),
        )


# ----- Search --------------------------------------------------------


@components_router.get('/')
async def search_components(
    org_slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('component:read')),
    ],
    q: str = '',
    ecosystem: str = '',
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> ComponentSearchResponse:
    """Search the packages the organization depends on.

    ``q`` matches the purl or the display name, case-insensitively.
    Ranking is by how the name matched -- exact, then prefix, then
    substring, then alphabetical -- rather than by project count: the
    counts belong to the page this returns, not to the catalog it
    picked the page from, and computing them catalog-wide is what made
    the pre-split query slow.

    An empty ``q`` returns ``ecosystem_totals`` and no rows. The screen
    shows the reader's recently-viewed packages rather than a slice of
    the catalog when the box is empty, so listing every package it
    depends on would be a full-catalog traversal whose result is
    discarded.
    """
    capped = max(1, min(limit, MAX_SEARCH_LIMIT))
    query = q.strip().lower()
    selected_ecosystem = ecosystem.strip()
    project_ids = await component_facts.org_project_ids(db, org_slug)

    results: list[ComponentSearchResult] = []
    total = 0
    if query:
        # Name match against the catalog, then intersect with what the
        # org actually depends on. The intersection has to precede
        # ranking and paging, because ``total`` counts what the reader
        # may see rather than what the catalog holds.
        matches = await db.execute(
            _SEARCH_COMPONENTS,
            {'q': query, 'ecosystem': selected_ecosystem},
            ['id', 'purl_name', 'name', 'ecosystem', 'status'],
        )
        in_org = await component_facts.component_ids_in_org(
            project_ids, [_required(row, 'id') for row in matches]
        )
        matches = [row for row in matches if _required(row, 'id') in in_org]
        total = len(matches)
        ranked = sorted(matches, key=lambda row: _match_rank(row, query))
        page = ranked[:capped]
        counts = await component_facts.search_counts(
            project_ids, [_required(row, 'id') for row in page]
        )
        results = [
            ComponentSearchResult(
                id=_required(row, 'id'),
                purl_name=_required(row, 'purl_name'),
                name=_required(row, 'name'),
                ecosystem=_required(row, 'ecosystem'),
                status=_status(_text(row, 'status')),
                version_count=counts.get(_required(row, 'id'), (0, 0))[0],
                project_count=counts.get(_required(row, 'id'), (0, 0))[1],
            )
            for row in page
        ]

    # The totals describe the org's catalog, not the result set, so
    # they are computed only for the request with an empty box -- the
    # one the screen makes on load. Recomputing on every keystroke
    # would double the cost of a search to restate a constant. The
    # ecosystem filter does not gate them: they are what the filter's
    # own chips count, so dropping them the moment the reader picks a
    # chip would empty the control they just used.
    totals: dict[str, int] = {}
    if not query:
        totals = await component_facts.ecosystem_totals(project_ids)
    return ComponentSearchResponse(
        data=results,
        ecosystem_totals=totals,
        total=total,
    )


def _match_rank(
    row: dict[str, typing.Any], query: str
) -> tuple[int, int, str]:
    """Rank one search hit: exact, then prefix, then substring.

    The third element breaks ties alphabetically, and the second
    prefers the shorter name -- ``react`` outranks
    ``react-dom-server`` for the query ``react``.
    """
    name = _required(row, 'name').lower()
    purl = _required(row, 'purl_name').lower()
    if name == query or purl == query:
        tier = 0
    elif name.startswith(query) or purl.startswith(query):
        tier = 1
    else:
        tier = 2
    return (tier, len(name), _required(row, 'purl_name'))


async def _deployment_pointers(
    db: graph.Graph,
    org_slug: str,
) -> dict[str, list[dict[str, typing.Any]]]:
    """The deployment pointer set, indexed by release id.

    One entry per release a non-archived project of the org currently
    has deployed, holding the project/team/environment rows that
    release is deployed as -- several, when a project runs the same
    release in more than one environment. That fan-out is what the old
    traversal's cross-product carried, and the report folding depends
    on it.

    Rows keep their agtype encoding: every consumer decodes with
    ``_required``/``_text``, and the only value joined in from
    ClickHouse is a nanoid, which decodes to itself.
    """
    rows = await db.execute(
        component_facts.ORG_DEPLOYED_RELEASES,
        {'org_slug': org_slug},
        [
            'release_id',
            'project_id',
            'project_name',
            'project_slug',
            'team_name',
            'team_slug',
            'environment_name',
            'environment_slug',
            'environment_color',
            'project_types',
        ],
    )
    pointers: dict[str, list[dict[str, typing.Any]]] = {}
    for row in rows:
        release_id = _text(row, 'release_id')
        if release_id:
            pointers.setdefault(release_id, []).append(row)
    return pointers


# ----- Package usage -------------------------------------------------


def _usage_versions(
    usage_rows: list[dict[str, typing.Any]],
    version_rows: list[dict[str, typing.Any]],
    component_status: models.ComponentStatus | None,
) -> list[UsageVersion]:
    """Fold the usage cross-product into one group per version.

    ``version_rows`` seeds a group for every known version so a version
    nothing currently deploys still appears (it can be marked, and the
    header's version count must agree with the table).
    """
    versions: dict[str, UsageVersion] = {}
    for row in version_rows:
        version_status = _status(_text(row, 'version_status'))
        effective = models.effective_component_status(
            component_status, version_status
        )
        versions[_required(row, 'component_release_id')] = UsageVersion(
            id=_required(row, 'component_release_id'),
            version=_required(row, 'version'),
            status=version_status,
            status_at=_timestamp(row, 'version_status_at'),
            status_by=_text(row, 'version_status_by'),
            effective_status=effective,
            status_inherited=effective is not None
            and effective != version_status,
            first_seen=_timestamp(row, 'first_seen'),
        )

    projects: dict[str, dict[str, UsageProject]] = {}
    env_counts: dict[str, dict[str, EnvironmentChip]] = {}
    for row in usage_rows:
        release_id = _required(row, 'component_release_id')
        if release_id not in versions:
            continue
        project_id = _required(row, 'project_id')
        environment = _required(row, 'environment_name')
        project = projects.setdefault(release_id, {}).get(project_id)
        if project is None:
            project = UsageProject(
                id=project_id,
                name=_required(row, 'project_name'),
                slug=_required(row, 'project_slug'),
                team=_text(row, 'team_name'),
                team_slug=_text(row, 'team_slug'),
                project_types=_string_list(row, 'project_types'),
            )
            projects[release_id][project_id] = project
        if environment not in project.environments:
            project.environments.append(environment)
        chips = env_counts.setdefault(release_id, {})
        chip = chips.get(environment)
        if chip is None:
            chips[environment] = EnvironmentChip(
                name=environment,
                slug=_required(row, 'environment_slug'),
                label_color=_text(row, 'environment_color'),
                count=1,
            )
        else:
            chip.count += 1

    for release_id, version in versions.items():
        version.projects = sorted(
            projects.get(release_id, {}).values(), key=lambda p: p.name
        )
        version.project_count = len(version.projects)
        version.environments = sorted(
            env_counts.get(release_id, {}).values(), key=lambda c: c.name
        )
        for project in version.projects:
            project.environments.sort()
    return sorted(
        versions.values(),
        key=lambda v: _version_sort_key(v.version),
        reverse=True,
    )


def _version_sort_key(
    version: str,
) -> tuple[tuple[int, ...], int, tuple[tuple[int, int, str], ...]]:
    """Order a version string newest-last, across ecosystems.

    Version strings have no one ordering that spans npm and pypi, so
    this compares what both agree on: leading numeric segments
    numerically (``4.19.2`` below ``4.23.0``, which a string sort gets
    backwards), and everything from the first non-numeric segment on as
    a pre-release ranking below the plain release (``1.0.0-rc1`` below
    ``1.0.0``).

    Build metadata is dropped first. SemVer gives it no bearing on
    precedence, and leaving it in would read as a pre-release suffix
    and sort ``1.0.0+build.5`` below the plain ``1.0.0``.

    Nothing here raises: a hand-written version in the graph sorts
    oddly rather than breaking the report. The digit test is
    ``isdecimal`` rather than ``isdigit`` for that reason -- ``isdigit``
    accepts characters ``int()`` rejects, superscripts among them.
    """
    core = version.strip().lstrip('vV').split('+', 1)[0]
    parts = re.split(r'[._\-]', core)
    release = tuple(
        int(part) for part in itertools.takewhile(str.isdecimal, parts)
    )
    rest = parts[len(release) :]
    return (
        release,
        # A plain release outranks the same release with a
        # pre-release suffix, so it takes the higher tier.
        0 if rest else 1,
        tuple(
            (0, int(part), '') if part.isdecimal() else (1, 0, part)
            for part in rest
        ),
    )


@components_router.get('/{component_id}/usage')
async def get_component_usage(
    org_slug: str,
    component_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('component:read')),
    ],
) -> ComponentUsageResponse:
    """Return the Package Usage payload for one package.

    Deployment facts cover currently-deployed releases only. The header
    counts are over the same scope, except ``version_count``, which is
    every version Imbi has ever ingested for the package.
    """
    # Independent reads, and ``execute`` takes its own pooled
    # connection per call, so the screen waits on the slowest rather
    # than on their sum. The membership check is one of them: it is a
    # guard on the response, not on whether the others may run.
    _scope, header_rows, version_rows, pointer_rows = await asyncio.gather(
        _assert_component_in_org(db, org_slug, component_id),
        db.execute(
            _GET_COMPONENT,
            {'component_id': component_id},
            [
                'id',
                'purl_name',
                'name',
                'ecosystem',
                'description',
                'status',
                'status_at',
                'status_by',
                'version_count',
            ],
        ),
        db.execute(
            _COMPONENT_VERSIONS,
            {'component_id': component_id},
            [
                'component_release_id',
                'version',
                'version_status',
                'version_status_at',
                'version_status_by',
                'first_seen',
            ],
        ),
        _deployment_pointers(db, org_slug),
    )
    if not header_rows:
        raise fastapi.HTTPException(
            status_code=404, detail=f'No component {component_id!r}'
        )
    header = header_rows[0]
    component_status = _status(_text(header, 'status'))
    # ClickHouse says which of the deployed releases carry a version of
    # this package; the pointer rows say what those releases are
    # deployed as. Re-joining here reproduces the cross-product the
    # traversal used to return, so the folding below is unchanged.
    usage = await component_facts.component_usage(
        list(pointer_rows), component_id
    )
    usage_rows = [
        {**pointer, 'component_release_id': component_release_id}
        for release_id, component_release_id, _version in usage
        for pointer in pointer_rows.get(release_id, ())
    ]
    versions = _usage_versions(usage_rows, version_rows, component_status)

    release_ids = [v.id for v in versions]
    advisories, note_counts = await asyncio.gather(
        _advisories_by_release(db, release_ids),
        _note_counts_by_release(db, release_ids),
    )
    for version in versions:
        version.advisories = advisories.get(version.id, [])
        version.note_count = note_counts.get(version.id, 0)

    deployed = [v for v in versions if v.project_count]
    vulnerable = {
        project.id
        for version in versions
        if version.effective_status is not None or version.advisories
        for project in version.projects
    }
    return ComponentUsageResponse(
        id=_required(header, 'id'),
        purl_name=_required(header, 'purl_name'),
        name=_required(header, 'name'),
        ecosystem=_required(header, 'ecosystem'),
        description=_text(header, 'description'),
        status=component_status,
        status_at=_timestamp(header, 'status_at'),
        status_by=_text(header, 'status_by'),
        project_count=len(
            {p.id for version in versions for p in version.projects}
        ),
        version_count=_count(header, 'version_count'),
        deployed_version_count=len(deployed),
        vulnerable_project_count=len(vulnerable),
        # The table is sorted newest-first by the same comparator,
        # so this is its top deployed row -- the number and the row a
        # reader sees agree by construction.
        newest_deployed_version=deployed[0].version if deployed else None,
        versions=versions,
    )


# ----- Governance marks ----------------------------------------------


async def _write_component_status(
    db: graph.Graph,
    component_id: str,
    status: models.ComponentStatus | None,
    actor: str | None,
) -> ComponentStatusResponse:
    """Set or clear the triple on a ``Component``."""
    status_at = (
        datetime.datetime.now(datetime.UTC) if status is not None else None
    )
    rows = await db.execute(
        _SET_COMPONENT_STATUS,
        {
            'component_id': component_id,
            'status': status,
            'status_at': status_at.isoformat() if status_at else None,
            'status_by': actor if status is not None else None,
            'now': datetime.datetime.now(datetime.UTC).isoformat(),
        },
        ['id'],
    )
    if not rows:
        raise fastapi.HTTPException(
            status_code=404, detail=f'No component {component_id!r}'
        )
    return ComponentStatusResponse(
        id=component_id,
        status=status,
        status_at=status_at,
        status_by=actor if status is not None else None,
    )


async def _write_release_status(
    db: graph.Graph,
    component_release_id: str,
    status: models.ComponentStatus | None,
    actor: str | None,
) -> ComponentStatusResponse:
    """Set or clear the triple on a ``ComponentRelease``."""
    status_at = (
        datetime.datetime.now(datetime.UTC) if status is not None else None
    )
    rows = await db.execute(
        _SET_RELEASE_STATUS,
        {
            'component_release_id': component_release_id,
            'status': status,
            'status_at': status_at.isoformat() if status_at else None,
            'status_by': actor if status is not None else None,
            'now': datetime.datetime.now(datetime.UTC).isoformat(),
        },
        ['id'],
    )
    if not rows:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'No component version {component_release_id!r}',
        )
    return ComponentStatusResponse(
        id=component_release_id,
        status=status,
        status_at=status_at,
        status_by=actor if status is not None else None,
    )


@components_router.put('/{component_id}/status')
async def set_component_status(
    org_slug: str,
    component_id: str,
    body: ComponentStatusRequest,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('component:write')),
    ],
) -> ComponentStatusResponse:
    """Mark every version of a package deprecated or forbidden.

    Re-marking overwrites the mark and re-stamps the actor. The mark is
    global — components are shared identities, so every organization
    depending on this package sees it.
    """
    await _assert_component_in_org(db, org_slug, component_id)
    result = await _write_component_status(
        db, component_id, body.status, auth.principal_name
    )
    LOGGER.info(
        'Component marked: component=%s status=%s actor=%s',
        component_id,
        body.status,
        auth.principal_name,
    )
    return result


@components_router.delete('/{component_id}/status')
async def clear_component_status(
    org_slug: str,
    component_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('component:write')),
    ],
) -> ComponentStatusResponse:
    """Return a package to current.

    Clearing an unmarked package is a no-op, not an error. The clear is
    as global as the mark was — every organization depending on this
    package stops seeing it.
    """
    await _assert_component_in_org(db, org_slug, component_id)
    result = await _write_component_status(db, component_id, None, None)
    LOGGER.info(
        'Component mark cleared: component=%s actor=%s',
        component_id,
        auth.principal_name,
    )
    return result


@component_releases_router.put('/{component_release_id}/status')
async def set_component_release_status(
    org_slug: str,
    component_release_id: str,
    body: ComponentStatusRequest,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('component:write')),
    ],
) -> ComponentStatusResponse:
    """Mark one version of a package deprecated or forbidden.

    A version mark never *relaxes* its component's — the effective
    status reports are built from is the stricter of the two.
    """
    await _assert_release_in_org(db, org_slug, component_release_id)
    result = await _write_release_status(
        db, component_release_id, body.status, auth.principal_name
    )
    LOGGER.info(
        'Component version marked: version=%s status=%s actor=%s',
        component_release_id,
        body.status,
        auth.principal_name,
    )
    return result


@component_releases_router.delete('/{component_release_id}/status')
async def clear_component_release_status(
    org_slug: str,
    component_release_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('component:write')),
    ],
) -> ComponentStatusResponse:
    """Return one version to current.

    A version left current still reports as non-current while its
    component carries a mark — clearing here removes only the
    version's own.
    """
    await _assert_release_in_org(db, org_slug, component_release_id)
    result = await _write_release_status(db, component_release_id, None, None)
    LOGGER.info(
        'Component version mark cleared: version=%s actor=%s',
        component_release_id,
        auth.principal_name,
    )
    return result


# ----- Notes ---------------------------------------------------------


@component_releases_router.get('/{component_release_id}/notes')
async def list_component_notes(
    org_slug: str,
    component_release_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('component:read')),
    ],
) -> list[ComponentNoteResponse]:
    """List the notes on a package version, oldest first."""
    await _assert_release_in_org(db, org_slug, component_release_id)
    rows = await db.execute(
        _LIST_NOTES,
        {'component_release_id': component_release_id},
        ['id', 'author', 'body', 'created_at'],
    )
    notes = [
        ComponentNoteResponse(
            id=_required(row, 'id'),
            author=_required(row, 'author'),
            body=_required(row, 'body'),
            created_at=_timestamp(row, 'created_at'),
        )
        for row in rows
    ]
    notes.sort(key=lambda n: (n.created_at or _UNDATED, n.id))
    return notes


@component_releases_router.post(
    '/{component_release_id}/notes', status_code=201
)
async def create_component_note(
    org_slug: str,
    component_release_id: str,
    body: ComponentNoteRequest,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('component:write')),
    ],
) -> ComponentNoteResponse:
    """Append a note to a package version.

    Notes are append-only and visible to every team; the author is the
    calling principal, never a body field.
    """
    await _assert_release_in_org(db, org_slug, component_release_id)
    now = datetime.datetime.now(datetime.UTC)
    note_id = nanoid.generate()
    rows = await db.execute(
        _CREATE_NOTE,
        {
            'component_release_id': component_release_id,
            'note_id': note_id,
            'author': auth.principal_name,
            'body': body.body,
            'now': now.isoformat(),
        },
        ['id'],
    )
    if not rows:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'No component version {component_release_id!r}',
        )
    return ComponentNoteResponse(
        id=note_id,
        author=auth.principal_name,
        body=body.body,
        created_at=now,
    )


# ----- Advisories ----------------------------------------------------


@component_releases_router.get('/{component_release_id}/advisories')
async def list_component_advisories(
    org_slug: str,
    component_release_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('component:read')),
    ],
) -> list[AdvisoryResponse]:
    """List the advisories recorded against a package version."""
    await _assert_release_in_org(db, org_slug, component_release_id)
    rows = await db.execute(
        _LIST_ADVISORIES,
        {'component_release_id': component_release_id},
        ['cve_id', 'url', 'title', 'created_by', 'created_at'],
    )
    advisories = [
        AdvisoryResponse(
            cve_id=_required(row, 'cve_id'),
            url=_required(row, 'url'),
            title=_text(row, 'title'),
            created_by=_text(row, 'created_by'),
            created_at=_timestamp(row, 'created_at'),
        )
        for row in rows
    ]
    advisories.sort(key=lambda a: a.cve_id)
    return advisories


@component_releases_router.put('/{component_release_id}/advisories/{cve_id}')
async def upsert_component_advisory(
    org_slug: str,
    component_release_id: str,
    cve_id: str,
    body: AdvisoryRequest,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('component:write')),
    ],
) -> AdvisoryResponse:
    """Record an advisory against a package version.

    The identifier is upper-cased and MERGEd, so the same CVE affecting
    several versions is one node with several edges. Re-recording it
    updates the URL and title but keeps the original author and
    creation time.
    """
    await _assert_release_in_org(db, org_slug, component_release_id)
    normalized = _normalize_cve(cve_id)
    now = datetime.datetime.now(datetime.UTC)
    rows = await db.execute(
        _UPSERT_ADVISORY,
        {
            'component_release_id': component_release_id,
            'cve_id': normalized,
            'advisory_id': nanoid.generate(),
            'url': body.url,
            'title': body.title,
            'created_by': auth.principal_name,
            'now': now.isoformat(),
        },
        ['cve_id'],
    )
    if not rows:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'No component version {component_release_id!r}',
        )
    LOGGER.info(
        'Advisory recorded: version=%s cve=%s actor=%s',
        component_release_id,
        normalized,
        auth.principal_name,
    )
    return AdvisoryResponse(
        cve_id=normalized,
        url=body.url,
        title=body.title,
        created_by=auth.principal_name,
        created_at=now,
    )


@component_releases_router.delete(
    '/{component_release_id}/advisories/{cve_id}', status_code=204
)
async def delete_component_advisory(
    org_slug: str,
    component_release_id: str,
    cve_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('component:write')),
    ],
) -> fastapi.Response:
    """Detach an advisory from a package version.

    Only the edge is removed; the ``Advisory`` node survives as long as
    another version still references it, and is collected once none
    does. Removing an advisory that was never attached is a no-op.
    """
    await _assert_release_in_org(db, org_slug, component_release_id)
    normalized = _normalize_cve(cve_id)
    deleted = await db.execute(
        _DELETE_ADVISORY_EDGE,
        {
            'component_release_id': component_release_id,
            'cve_id': normalized,
        },
        ['deleted'],
    )
    if deleted:
        await db.execute(_GC_ORPHAN_ADVISORY, {'cve_id': normalized})
    LOGGER.info(
        'Advisory removed: version=%s cve=%s actor=%s',
        component_release_id,
        normalized,
        auth.principal_name,
    )
    return fastapi.Response(status_code=204)


# ----- Problem Packages report ---------------------------------------


def _problem_rows(
    rows: list[dict[str, typing.Any]],
) -> dict[tuple[str, str], ProblemPackageRow]:
    """Fold the report cross-product into project+package+version rows.

    Environments collapse into chips on the row; every other column is
    identical across the collapsed rows by construction.
    """
    findings: dict[tuple[str, str], ProblemPackageRow] = {}
    for row in rows:
        component_status = _status(_text(row, 'component_status'))
        version_status = _status(_text(row, 'version_status'))
        effective = models.effective_component_status(
            component_status, version_status
        )
        key = (
            _required(row, 'project_id'),
            _required(row, 'component_release_id'),
        )
        finding = findings.get(key)
        if finding is None:
            finding = ProblemPackageRow(
                project_id=_required(row, 'project_id'),
                project_name=_required(row, 'project_name'),
                project_slug=_required(row, 'project_slug'),
                team=_text(row, 'team_name'),
                team_slug=_text(row, 'team_slug'),
                project_types=_string_list(row, 'project_types'),
                component_id=_required(row, 'component_id'),
                purl_name=_required(row, 'purl_name'),
                component_name=_required(row, 'component_name'),
                ecosystem=_required(row, 'ecosystem'),
                component_release_id=_required(row, 'component_release_id'),
                version=_required(row, 'version'),
                status=effective,
                status_inherited=effective is not None
                and effective != version_status,
            )
            findings[key] = finding
        environment = _required(row, 'environment_name')
        if not any(chip.name == environment for chip in finding.environments):
            finding.environments.append(
                EnvironmentChip(
                    name=environment,
                    slug=_required(row, 'environment_slug'),
                    label_color=_text(row, 'environment_color'),
                    count=1,
                )
            )
    return findings


@component_reports_router.get('/problem-packages')
async def get_problem_packages(
    org_slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('component:read')),
    ],
) -> ProblemPackagesResponse:
    """Every currently-deployed package version that needs attention.

    A finding is an effective status other than current *or* at least
    one recorded advisory — a package still marked current but carrying
    a CVE is exactly what this report exists to surface. Filtering,
    counting, and CSV export are the client's job; this returns the
    whole (capped) set.
    """
    # The graph supplies the governed set and every attribute the
    # report renders; ClickHouse supplies only the intersection --
    # which of those versions the deployed releases actually carry.
    # Both bounds are small, so the scan the traversal could not avoid
    # never happens.
    governed_rows, pointer_rows = await asyncio.gather(
        db.execute(
            _GOVERNED_VERSIONS,
            {},
            [
                'component_id',
                'purl_name',
                'component_name',
                'ecosystem',
                'component_status',
                'component_release_id',
                'version',
                'version_status',
            ],
        ),
        _deployment_pointers(db, org_slug),
    )
    governed = {
        _required(row, 'component_release_id'): row for row in governed_rows
    }
    usages = await component_facts.governed_usage(
        list(pointer_rows), list(governed)
    )
    rows = [
        {**pointer, **governed[usage['component_release_id']]}
        for usage in usages
        for pointer in pointer_rows.get(usage['release_id'], ())
        if usage['component_release_id'] in governed
    ]
    findings = _problem_rows(rows)
    release_ids = sorted({f.component_release_id for f in findings.values()})
    advisories = await _advisories_by_release(db, release_ids)
    note_counts = await _note_counts_by_release(db, release_ids)
    for finding in findings.values():
        finding.advisories = advisories.get(finding.component_release_id, [])
        finding.note_count = note_counts.get(finding.component_release_id, 0)
        finding.environments.sort(key=lambda c: c.name)

    # The anchor clause admits versions whose only qualification was an
    # advisory edge that has since been deleted; drop those here rather
    # than pushing another EXISTS into the report scan.
    kept = [
        finding
        for finding in findings.values()
        if finding.status is not None or finding.advisories
    ]
    # ``version`` sorts on a real version key, not lexically: a string
    # sort puts ``4.9.0`` above ``4.23.0``, which is backwards for a
    # report whose whole job is telling an operator which version they
    # are running.
    kept.sort(
        key=lambda f: (
            f.project_name,
            f.purl_name,
            _version_sort_key(f.version),
        )
    )
    return ProblemPackagesResponse(
        rows=kept[:MAX_PROBLEM_ROWS],
        truncated=len(kept) > MAX_PROBLEM_ROWS,
    )
