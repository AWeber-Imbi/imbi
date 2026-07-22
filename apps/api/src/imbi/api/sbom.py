# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportOptionalMemberAccess=false
#
# The cyclonedx-python-lib uses py_serializable's
# ``@serializable.serializable_class`` decorator, which causes
# basedpyright to see its model classes as ``_JsonSerializable |
# _XmlSerializable`` rather than their declared interfaces. Field
# accessors (``Component.purl``, ``Component.cpe`` etc.) and the
# dynamic ``from_json`` classmethod are typed at runtime but
# invisible to the static checker. The suppressions above are
# scoped to this module so the rest of the codebase keeps strict
# checking.
"""CycloneDX 1.7 SBoM ingestion.

This module owns the full SBoM ingestion pipeline:

1. :func:`parse` — pure CycloneDX 1.7 deserialization, returns a
   flat list of :class:`NormalizedComponent` records.
2. :func:`replace_release_components` — idempotent graph upsert
   that drops a release's existing component edges and rebuilds
   them from a normalized list (``Component`` →
   ``ComponentRelease`` → ``ComponentIdentifier``).
3. :func:`list_release_components` — reverse lookup used by the
   ``GET .../dependencies`` endpoint.

Cypher templates live as ``typing.LiteralString`` constants below.
The CycloneDX parse path is pure and depends only on stdlib and
``cyclonedx-python-lib``; the graph functions accept a
:class:`graph.Graph` and perform AGE I/O.
"""

import asyncio
import collections.abc
import datetime
import json
import logging
import typing

import cyclonedx.exception.model
import cyclonedx.model
import nanoid
import pydantic
from cyclonedx.model import bom as cdx_bom
from cyclonedx.model import component as cdx_component
from cyclonedx.model import license as cdx_license
from packageurl import PackageURL

from imbi.common import graph

LOGGER = logging.getLogger(__name__)

#: The single CycloneDX spec version we accept on the wire. The
#: producer side (build CI) is expected to emit 1.7 verbatim; we
#: deliberately do not silently coerce earlier versions because the
#: 1.7 schema introduces a handful of fields (e.g. tagged-by) we
#: store, and 1.5/1.6 payloads would arrive with subtle data loss.
SUPPORTED_SPEC_VERSION: typing.Final = '1.7'

#: CycloneDX identifier kinds we project into ``ComponentIdentifier``
#: nodes. ``bom-ref`` is intentionally excluded — it is a per-SBoM
#: internal cross-reference, not a stable global identity for a
#: component, and conflating the two would create spurious matches
#: across unrelated SBoMs that happen to reuse the same string.
_IDENTIFIER_KINDS: typing.Final = ('purl', 'cpe')

#: ``component.properties[].name`` values cdxgen emits to attribute a
#: component to a named dependency group. The list is intentionally
#: short — only ``cdx:pyproject:group`` is in use today and covers
#: both Poetry groups and PEP 735 ``[dependency-groups]``. As cdxgen
#: gains support for similar groupings in other ecosystems (npm
#: workspaces, Maven profiles, etc.) we extend this tuple rather than
#: matching ``cdx:*:group`` with a regex, so that boolean-flag
#: properties like ``cdx:npm:package:development`` never accidentally
#: land in the ``groups`` list.
#:
#: The CycloneDX 1.7 property-taxonomy reference is at
#: https://github.com/CycloneDX/cyclonedx-property-taxonomy.
_GROUP_PROPERTY_NAMES: typing.Final[tuple[str, ...]] = ('cdx:pyproject:group',)

#: CycloneDX 1.7 ``scope`` values we round-trip on the ingest path.
_COMPONENT_SCOPES: typing.Final = ('required', 'optional', 'excluded')

#: Maximum number of components we upsert in parallel during a single
#: SBoM PUT. A typical Python project ships 30-80 components, while a
#: typical npm tree is 500-1500 — serial upserts at AGE round-trip
#: latency are slow enough that the gateway times out before the API
#: finishes. Bound the gather so we don't swamp the connection pool;
#: each task holds one connection for the lifetime of its
#: UPSERT_COMPONENT_AND_LINK + identifier upserts. 16 is conservative
#: against the default psycopg pool size and leaves headroom for
#: other in-flight requests. Tune via the settings module if pool-
#: saturation warnings start appearing under realistic SBoM sizes.
_UPSERT_CONCURRENCY: typing.Final = 16


