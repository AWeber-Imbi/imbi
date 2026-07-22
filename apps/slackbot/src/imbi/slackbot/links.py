"""Fetch and cache the Imbi UI URL patterns (``llms.txt``).

The Imbi UI publishes an ``llms.txt`` at its root documenting the route
patterns for building deep links. This module fetches it once at startup
from the in-cluster ``IMBI_INTERNAL_UI_URL`` (falling back to the public
``IMBI_UI_URL``) and caches it; if the UI is unreachable or neither is set
a built-in fallback is used so the system prompt always has URL guidance.

"""

from __future__ import annotations

import logging

import httpx

from imbi.slackbot import settings

LOGGER = logging.getLogger(__name__)

# httpx.InvalidURL is a separate hierarchy from httpx.HTTPError, so a
# malformed IMBI_UI_URL must be caught explicitly to keep startup fail-soft.
_FETCH_ERRORS = (httpx.HTTPError, httpx.InvalidURL)

# Used when the UI's llms.txt cannot be fetched. Keep this roughly in sync
# with imbi-ui's public/llms.txt, which is the canonical source.
FALLBACK_URL_PATTERNS = """\
- `/dashboard`: the user's dashboard.
- `/projects`: the project inventory list.
- `/projects/{project_id}`: a project's detail page.
- `/projects/{project_id}/{tab}`: a project tab (overview, dependencies,
  relationships, documents, configuration, logs, operations-log).
- `/operations-log`: the operations log.
- `/reports` and `/reports/{report_id}`: reports.
- `/settings` and `/settings/{tab}`: the current user's settings.
- `/users/{email}`: a user's profile page.
- `/admin/{section}`: an admin list view (sections: project-types,
  environments, teams, organizations, blueprints, roles, users,
  service-accounts).
- `/admin/{section}/new`: the create form.
- `/admin/{section}/{slug}`: an admin item's detail view.
- `/admin/{section}/{slug}/edit`: an admin item's edit form."""

_url_patterns: str | None = None


async def initialize() -> None:
    """Fetch the UI's ``llms.txt`` and cache its contents."""
    global _url_patterns
    slackbot_settings = settings.get_slackbot_settings()
    base_url = slackbot_settings.llms_base_url
    if not base_url:
        LOGGER.info(
            'No IMBI_INTERNAL_UI_URL or IMBI_UI_URL configured; '
            'using built-in URL patterns'
        )
        _url_patterns = FALLBACK_URL_PATTERNS
        return

    llms_url = f'{base_url.rstrip("/")}/llms.txt'
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(llms_url)
            response.raise_for_status()
        text = response.text.strip()
    except _FETCH_ERRORS:
        LOGGER.warning(
            'Failed to load %s; using built-in URL patterns', llms_url
        )
        _url_patterns = FALLBACK_URL_PATTERNS
        return

    # An empty body or an HTML page (e.g. an SPA 404 fallback) is not
    # usable URL guidance.
    if not text or text.startswith('<'):
        LOGGER.warning(
            '%s did not return markdown; using built-in URL patterns',
            llms_url,
        )
        _url_patterns = FALLBACK_URL_PATTERNS
        return

    _url_patterns = text
    LOGGER.info('Loaded UI URL patterns from %s', llms_url)


def get_url_patterns() -> str:
    """Return the cached UI URL patterns (or the built-in fallback)."""
    return _url_patterns or FALLBACK_URL_PATTERNS
