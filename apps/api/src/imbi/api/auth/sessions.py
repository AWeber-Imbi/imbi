"""Session management and enforcement (Phase 5).

The original Phase 5 design wrote ``Session`` nodes alongside JWTs and
gated them with a concurrent-session limit + a per-request activity
stamp. The shipped auth stack tracks session state on
``TokenMetadata`` instead, so the original limit/activity helpers
were never called and have been removed (see code review H3). Only
the periodic cleanup helper remains for any leftover rows from earlier
schemas.
"""

import datetime
import logging

from imbi_common import graph

LOGGER = logging.getLogger(__name__)


async def delete_expired_sessions(db: graph.Graph) -> int:
    """Delete expired sessions from the database.

    This function should be called periodically (e.g., via background
    task) to clean up expired sessions.

    Args:
        db: Graph database connection.

    Returns:
        Number of sessions deleted.

    """
    now = datetime.datetime.now(datetime.UTC).isoformat()
    query = (
        'MATCH (s:Session) '
        'WHERE s.expires_at < {now} '
        'DETACH DELETE s '
        'RETURN count(s) AS deleted_count'
    )
    records = await db.execute(query, {'now': now}, columns=['deleted_count'])
    raw = graph.parse_agtype(
        records[0].get('deleted_count') if records else None
    )
    count = raw if isinstance(raw, int) else 0

    if count > 0:
        LOGGER.info('Deleted %d expired sessions', count)

    return count
