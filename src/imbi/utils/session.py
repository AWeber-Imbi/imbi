"""
Session management using Valkey (Redis-compatible).

Sessions are stored in Valkey with JSON-serialized user data.
"""

from __future__ import annotations

import datetime
import json
import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as aioredis
    from fastapi import Request

logger = logging.getLogger(__name__)


class Session:
    """Session manager for authenticated users."""

    def __init__(
        self,
        request: Request,
        valkey: aioredis.Redis,
        cookie_name: str = "session",
        duration: int = 7,  # days
    ):
        self.request = request
        self.valkey = valkey
        self.cookie_name = cookie_name
        self.duration = duration
        self.session_id: str | None = None
        self.data: dict = {}
        self.authenticated = False

    @property
    def _redis_key(self) -> str:
        """Get the Valkey key for this session."""
        return f"session:{self.session_id}"

    async def load(self) -> None:
        """Load session data from Valkey."""
        # Get session ID from cookie
        self.session_id = self.request.session.get("id")

        if not self.session_id:
            logger.debug("No session ID in cookie")
            return

        # Load from Valkey
        try:
            data = await self.valkey.get(self._redis_key)
            if data:
                self.data = json.loads(data)
                self.authenticated = bool(self.data.get("user"))
                logger.debug(f"Session loaded: {self.session_id}")
            else:
                logger.info(f"Session {self.session_id} not found in Valkey")
                self.session_id = None
        except Exception as e:
            logger.error(f"Failed to load session: {e}", exc_info=True)
            self.session_id = None

    async def save(self) -> None:
        """Save session data to Valkey."""
        if not self.session_id:
            self.session_id = str(uuid.uuid4())

        # Save session ID to cookie
        self.request.session["id"] = self.session_id

        # Save data to Valkey
        try:
            self.data["last_save"] = datetime.datetime.utcnow().isoformat()
            await self.valkey.set(
                self._redis_key,
                json.dumps(self.data),
                ex=self.duration * 86400,  # Convert days to seconds
            )
            logger.debug(f"Session saved: {self.session_id}")
        except Exception as e:
            logger.error(f"Failed to save session: {e}", exc_info=True)
            raise

    async def clear(self) -> None:
        """Clear session data from Valkey and cookie."""
        if self.session_id:
            try:
                await self.valkey.delete(self._redis_key)
                logger.debug(f"Session deleted: {self.session_id}")
            except Exception as e:
                logger.error(f"Failed to delete session: {e}", exc_info=True)

        # Clear cookie
        self.request.session.clear()
        self.session_id = None
        self.data = {}
        self.authenticated = False

    def get_user_data(self) -> dict | None:
        """Get user data from session."""
        return self.data.get("user")

    async def set_user_data(self, user_data: dict) -> None:
        """Set user data in session."""
        self.data["user"] = user_data
        self.data["start"] = datetime.datetime.utcnow().isoformat()
        self.authenticated = True
        await self.save()


async def get_session(request: Request) -> Session:
    """
    FastAPI dependency to get the session for a request.

    Args:
        request: The FastAPI request object

    Returns:
        Session instance
    """
    session = Session(
        request=request,
        valkey=request.app.state.session_valkey,
        cookie_name=request.app.state.config.session.cookie_name,
        duration=request.app.state.config.session.duration,
    )
    await session.load()
    return session
