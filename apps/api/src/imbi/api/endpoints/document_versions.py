"""Document version history backed by ClickHouse.

Every content-affecting change to a ``Document`` node (title, content,
or tags) appends a full snapshot row to the ``document_versions``
ClickHouse table; the node itself carries the monotonically increasing
``version`` counter. Documents that predate versioning get a
``baseline`` snapshot of their pre-edit state the first time they are
edited so the original content is never lost.

Snapshot capture is best-effort: the graph is the source of truth, so
a failed ClickHouse insert is logged rather than surfaced as an error
(the affected version number is simply absent from the history).

``documents.py`` calls :func:`record_created` / :func:`record_updated`
via deferred imports; this module imports ``documents`` at module
level, so the reverse edge must stay lazy to avoid a cycle.
"""

import datetime
import logging
import typing

import fastapi
import pydantic

from imbi.api import patch as json_patch
from imbi.api.auth import permissions
from imbi.api.endpoints import documents
from imbi.common import clickhouse, graph

LOGGER = logging.getLogger(__name__)

document_versions_router = fastapi.APIRouter(tags=['Documents'])

ChangeKind = typing.Literal['create', 'update', 'restore', 'baseline']


class DocumentVersionRow(pydantic.BaseModel):
    """One row in the ``document_versions`` ClickHouse table."""

    document_id: str
    version: int
    title: str
    content: str
    tags: list[str]
    change_kind: ChangeKind
    updated_by: str
    updated_at: datetime.datetime
    recorded_at: datetime.datetime


class DocumentVersionInfo(pydantic.BaseModel):
    """Version metadata without the (potentially large) content."""

    version: int
    title: str
    change_kind: ChangeKind
    updated_by: str
    updated_at: datetime.datetime


class DocumentVersionResponse(DocumentVersionInfo):
    content: str
    tags: list[str] = []


class DocumentVersionListResponse(pydantic.BaseModel):
    data: list[DocumentVersionInfo]


async def _insert_rows(rows: list[DocumentVersionRow]) -> None:
    await clickhouse.insert('document_versions', list(rows))


async def _max_recorded_version(document_id: str) -> int | None:
    """Highest version recorded in ClickHouse, or None when no history."""
    rows = await clickhouse.query(
        'SELECT max(version) AS v, count() AS c FROM document_versions '
        'WHERE document_id = {document_id:String}',
        {'document_id': document_id},
    )
    if not rows or not int(rows[0].get('c') or 0):
        return None
    return int(rows[0]['v'])


def _parse_ts(
    value: typing.Any, fallback: datetime.datetime
) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.datetime.fromisoformat(value)
        except ValueError:
            return fallback
    return fallback


async def record_created(
    document_id: str,
    title: str,
    content: str,
    tags: list[str],
    created_by: str,
    created_at: datetime.datetime,
) -> None:
    """Record version 1 for a newly created document. Best-effort."""
    try:
        await _insert_rows(
            [
                DocumentVersionRow(
                    document_id=document_id,
                    version=1,
                    title=title,
                    content=content,
                    tags=tags,
                    change_kind='create',
                    updated_by=created_by,
                    updated_at=created_at,
                    recorded_at=created_at,
                )
            ]
        )
    except Exception:
        LOGGER.exception(
            'failed to record create snapshot for document %s', document_id
        )


