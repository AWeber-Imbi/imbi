"""Map Slack users to Imbi users and mint per-user API tokens.

A Slack user is resolved to an Imbi user by email: the Slack profile
email (``users.info``) is matched against an active ``User`` node in the
graph. A short-lived per-user JWT access token is then minted with the
shared ``IMBI_AUTH_JWT_SECRET`` — identical to the token the Imbi API
issues at login — so every tool call the bot makes on the user's behalf
is authorized as, and limited to, that user.

The bot serves one Slack workspace, and the workspace belongs to one
Imbi organization: the one whose ``slack_team_id`` is the workspace's
team id. A Slack user resolves only when the Imbi user is a member of
that organization, and everything the bot does for them is in it.

Resolutions (including "no matching Imbi user") are cached with a TTL to
avoid hitting Slack and the graph on every message.

"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import typing

import httpx

from imbi.common import api, graph
from imbi.common.auth import core
from imbi.slackbot import settings

# slack_sdk's AsyncWebClient is only loosely typed (its responses are
# AsyncSlackResponse with Unknown generics), so treat it as Any rather
# than propagate Unknown through every call site.
SlackClient = typing.Any

LOGGER = logging.getLogger(__name__)

# The user, and the slug of the workspace's organization when the user
# is a member of it.
_USER_QUERY = """
MATCH (u:User {{email: {email}}})
OPTIONAL MATCH (u)-[:MEMBER_OF]->(o:Organization {{slack_team_id: {team_id}}})
RETURN u, o.slug AS slug
"""
_WORKSPACE_ORG_QUERY = """
MATCH (o:Organization {{slack_team_id: {team_id}}})
RETURN o.slug AS slug
"""


@dataclasses.dataclass(frozen=True)
class ImbiUser:
    """An Imbi user resolved from a Slack identity."""

    email: str
    display_name: str
    #: The slug of the organization of the Slack workspace.
    org_slug: str
    is_admin: bool = False
    #: The IANA time zone of the Slack user (``users.info`` ``tz``).
    tz: str | None = None


@dataclasses.dataclass
class _CacheEntry:
    """A cached resolution; ``user`` is ``None`` for a known non-user."""

    user: ImbiUser | None
    expires_at: datetime.datetime


# Shared graph instance captured at startup via ``graph.set_on_startup``.
_graph: graph.Graph | None = None
_cache: dict[str, _CacheEntry] = {}
# The team id of the Slack workspace, from ``auth.test`` at startup.
_team_id: str | None = None
# The workspace's organization slug, and when to read it again.
_workspace_org: tuple[str | None, datetime.datetime] | None = None


def set_team_id(team_id: str | None) -> None:
    """Set the team id of the Slack workspace that the bot serves."""
    global _team_id, _workspace_org
    _team_id = team_id
    _workspace_org = None


def set_graph(db: graph.Graph) -> None:
    """Capture the shared graph connection opened by ``graph_lifespan``."""
    global _graph
    _graph = db


def get_graph() -> graph.Graph | None:
    """Return the shared graph connection, or ``None`` before startup."""
    return _graph


async def on_graph_ready(db: graph.Graph) -> None:
    """``graph.set_on_startup`` callback that captures the connection."""
    set_graph(db)


def clear_cache() -> None:
    """Drop all cached resolutions (used by tests and on shutdown)."""
    global _workspace_org
    _cache.clear()
    _workspace_org = None


async def _slack_email(
    slack_client: SlackClient,
    slack_user_id: str,
) -> tuple[str | None, str | None]:
    """Return the Slack user's profile email and time zone, if any."""
    response: typing.Any = await slack_client.users_info(user=slack_user_id)
    user: typing.Any = response['user'] or {}
    profile: typing.Any = user.get('profile') or {}
    email: typing.Any = profile.get('email')
    tz: typing.Any = user.get('tz')
    return (str(email) if email else None, str(tz) if tz else None)


async def _load_imbi_user(email: str) -> ImbiUser | None:
    """Look up an active Imbi ``User`` node by email."""
    if _graph is None:
        raise RuntimeError('Graph connection not initialized')
    records = await _graph.execute(
        _USER_QUERY, {'email': email, 'team_id': _team_id or ''}, ['u', 'slug']
    )
    if not records:
        return None
    raw = graph.parse_agtype(records[0]['u'])
    if not isinstance(raw, dict):
        return None
    data = typing.cast('dict[str, typing.Any]', raw)
    if not data.get('is_active', True):
        return None
    org_slug = graph.parse_agtype(records[0]['slug'])
    if not org_slug:
        LOGGER.info(
            '%s is not a member of the organization of Slack workspace %s',
            email,
            _team_id,
        )
        return None
    return ImbiUser(
        email=email,
        display_name=str(data.get('display_name') or email),
        is_admin=bool(data.get('is_admin', False)),
        org_slug=str(org_slug),
    )


async def workspace_org_slug(
    *, now: datetime.datetime | None = None
) -> str | None:
    """Return the slug of the organization of the Slack workspace, or
    ``None`` when no organization has its team id. The answer is kept
    for the identity cache TTL."""
    global _workspace_org
    now = now or datetime.datetime.now(datetime.UTC)
    if _workspace_org is not None and _workspace_org[1] > now:
        return _workspace_org[0]
    if _graph is None or not _team_id:
        return None
    records = await _graph.execute(
        _WORKSPACE_ORG_QUERY, {'team_id': _team_id}, ['slug']
    )
    slug = str(graph.parse_agtype(records[0]['slug'])) if records else None
    if slug is None:
        LOGGER.warning(
            'Slack workspace %s is not linked to an Imbi organization',
            _team_id,
        )
    ttl = settings.get_slackbot_settings().identity_cache_ttl
    _workspace_org = (slug, now + datetime.timedelta(seconds=ttl))
    return slug


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

    email, tz = await _slack_email(slack_client, slack_user_id)
    user = await _load_imbi_user(email) if email else None
    if user is not None:
        user = dataclasses.replace(user, tz=tz)

    ttl = settings.get_slackbot_settings().identity_cache_ttl
    _cache[slack_user_id] = _CacheEntry(
        user=user,
        expires_at=now + datetime.timedelta(seconds=ttl),
    )
    if user is None:
        LOGGER.info('No Imbi user for Slack user %s', slack_user_id)
    return user


NO_USER_MESSAGE = (
    "I couldn't match your Slack account to an Imbi user in the "
    'organization of this Slack workspace. Imbi matches you by your email '
    'address — ask an Imbi administrator to make sure your account exists, '
    'is active, and is a member of that organization, and that the '
    'organization is linked to this workspace.'
)


def mint_token(user: ImbiUser) -> str:
    """Mint a per-user Imbi API access token.

    The token is signed with the shared ``IMBI_AUTH_JWT_SECRET`` and
    carries the user's email as its subject, exactly as the Imbi API
    does at login. The API loads the user's permissions fresh from the
    graph on each request keyed by this subject. The ``channel`` claim
    makes the API record ``slack`` as the channel of what the user does
    through the bot (H3).

    """
    return core.create_access_token(
        user.email, extra_claims={'channel': 'slack'}
    )


def api_client(user: ImbiUser) -> api.Imbi:
    """Return an imbi-api client that acts as ``user``."""
    return api.Imbi(
        base_url=settings.get_slackbot_settings().api_base_url,
        token=mint_token(user),
        timeout=10,
    )


def response_detail(response: httpx.Response) -> object:
    """Return the ``detail`` of an imbi-api error response, if any."""
    try:
        return response.json().get('detail')
    except ValueError:
        return None
