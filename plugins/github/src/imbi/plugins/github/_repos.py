"""Shared owner/repo resolution for the GitHub plugin family.

Identity, deployment, and lifecycle plugins all derive ``(owner, repo)``
from a project's external links (preferring the ``github-repository``
link key) plus, as a final fallback, the project's slug and type slug.
Centralising the logic here keeps the rules — reserved GitHub URL
prefixes, ``.git`` stripping, host case-folding — in one place so every
plugin agrees on what counts as a "real" repo URL.
"""

from __future__ import annotations

import urllib.parse

from imbi_common.plugins.base import PluginContext

# Reserved GitHub URL prefixes that share the host with repository URLs
# but never point at a real ``<owner>/<repo>`` pair.  Any link whose
# first path segment matches one of these is skipped during owner/repo
# derivation so e.g. ``github.com/orgs/<org>`` or a marketplace link
# can't silently bind a plugin to the wrong target.
_RESERVED_LINK_PREFIXES = frozenset(
    {
        'orgs',
        'marketplace',
        'settings',
        'enterprises',
        'features',
        'pricing',
        'about',
        'login',
        'logout',
        'signup',
        'sponsors',
        'topics',
        'collections',
        'trending',
        'codespaces',
        'notifications',
        'issues',
        'pulls',
        'search',
        'stars',
        'explore',
    }
)


def parse_owner_repo(url: str, target_host: str) -> tuple[str, str] | None:
    """Extract ``(owner, repo)`` from ``url`` when it is a repo URL on
    ``target_host``.  Returns ``None`` for other hosts, short paths,
    or reserved-prefix paths like ``/orgs/<org>``.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    if (parsed.hostname or '').lower() != target_host:
        return None
    parts = [p for p in parsed.path.split('/') if p]
    if len(parts) < 2:
        return None
    if parts[0].lower() in _RESERVED_LINK_PREFIXES:
        return None
    return parts[0], parts[1].removesuffix('.git')


def derive_owner_repo_from_links(
    links: dict[str, str],
    host: str,
    *,
    preferred_key: str | None = None,
) -> tuple[str, str] | None:
    """Find a project link pointing at ``host`` and parse owner/repo.

    Prefers the dashboard link keyed by ``preferred_key`` (the bound
    third-party-service slug) when present and pointing at ``host``,
    then the legacy ``github-repository`` link key, then scans the
    remaining same-host links and returns the first usable one.
    Returns ``None`` when nothing matches.
    """
    target = host.lower()
    tried: set[str] = set()
    for key in (preferred_key, 'github-repository'):
        if not key or key in tried:
            continue
        tried.add(key)
        url = links.get(key)
        if url is not None:
            owner_repo = parse_owner_repo(url, target)
            if owner_repo is not None:
                return owner_repo
    for key, url in links.items():
        if key in tried:
            continue
        owner_repo = parse_owner_repo(url, target)
        if owner_repo is not None:
            return owner_repo
    return None


def resolve_owner_repo(
    ctx: PluginContext,
    host: str,
    plugin_label: str,
    *,
    prefer_previous_slug: bool = False,
) -> tuple[str, str]:
    """Resolve the repo for a plugin call from ``ctx``.

    First tries the project links; falls back to
    ``<project_type_slug>/<project_slug>`` as a convention.  Raises
    :class:`ValueError` when neither path produces a candidate so the
    caller can surface a clear "set the GitHub Repository link"
    message to the operator.

    ``prefer_previous_slug`` makes the slug fallback prefer
    ``ctx.previous_project_slug`` (when set) over ``ctx.project_slug``
    so callers reacting to a slug rename (e.g. ``on_project_updated``)
    can still locate the pre-rename repo on GitHub.
    """
    derived = derive_owner_repo_from_links(
        ctx.project_links,
        host,
        preferred_key=ctx.third_party_service_slug,
    )
    if derived is not None:
        return derived
    if ctx.project_type_slugs:
        slug = ctx.project_slug
        if prefer_previous_slug and ctx.previous_project_slug:
            slug = ctx.previous_project_slug
        if slug:
            return ctx.project_type_slugs[0], slug
    raise ValueError(
        f'{plugin_label} could not determine the target repository: '
        "set the project's GitHub Repository link or tag the project "
        'with a ProjectType'
    )