async def record_updated(
    document_id: str,
    previous: dict[str, typing.Any],
    new_version: int,
    title: str,
    content: str,
    tags: list[str],
    change_kind: ChangeKind,
    updated_by: str,
    updated_at: datetime.datetime,
) -> None:
    """Record a snapshot for an edited document. Best-effort.

    ``previous`` is the parsed document dict as it was before the edit.
    When the document has no history yet (it predates versioning, or
    its create snapshot was lost), the pre-edit state is first written
    as a ``baseline`` row so the original content is retained.
    """
    now = datetime.datetime.now(datetime.UTC)
    try:
        rows: list[DocumentVersionRow] = []
        if await _max_recorded_version(document_id) is None:
            rows.append(
                DocumentVersionRow(
                    document_id=document_id,
                    version=new_version - 1,
                    title=str(previous.get('title') or ''),
                    content=str(previous.get('content') or ''),
                    tags=[t['slug'] for t in previous.get('tags', [])],
                    change_kind='baseline',
                    updated_by=str(
                        previous.get('updated_by')
                        or previous.get('created_by')
                        or ''
                    ),
                    updated_at=_parse_ts(
                        previous.get('updated_at')
                        or previous.get('created_at'),
                        now,
                    ),
                    recorded_at=now,
                )
            )
        rows.append(
            DocumentVersionRow(
                document_id=document_id,
                version=new_version,
                title=title,
                content=content,
                tags=tags,
                change_kind=change_kind,
                updated_by=updated_by,
                updated_at=updated_at,
                recorded_at=now,
            )
        )
        await _insert_rows(rows)
    except Exception:
        LOGGER.exception(
            'failed to record version %s for document %s',
            new_version,
            document_id,
        )


def _row_to_dict(row: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Attach UTC to naive DateTime64 values coming back from ClickHouse."""
    out = dict(row)
    ts = out.get('updated_at')
    if isinstance(ts, datetime.datetime) and ts.tzinfo is None:
        out['updated_at'] = ts.replace(tzinfo=datetime.UTC)
    return out


async def _require_document(
    db: graph.Pool, org_slug: str, document_id: str
) -> dict[str, typing.Any]:
    """404 unless the document exists within the caller's org."""
    existing = await documents.fetch_document(db, org_slug, document_id)
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Document {document_id!r} not found'
        )
    return existing


@document_versions_router.get('', response_model=DocumentVersionListResponse)
async def list_document_versions(
    org_slug: str,
    document_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
) -> dict[str, typing.Any]:
    """List a document's version history, newest first."""
    await _require_document(db, org_slug, document_id)
    rows = await clickhouse.query(
        'SELECT version, title, change_kind, updated_by, updated_at '
        'FROM document_versions FINAL '
        'WHERE document_id = {document_id:String} '
        'ORDER BY version DESC',
        {'document_id': document_id},
    )
    return {'data': [_row_to_dict(r) for r in rows]}


async def _fetch_version(
    document_id: str, version: int
) -> dict[str, typing.Any] | None:
    rows = await clickhouse.query(
        'SELECT version, title, content, tags, change_kind, updated_by, '
        'updated_at FROM document_versions FINAL '
        'WHERE document_id = {document_id:String} '
        'AND version = {version:UInt32} LIMIT 1',
        {'document_id': document_id, 'version': version},
    )
    return _row_to_dict(rows[0]) if rows else None


@document_versions_router.get(
    '/{version}', response_model=DocumentVersionResponse
)
async def get_document_version(
    org_slug: str,
    document_id: str,
    version: int,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
) -> dict[str, typing.Any]:
    """Retrieve the full snapshot of a single document version."""
    await _require_document(db, org_slug, document_id)
    row = await _fetch_version(document_id, version)
    if row is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Version {version} of document {document_id!r} not found',
        )
    return row


@document_versions_router.post(
    '/{version}/restore', response_model=documents.DocumentResponse
)
async def restore_document_version(
    org_slug: str,
    document_id: str,
    version: int,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:write')),
    ],
) -> dict[str, typing.Any]:
    """Restore a document to a previous version.

    Applies the old snapshot as a normal update, producing a new
    version with ``change_kind='restore'`` — history is never
    rewritten.
    """
    await _require_document(db, org_slug, document_id)
    row = await _fetch_version(document_id, version)
    if row is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Version {version} of document {document_id!r} not found',
        )
    operations = [
        json_patch.PatchOperation.model_validate(
            {'op': 'replace', 'path': path, 'value': value}
        )
        for path, value in (
            ('/title', row['title']),
            ('/content', row['content']),
            ('/tags', list(row.get('tags') or [])),
        )
    ]
    return await documents.patch_document_impl(
        db, auth, org_slug, document_id, operations, change_kind='restore'
    )
