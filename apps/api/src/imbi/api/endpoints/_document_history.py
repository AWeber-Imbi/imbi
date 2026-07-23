"""Version-history recording for documents (ClickHouse write side).

Owns the versioning policy: what counts as a new version
(:func:`resolve_change`) and how snapshots are recorded
(:func:`record_created` / :func:`record_updated`). The read-side
endpoints live in ``document_versions.py``; keeping the recorder here
lets both ``documents.py`` and ``document_versions.py`` import it
top-level without a cycle.

Snapshot capture is best-effort: the graph is the source of truth, so
a failed ClickHouse insert is logged rather than surfaced as an error
(the affected version number is simply absent from the history).
"""

import datetime
import logging
import typing

import pydantic

from imbi.common import clickhouse

LOGGER = logging.getLogger(__name__)

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


def has_changed(
    existing: dict[str, typing.Any],
    title: str,
    content: str,
    tags: list[str],
) -> bool:
    """Whether an update produces a new version.

    Only title/content/tag changes count; pin toggles and no-op
    patches keep the current version. The version number itself is
    assigned atomically by the graph ``SET`` so concurrent saves
    cannot collide on it.
    """
    return (
        title != str(existing.get('title') or '')
        or content != existing['content']
        or sorted(tags) != sorted(t['slug'] for t in existing.get('tags', []))
    )


async def _has_history(document_id: str) -> bool:
    """Whether any version rows exist for the document."""
    rows = await clickhouse.query(
        'SELECT count() AS c FROM document_versions '
        'WHERE document_id = {document_id:String}',
        {'document_id': document_id},
    )
    return bool(rows and int(rows[0].get('c') or 0))


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
        await clickhouse.insert(
            'document_versions',
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
            ],
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
    When a document at version 1 has no history yet (it predates
    versioning, or its create snapshot was lost), the pre-edit state is
    first written as a ``baseline`` row so the original content is
    retained. Documents already past version 1 were versioned by this
    code path, so the existence probe is skipped for them.
    """
    now = datetime.datetime.now(datetime.UTC)
    try:
        rows: list[pydantic.BaseModel] = []
        if new_version <= 2 and not await _has_history(document_id):
            prev_ts = str(
                previous.get('updated_at') or previous.get('created_at') or ''
            )
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
                    updated_at=(
                        datetime.datetime.fromisoformat(prev_ts)
                        if prev_ts
                        else now
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
        await clickhouse.insert('document_versions', rows)
    except Exception:
        LOGGER.exception(
            'failed to record version %s for document %s',
            new_version,
            document_id,
        )