class SBomError(Exception):
    """Base class for SBoM parsing failures.

    Subclasses map to specific HTTP responses on the endpoint side
    so the API can return precise status codes without inspecting
    error messages.
    """


class UnsupportedSpecVersionError(SBomError):
    """Raised when ``specVersion`` is not :data:`SUPPORTED_SPEC_VERSION`.

    Mapped to ``415 Unsupported Media Type`` at the endpoint.
    """

    def __init__(self, received: object) -> None:
        super().__init__(
            f'CycloneDX specVersion {received!r} is not supported; '
            f'expected {SUPPORTED_SPEC_VERSION!r}.'
        )
        self.received = received


class MalformedSBomError(SBomError):
    """Raised when the payload is not a valid CycloneDX document.

    Mapped to ``400 Bad Request`` at the endpoint.
    """


class ComponentIdentity(pydantic.BaseModel):
    """A single ``(kind, value)`` pair attached to a component."""

    model_config = pydantic.ConfigDict(frozen=True)

    kind: typing.Literal['purl', 'cpe']
    value: str


class NormalizedComponent(pydantic.BaseModel):
    """Graph-ready projection of a single CycloneDX component.

    ``purl_name`` is the version-stripped package URL and is the
    canonical key for the upstream ``Component`` node. ``version``
    keys the ``ComponentRelease``. ``identifiers`` carry the
    version-stripped identifier values used to MERGE
    ``ComponentIdentifier`` nodes — the version-bearing purl/cpe
    direct from the SBoM is intentionally not persisted as a node.

    ``scope`` and ``groups`` are *usage* facts — they describe how
    the component is used by *this* release. They land on the
    ``Release-[:USES_COMPONENT_RELEASE]->ComponentRelease`` edge,
    not on the ``ComponentRelease`` node, because the same package
    version can be required by one project and a dev-only
    dependency in another.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    purl_name: str
    name: str
    ecosystem: str
    version: str
    license: str | None = None
    supplier: str | None = None
    hashes: dict[str, str] = pydantic.Field(default_factory=dict)
    description: str | None = None
    identifiers: list[ComponentIdentity] = pydantic.Field(
        default_factory=list,
    )
    scope: typing.Literal['required', 'optional', 'excluded'] | None = None
    groups: list[str] = pydantic.Field(default_factory=list)


def parse(payload: object) -> list[NormalizedComponent]:
    """Validate and normalize a CycloneDX 1.7 payload.

    :param payload: The decoded JSON body (already a ``dict``).
    :returns: A deduplicated list of ``NormalizedComponent`` records,
        one per unique ``(purl_name, version)`` pair encountered in
        ``components[]``. Components without enough information to
        derive a ``purl_name`` are silently skipped — the SBoM
        producer is responsible for emitting a purl for everything
        we care about; skipping is preferable to inventing a
        synthetic identity that may collide.
    :raises UnsupportedSpecVersionError: if ``specVersion`` is not
        ``"1.7"``.
    :raises MalformedSBomError: if the payload is not a CycloneDX
        document the library can parse.
    """
    if not isinstance(payload, dict):
        raise MalformedSBomError('CycloneDX payload must be a JSON object')
    spec_version = payload.get('specVersion')
    if spec_version != SUPPORTED_SPEC_VERSION:
        raise UnsupportedSpecVersionError(spec_version)

    try:
        # ``from_json`` is dynamically injected by py_serializable and
        # is therefore invisible to mypy / basedpyright.
        bom = cdx_bom.Bom.from_json(  # type: ignore[attr-defined]
            typing.cast(typing.Any, payload)
        )
    except (
        cyclonedx.exception.model.CycloneDxModelException,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise MalformedSBomError(f'Invalid CycloneDX document: {exc}') from exc

    seen: dict[tuple[str, str], NormalizedComponent] = {}
    for component in bom.components:
        normalized = _normalize(component)
        if normalized is None:
            continue
        key = (normalized.purl_name, normalized.version)
        if key in seen:
            continue
        seen[key] = normalized
    return list(seen.values())


def _normalize(
    component: cdx_component.Component,
) -> NormalizedComponent | None:
    """Project a CycloneDX ``Component`` into a NormalizedComponent.

    Returns ``None`` when the component has no purl — without one
    we have no stable identity to key on. Callers skip such rows.
    """
    purl = component.purl
    if purl is None:
        LOGGER.debug('Skipping component %r — no purl in SBoM', component.name)
        return None

    purl_name = _strip_purl_version(purl)
    version = component.version or purl.version
    if not version:
        LOGGER.debug(
            'Skipping component %r — no version in SBoM',
            component.name,
        )
        return None

    identifiers: list[ComponentIdentity] = [
        ComponentIdentity(kind='purl', value=purl_name),
    ]
    if component.cpe:
        identifiers.append(
            ComponentIdentity(
                kind='cpe', value=_strip_cpe_version(component.cpe)
            ),
        )

    return NormalizedComponent(
        purl_name=purl_name,
        name=component.name,
        ecosystem=purl.type,
        version=version,
        license=_normalize_license(component.licenses),
        supplier=component.supplier.name if component.supplier else None,
        hashes={hash_.alg.value: hash_.content for hash_ in component.hashes},
        description=component.description,
        scope=_normalize_scope(component.scope),
        groups=_collect_groups(component.properties),
        identifiers=identifiers,
    )


def _strip_purl_version(purl: PackageURL) -> str:
    """Return the purl string with any ``@version`` segment removed."""
    return str(
        PackageURL(
            type=purl.type,
            namespace=purl.namespace,
            name=purl.name,
            qualifiers=purl.qualifiers,
            subpath=purl.subpath,
        )
    )


def _strip_cpe_version(cpe: str) -> str:
    """Return a CPE 2.3 string with the version segment masked to ``*``.

    CPE 2.3 URIs are colon-delimited with version at index 5
    (``cpe:2.3:<part>:<vendor>:<product>:<version>:<update>:…``).
    Replacing the version with ``*`` collapses every per-version CPE
    a producer might emit to a single component-level identifier.
    Inputs that don't look like CPE 2.3 are returned unchanged —
    that's an SBoM producer issue, not ours to silently rewrite.
    """
    parts = cpe.split(':')
    if len(parts) >= 6 and parts[0] == 'cpe' and parts[1] == '2.3':
        parts[5] = '*'
        return ':'.join(parts)
    return cpe


def _normalize_license(
    licenses: collections.abc.Iterable[cdx_license.License],
) -> str | None:
    """Reduce CycloneDX license records to a single SPDX-ish string.

    Producers emit licenses in three shapes:
    - ``LicenseExpression`` (the SPDX expression form, preferred)
    - ``License`` with an ``id`` (SPDX identifier like ``MIT``)
    - ``License`` with a free-form ``name``

    We return the first hit in that priority order, joined with
    ``" AND "`` when multiple records co-exist. ``None`` means the
    component declared no license metadata.
    """
    expressions: list[str] = []
    for record in licenses:
        if isinstance(record, cdx_license.LicenseExpression):
            expressions.append(str(record.value))
            continue
        if record.id:
            expressions.append(record.id)
            continue
        if record.name:
            expressions.append(record.name)
    if not expressions:
        return None
    return ' AND '.join(expressions)


def _normalize_scope(
    scope: cdx_component.ComponentScope | None,
) -> typing.Literal['required', 'optional', 'excluded'] | None:
    """Coerce ``cyclonedx.model.component.ComponentScope`` to a literal.

    CycloneDX 1.7 defines three scopes; we round-trip exactly those.
    A ``None`` input — the producer did not declare ``scope`` — is
    surfaced as ``None`` rather than defaulted to ``"required"``,
    so the UI can distinguish "explicitly required" from "unstated".
    """
    if scope is None:
        return None
    value = scope.value
    if value == 'required':
        return 'required'
    if value == 'optional':
        return 'optional'
    if value == 'excluded':
        return 'excluded'
    return None


def _collect_groups(
    properties: collections.abc.Iterable[cyclonedx.model.Property],
) -> list[str]:
    """Read dependency-group names off of the curated property allow-list.

    Returns a sorted, de-duplicated list. Properties with empty
    values are skipped — they appear in some pipelines as placeholder
    rows when the producer cannot determine the group.
    """
    groups: set[str] = set()
    for prop in properties:
        if prop.name in _GROUP_PROPERTY_NAMES and prop.value:
            groups.add(prop.value)
    return sorted(groups)


# ----- Graph upsert / lookup ----------------------------------------

# Drops every USES_COMPONENT_RELEASE edge from a project release.
# Re-running an SBoM PUT replaces the dependency set wholesale —
# this query is the "replace" half of that contract. ``Component``
# and ``ComponentRelease`` nodes are intentionally left alone; they
# may still be referenced by other projects.
_CLEAR_RELEASE_COMPONENTS: typing.LiteralString = """
MATCH (:Release {{id: {release_id}}})-[edge:USES_COMPONENT_RELEASE]->()
DELETE edge
"""

# Upsert one Component plus its single ComponentRelease and link
# that ComponentRelease to the project Release. ``COALESCE`` lets
# the same plain ``SET`` clause serve both create and update —
# AGE has no ``ON CREATE SET`` / ``ON MATCH SET`` distinction.
#
# The ``USES_COMPONENT_RELEASE`` edge carries the *usage* facts
# (``scope`` and ``groups``) — see ``ReleaseComponentEdge`` and
# ADR 0015. ``groups`` is JSON-encoded because AGE stores list-of-
# string properties as JSON strings the same way it stores dicts.
_UPSERT_COMPONENT_AND_LINK: typing.LiteralString = """
MATCH (r:Release {{id: {release_id}}})
MERGE (c:Component {{purl_name: {purl_name}}})
SET c.id = COALESCE(c.id, {component_id}),
    c.name = {name},
    c.ecosystem = {ecosystem},
    c.description = {description},
    c.created_at = COALESCE(c.created_at, {now}),
    c.updated_at = {now}
