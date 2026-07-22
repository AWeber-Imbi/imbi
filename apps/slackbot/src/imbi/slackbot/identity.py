"""Map Slack users to Imbi users and mint per-user API tokens.

A Slack user is resolved to an Imbi user by email: the Slack profile
email (``users.info``) is matched against an active ``User`` node in the
graph. A short-lived per-user JWT access token is then minted with the
shared ``IMBI_AUTH_JWT_SECRET`` — identical to the token the Imbi API
issues at login — so every tool call the bot makes on the user's behalf
is authorized as, and limited to, that user.

Resolutions (including "no matching Imbi user") are cached with a TTL to
avoid hitting Slack and the graph on every message.

"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import typing

from imbi.common import graph
from imbi.common.auth import core
from imbi.slackbot import settings

# slack_sdk's AsyncWebClient is only loosely typed (its responses are
# AsyncSlackResponse with Unknown generics), so treat it as Any rather
# than propagate Unknown through every call site.
SlackClient = typing.Any

LOGGER = logging.getLogger(__name__)

_USER_QUERY = """
MATCH (u:User {{email: {email}}})
RETURN u
"""


@dataclasses.dataclass(frozen=True)
class ImbiUser:
    """An Imbi user resolved from a Slack identity."""

    email: str
    display_name: str
    is_admin: bool = False


@dataclasses.dataclass
class _CacheEntry:
    """A cached resolution; ``user`` is ``None`` for a known non-user."""

    user: ImbiUser | None
    expires_at: datetime.datetime


# Shared graph instance captured at startup via ``graph.set_on_startup``.
_graph: graph.Graph | None = None
_cache: dict[str, _CacheEntry] = {}


def set_graph(db: graph.Graph) -> None:
    """Capture the shared graph connection opened by ``graph_lifespan``."""
    global _graph
    _graph = db


async def on_graph_ready(db: graph.Graph) -> None:
    """``graph.set_on_startup`` callback that captures the connection."""
    set_graph(db)


def clear_cache() -> None:
    """Drop all cached resolutions (used by tests and on shutdown)."""
    _cache.clear()


async def _slack_email(
    slack_client: SlackClient,
    slack_user_id: str,
) -> str | None:
    """Return the Slack user's profile email, if any."""
    response: typing.Any = await slack_client.users_info(user=slack_user_id)
    user: typing.Any = response['user'] or {}
    profile: typing.Any = user.get('profile') or {}
    email: typing.Any = profile.get('email')
    return str(email) if email else None


async def _load_imbi_user(email: str) -> ImbiUser | None:
    """Look up an active Imbi ``User`` node by email."""
    if _graph is None:
        raise RuntimeError('Graph connection not initialized')
    records = await _graph.execute(_USER_QUERY, {'email': email}, ['u'])
    if not records:
        return None
    raw = graph.parse_agtype(records[0]['u'])
    if not isinstance(raw, dict):
        return None
    data = typing.cast('dict[str, typing.Any]', raw)
    if not data.get('is_active', True):
        return None
    return ImbiUser(
        email=email,
        display_name=str(data.get('display_name') or email),
        is_admin=bool(data.get('is_admin', False)),
    )


async def resolve(
    slack_client: SlackClient,
    slack_user_id: str,
    *,
    now: datetime.datetime | None = None,
) -> ImbiUser | None:
    """Resolve a Slack user id to an Imbi user, using the TTL cache.

    Args:
        slack_client: The Slack web client (for ``users.info``).
        slack_user_id: The Slack user id (e.g. ``U012ABCDEF``).
        now: Override the current time (for testing).

    Returns:
        The matching :class:`ImbiUser`, or ``None`` if the Slack user has
        no email or no active Imbi account.

    """
    now = now or datetime.datetime.now(datetime.UTC)
    entry = _cache.get(slack_user_id)
    if entry is not None and entry.expires_at > now:
        return entry.user

    email = await _slack_email(slack_client, slack_user_id)
    user = await _load_imbi_user(email) if email else None

    ttl = settings.get_slackbot_settings().identity_cache_ttl
    _cache[slack_user_id] = _CacheEntry(
        user=user,
        expires_at=now + datetime.timedelta(seconds=ttl),
    )
    if user is None:
        LOGGER.info('No Imbi user for Slack user %s', slack_user_id)
    return user


def mint_token(user: ImbiUser) -> str:
    """Mint a per-user Imbi API access token.

    The token is signed with the shared ``IMBI_AUTH_JWT_SECRET`` and
    carries the user's email as its subject, exactly as the Imbi API
    does at login. The API loads the user's permissions fresh from the
    graph on each request keyed by this subject.

    """
    return core.create_access_token(user.email)
