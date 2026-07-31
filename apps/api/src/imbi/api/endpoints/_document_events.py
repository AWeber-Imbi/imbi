"""Activity-feed events for document engagement (ClickHouse write side).

Writes ``imbi.events`` rows so document engagement surfaces in the
project and user activity feeds alongside comments. Best-effort in the
same sense as the version-history recorder: the request it belongs to
has already succeeded, so a failed analytics write is logged rather
than surfaced.
"""

import datetime
import logging

from imbi.common import clickhouse, models

LOGGER = logging.getLogger(__name__)

#: Event type for a like or unlike on a document.
LIKE_EVENT_TYPE = 'document-like'


async def emit_like_event(
    *,
    org_slug: str,
    project_id: str,
    document_id: str,
    principal: str,
    action: str,
    occurred_at: datetime.datetime,
) -> None:
    """Record a like/unlike as an ``events`` row. Best-effort.

    ``project_id`` is empty for documents attached to a project type or
    a user; those events still land and are readable from the user
    activity feed, which keys on ``attributed_to`` rather than project.
    """
    try:
        await clickhouse.insert(
            'events',
            [
                models.Event(
                    project_id=project_id,
                    recorded_at=occurred_at,
                    type=LIKE_EVENT_TYPE,
                    integration='internal',
                    attributed_to=principal,
                    payload={
                        'org_slug': org_slug,
                        'document_id': document_id,
                        'action': action,
                    },
                )
            ],
        )
    except Exception:
        LOGGER.exception(
            'Failed to emit %s event for document %s', action, document_id
        )