MERGE (c)-[:HAS_RELEASE]->(cr:ComponentRelease {{version: {version}}})
SET cr.id = COALESCE(cr.id, {component_release_id}),
    cr.license = {license},
    cr.supplier = {supplier},
    cr.hashes = {hashes},
    cr.created_at = COALESCE(cr.created_at, {now}),
    cr.updated_at = {now}
MERGE (r)-[e:USES_COMPONENT_RELEASE]->(cr)
SET e.scope = {scope},
    e.groups = {groups}
RETURN c.id AS component_id
"""

# Attach one identifier to a Component, MERGEing on the globally
# unique ``(kind, value)`` pair so the same purl shared by two
# components is impossible by construction.
_UPSERT_COMPONENT_IDENTIFIER: typing.LiteralString = """
MATCH (c:Component {{id: {component_id}}})
MERGE (ci:ComponentIdentifier {{kind: {kind}, value: {value}}})
SET ci.id = COALESCE(ci.id, {identifier_id}),
    ci.created_at = COALESCE(ci.created_at, {now}),
    ci.updated_at = {now}
MERGE (c)-[:IDENTIFIED_BY]->(ci)
"""

# Pull every component the named release uses, with version,
# license, supplier, identifier list, and per-release usage
# attribution off of the ``USES_COMPONENT_RELEASE`` edge.
# ``OPTIONAL MATCH`` on identifiers keeps a component visible even
# when no identifier nodes have been attached yet.
_LIST_RELEASE_COMPONENTS: typing.LiteralString = """
MATCH (:Release {{id: {release_id}}})
      -[e:USES_COMPONENT_RELEASE]->(cr:ComponentRelease)
