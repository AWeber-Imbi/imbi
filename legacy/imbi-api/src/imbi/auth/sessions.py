"""Session management and enforcement (Phase 5).

This module provides functions for managing user sessions, enforcing
concurrent session limits, and tracking session activity.
"""

import logging

from imbi import neo4j, settings

LOGGER = logging.getLogger(__name__)


async def enforce_session_limit(
    username: str, auth_settings: settings.Auth
) -> None:
    """Enforce maximum concurrent sessions by removing oldest.

    When a user has more than the maximum allowed concurrent sessions,
    this function removes the oldest sessions (by last_activity timestamp)
    to bring the count within the limit.

    Args:
        username: Username to enforce session limit for
        auth_settings: Auth settings containing max_concurrent_sessions

    """
    query = """
    MATCH (u:User {username: $username})<-[:SESSION_FOR]-(s:Session)
    RETURN s.session_id as session_id, s.last_activity as last_activity
    ORDER BY s.last_activity DESC
    """
    async with neo4j.run(query, username=username) as result:
        sessions = await result.data()

    if len(sessions) > auth_settings.max_concurrent_sessions:
        # Remove oldest sessions (those beyond the limit)
        sessions_to_remove = sessions[auth_settings.max_concurrent_sessions :]
        session_ids = [s['session_id'] for s in sessions_to_remove]

        delete_query = """
        MATCH (s:Session)
        WHERE s.session_id IN $session_ids
        DETACH DELETE s
        """
        async with neo4j.run(delete_query, session_ids=session_ids) as result:
            await result.consume()

        LOGGER.info(
            'Removed %d old sessions for user %s',
            len(session_ids),
            username,
        )


async def update_session_activity(session_id: str) -> None:
    """Update last activity timestamp for session.

    Args:
        session_id: Session ID to update

    """
    query = """
    MATCH (s:Session {session_id: $session_id})
    SET s.last_activity = datetime()
    """
    async with neo4j.run(query, session_id=session_id) as result:
        await result.consume()


async def delete_expired_sessions() -> int:
    """Delete expired sessions from the database.

    This function should be called periodically (e.g., via background task)
    to clean up expired sessions.

    Returns:
        Number of sessions deleted

    """
    query = """
    MATCH (s:Session)
    WHERE s.expires_at < datetime()
    DETACH DELETE s
    RETURN count(s) as deleted_count
    """
    async with neo4j.run(query) as result:
        records = await result.data()
        count = records[0]['deleted_count'] if records else 0

    if count > 0:
        LOGGER.info('Deleted %d expired sessions', count)

    return count
