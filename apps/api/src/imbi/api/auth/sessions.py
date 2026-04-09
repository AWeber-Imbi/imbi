"""Session management and enforcement (Phase 5).

This module provides functions for managing user sessions, enforcing
concurrent session limits, and tracking session activity.
"""

import datetime
import logging
import typing

from imbi_common import graph

from imbi_api import settings

LOGGER = logging.getLogger(__name__)


async def enforce_session_limit(
    db: graph.Graph,
    email: str,
    auth_settings: settings.Auth,
) -> None:
    """Enforce maximum concurrent sessions by removing oldest.

    When a user has more than the maximum allowed concurrent sessions,
    this function removes the oldest sessions (by last_activity
    timestamp) to bring the count within the limit.

    Args:
        db: Graph database connection.
        email: Email of the user to enforce session limit for.
        auth_settings: Auth settings containing
            max_concurrent_sessions.

    """
    query = (
        'MATCH (u:User {{email: {email}}})'
        '<-[:SESSION_FOR]-(s:Session) '
        'RETURN s.session_id, s.last_activity '
        'ORDER BY s.last_activity DESC'
    )
    records = await db.execute(
        query,
        {'email': email},
        columns=['session_id', 'last_activity'],
    )

    sessions: list[dict[str, typing.Any]] = []
    for record in records:
        sessions.append(
            {
                'session_id': graph.parse_agtype(record.get('session_id')),
                'last_activity': graph.parse_agtype(
                    record.get('last_activity')
                ),
            }
        )

    if len(sessions) > auth_settings.max_concurrent_sessions:
        # Remove oldest sessions (those beyond the limit)
        sessions_to_remove: list[dict[str, typing.Any]] = sessions[
            auth_settings.max_concurrent_sessions :
        ]
        for s in sessions_to_remove:
            delete_query = (
                'MATCH (s:Session '
                '{{session_id: {session_id}}}) '
                'DETACH DELETE s'
            )
            await db.execute(
                delete_query,
                {'session_id': s['session_id']},
            )

        LOGGER.info(
            'Removed %d old sessions for user %s',
            len(sessions_to_remove),
            email,
        )


async def update_session_activity(db: graph.Graph, session_id: str) -> None:
    """Update last activity timestamp for session.

    Args:
        db: Graph database connection.
        session_id: Session ID to update.

    """
    now = datetime.datetime.now(datetime.UTC).isoformat()
    query = (
        'MATCH (s:Session {{session_id: {session_id}}}) '
        'SET s.last_activity = {now}'
    )
    await db.execute(query, {'session_id': session_id, 'now': now})


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