MATCH (c:Component)-[:HAS_RELEASE]->(cr)
OPTIONAL MATCH (c)-[:IDENTIFIED_BY]->(ci:ComponentIdentifier)
RETURN c.id AS component_id,
       c.purl_name AS purl_name,
       c.name AS name,
       c.ecosystem AS ecosystem,
       c.description AS description,
       cr.id AS component_release_id,
       cr.version AS version,
       cr.license AS license,
       cr.supplier AS supplier,
       cr.hashes AS hashes,
       e.scope AS scope,
       e.groups AS groups,
       collect(DISTINCT {{kind: ci.kind, value: ci.value}}) AS identifiers
"""


async def replace_release_components(
    db: graph.Graph,
    release_id: str,
    components: collections.abc.Sequence[NormalizedComponent],
) -> None:
    """Replace a release's component edges with the given set.

    The operation is idempotent: existing
    ``USES_COMPONENT_RELEASE`` edges from ``release_id`` are
    dropped, then re-created from ``components``. Component and
    ComponentRelease nodes are MERGE-ed (created if absent,
    updated if present) so unrelated projects keep their
    references intact.

    Concurrency strategy: components are bucketed by ``purl_name``;
    each bucket runs sequentially, and buckets parallelize via
    ``asyncio.gather`` bounded by :data:`_UPSERT_CONCURRENCY`.
    Serializing within a bucket is load-bearing — two parallel
    MERGEs against the same ``Component`` vertex (e.g.
    ``react-is@17`` and ``react-is@18``, which share
    ``pkg:npm/react-is``) trigger AGE's "Entity failed to be
    updated: 3" vertex-version conflict. Different purl_names
    target different vertices, so cross-bucket parallelism is
    safe. Each task holds one pool connection at a time for the
    duration of its current ``db.execute``.

    Failures are *non-fatal*: a per-component exception is caught,
    logged as a warning, and the other components continue
    (within the same bucket and across buckets). Partial graph
    state is more useful than no graph state for deps-listing
    purposes, and the producer side typically re-PUTs on the
    next build anyway.

    The function does not own a transaction — callers using the
    Graph pool already run each ``execute`` inside its own
    connection. If atomic replace-set semantics become important
    we should lift the calls into an explicit transaction.
    """
    now = datetime.datetime.now(datetime.UTC).isoformat()
    await db.execute(
        _CLEAR_RELEASE_COMPONENTS,
        {'release_id': release_id},
    )
    if not components:
        return
    buckets: dict[str, list[NormalizedComponent]] = {}
    for component in components:
        buckets.setdefault(component.purl_name, []).append(component)
    semaphore = asyncio.Semaphore(_UPSERT_CONCURRENCY)
    bucket_items = list(buckets.values())
    results = await asyncio.gather(
        *(
            _upsert_component_bucket(db, release_id, bucket, now, semaphore)
            for bucket in bucket_items
        ),
        return_exceptions=True,
    )
    # Bucket-level exceptions (something escaped the per-component
    # try/except — usually a connection-pool or programming error)
    # land here. Per-component failures were already logged
    # inside the bucket task.
    for bucket, result in zip(bucket_items, results, strict=True):
        if isinstance(result, BaseException):
            LOGGER.warning(
                'Bucket %s failed during SBoM ingest for release %s: %s: %s',
                bucket[0].purl_name,
                release_id,
                type(result).__name__,
                result,
            )


async def _upsert_component_bucket(
    db: graph.Graph,
    release_id: str,
    bucket: collections.abc.Sequence[NormalizedComponent],
    now: str,
    semaphore: asyncio.Semaphore,
) -> None:
    """Upsert every component in a ``purl_name`` bucket sequentially.

    All components in the bucket share a ``purl_name`` — and
    therefore the same ``Component`` vertex — so they must be
    serialized to avoid AGE's "Entity failed to be updated: 3"
    conflict. Per-component failures are logged here, not raised,
    so one bad version doesn't stop the bucket's remaining
    versions from landing. The bucket itself raises only on
    unexpected (non-component) errors.
    """
    async with semaphore:
        for component in bucket:
            try:
                await _upsert_one_component(db, release_id, component, now)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    'Failed to ingest component %s@%s for release %s: %s: %s',
                    component.purl_name,
                    component.version,
                    release_id,
                    type(exc).__name__,
                    exc,
                )


async def _upsert_one_component(
    db: graph.Graph,
    release_id: str,
    component: NormalizedComponent,
    now: str,
) -> None:
    """Upsert one ``Component`` + ``ComponentRelease`` + identifiers.

    Raises on any AGE failure so the bucket loop can log it and
    move on. Concurrency control is the bucket's responsibility
    (it owns the semaphore); this helper assumes serial execution
    against a single purl_name.
    """
    rows = await db.execute(
        _UPSERT_COMPONENT_AND_LINK,
        {
            'release_id': release_id,
            'purl_name': component.purl_name,
            'component_id': nanoid.generate(),
            'name': component.name,
            'ecosystem': component.ecosystem,
            'description': component.description,
            'version': component.version,
            'component_release_id': nanoid.generate(),
            'license': component.license,
            'supplier': component.supplier,
            'hashes': json.dumps(component.hashes),
            'scope': component.scope,
            'groups': json.dumps(component.groups),
            'now': now,
        },
        ['component_id'],
    )
    if not rows:
        # The release was deleted (or never existed) — the upsert
        # MATCHed nothing. Surface this as an exception so the
        # bucket logs it the same way it logs any other
        # per-component failure.
        raise RuntimeError(
            f'release {release_id!r} not found during component upsert'
        )
    component_db_id = graph.parse_agtype(rows[0]['component_id'])
    for identifier in component.identifiers:
        await db.execute(
            _UPSERT_COMPONENT_IDENTIFIER,
            {
                'component_id': component_db_id,
                'kind': identifier.kind,
                'value': identifier.value,
                'identifier_id': nanoid.generate(),
                'now': now,
            },
        )


class ListedIdentifier(pydantic.BaseModel):
    """One ``(kind, value)`` pair on a component returned by GET."""

    kind: str
    value: str


class ListedComponent(pydantic.BaseModel):
    """Flattened component row for the ``GET …/dependencies`` body.

    ``scope`` and ``groups`` come off of the
    ``USES_COMPONENT_RELEASE`` edge — they are per-release usage
    facts, not properties of the component-release itself.
    """

    purl_name: str
    name: str
    ecosystem: str
    description: str | None = None
    version: str
    license: str | None = None
    supplier: str | None = None
    hashes: dict[str, str] = pydantic.Field(default_factory=dict)
    identifiers: list[ListedIdentifier] = pydantic.Field(
        default_factory=list,
    )
    scope: str | None = None
    groups: list[str] = pydantic.Field(default_factory=list)


async def list_release_components(
    db: graph.Graph, release_id: str
) -> list[ListedComponent]:
    """Return the dependency set a release was ingested with.

    Components without a recorded SBoM yield an empty list — the
    caller (the GET endpoint) is responsible for distinguishing
    "no SBoM yet" from "unknown release" via a separate
    ``_fetch_release`` precondition check.
    """
    rows = await db.execute(
        _LIST_RELEASE_COMPONENTS,
        {'release_id': release_id},
        [
            'component_id',
            'purl_name',
            'name',
            'ecosystem',
            'description',
            'component_release_id',
            'version',
            'license',
            'supplier',
            'hashes',
            'scope',
            'groups',
            'identifiers',
        ],
    )
    out: list[ListedComponent] = []
    for row in rows:
        hashes_raw = graph.parse_agtype(row['hashes'])
        if isinstance(hashes_raw, str):
            hashes_decoded = typing.cast(
                dict[str, str], json.loads(hashes_raw)
            )
        elif isinstance(hashes_raw, dict):
            hashes_decoded = typing.cast(dict[str, str], hashes_raw)
        else:
            hashes_decoded = {}
        identifiers_raw = graph.parse_agtype(row['identifiers'])
        identifiers: list[ListedIdentifier] = []
        if isinstance(identifiers_raw, list):
            for entry in identifiers_raw:
                if (
                    isinstance(entry, dict)
                    and entry.get('kind') is not None
                    and entry.get('value') is not None
                ):
                    identifiers.append(
                        ListedIdentifier(
                            kind=str(entry['kind']),
                            value=str(entry['value']),
                        ),
                    )
        out.append(
            ListedComponent(
                purl_name=str(graph.parse_agtype(row['purl_name'])),
                name=str(graph.parse_agtype(row['name'])),
                ecosystem=str(graph.parse_agtype(row['ecosystem'])),
                description=_optional_str(row.get('description')),
                version=str(graph.parse_agtype(row['version'])),
                license=_optional_str(row.get('license')),
                supplier=_optional_str(row.get('supplier')),
                hashes=hashes_decoded,
                identifiers=identifiers,
                scope=_optional_str(row.get('scope')),
                groups=_decode_groups(row.get('groups')),
            ),
        )
    return out


def _decode_groups(raw: typing.Any) -> list[str]:
    """Decode the JSON-encoded ``e.groups`` edge property into a list.

    AGE stores list-of-string edge properties as JSON strings the
    same way it stores dicts. ``None`` and unparseable values
    collapse to an empty list rather than propagating ``None`` —
    the empty-list case is by far the most common (a release with
    no scoped group info).
    """
    if raw is None:
        return []
    value = graph.parse_agtype(raw)
    if value is None:
        return []
    if isinstance(value, list):
        return [str(g) for g in value]
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return []
        if isinstance(decoded, list):
            return [str(g) for g in decoded]
    return []


def _optional_str(raw: typing.Any) -> str | None:
    """Return ``str(value)`` for present scalars, else ``None``."""
    value = graph.parse_agtype(raw) if raw is not None else None
    if value is None:
        return None
    return str(value)
