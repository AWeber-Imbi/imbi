"""Document version-history endpoints (ClickHouse read side).

Snapshots are recorded by :mod:`imbi.api.endpoints._document_history`
on every content-affecting change; these endpoints list them, fetch a
single snapshot, and restore one — restore applies the old snapshot as
a normal update producing a new version, so history is never
rewritten.
"""

import datetime
import typing

import fastapi
import pydantic

from imbi.api.auth import permissions
from imbi.api.endpoints import documents
from imbi.api.endpoints._document_history import ChangeKind
from imbi.api.endpoints._helpers import fetch_or_404
from imbi.common import clickhouse, graph

document_versions_router = fastapi.APIRouter(tags=['Documents'])


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


def _row_to_dict(row: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Attach UTC to naive DateTime64 values coming back from ClickHouse."""
    out = dict(row)
    ts = out.get('updated_at')
    if isinstance(ts, datetime.datetime) and ts.tzinfo is None:
        out['updated_at'] = ts.replace(tzinfo=datetime.UTC)
    return out


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
    await fetch_or_404(
        documents.fetch_document,
        db,
        org_slug,
        document_id,
        detail=f'Document {document_id!r} not found',
    )
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
    await fetch_or_404(
        documents.fetch_document,
        db,
        org_slug,
        document_id,
        detail=f'Document {document_id!r} not found',
    )
    return await fetch_or_404(
        _fetch_version,
        document_id,
        version,
        detail=f'Version {version} of document {document_id!r} not found',
    )


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
    background_tasks: fastapi.BackgroundTasks,
) -> dict[str, typing.Any]:
    """Restore a document to a previous version.

    Applies the old snapshot as a normal update, producing a new
    version with ``change_kind='restore'`` — history is never
    rewritten. Snapshot tags that no longer exist in the org are
    dropped rather than failing the restore.
    """
    existing = await fetch_or_404(
        documents.fetch_document,
        db,
        org_slug,
        document_id,
        detail=f'Document {document_id!r} not found',
    )
    row = await fetch_or_404(
        _fetch_version,
        document_id,
        version,
        detail=f'Version {version} of document {document_id!r} not found',
    )
    raw_tags: list[typing.Any] = row.get('tags') or []
    tags = await documents.filter_existing_tag_slugs(
        db, org_slug, [str(t) for t in raw_tags]
    )
    return await documents.apply_document_update(
        db,
        auth,
        background_tasks,
        org_slug,
        document_id,
        existing,
        title=str(row['title']),
        content=str(row['content']),
        tags=tags,
        replace_tags=True,
        is_pinned=bool(existing.get('is_pinned', False)),
        change_kind='restore',
    )
