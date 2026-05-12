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
    links: dict[str, str], host: str
) -> tuple[str, str] | None:
    """Find a project link pointing at ``host`` and parse owner/repo.

    Prefers an explicit ``github-repository`` link key when one is
    present and points at ``host``; otherwise scans the remaining
    same-host links and returns the first usable one.  Returns
    ``None`` when nothing matches.
    """
    target = host.lower()
    preferred = links.get('github-repository')
    if preferred is not None:
        owner_repo = parse_owner_repo(preferred, target)
        if owner_repo is not None:
            return owner_repo
    for key, url in links.items():
        if key == 'github-repository':
            continue
        owner_repo = parse_owner_repo(url, target)
        if owner_repo is not None:
            return owner_repo
    return None


def resolve_owner_repo(
    ctx: PluginContext, host: str, plugin_label: str
) -> tuple[str, str]:
    """Resolve the repo for a plugin call from ``ctx``.

    First tries the project links; falls back to
    ``<project_type_slug>/<project_slug>`` as a convention.  Raises
    :class:`ValueError` when neither path produces a candidate so the
    caller can surface a clear "set the GitHub Repository link"
    message to the operator.
    """
    derived = derive_owner_repo_from_links(ctx.project_links, host)
    if derived is not None:
        return derived
    if ctx.project_type_slugs and ctx.project_slug:
        return ctx.project_type_slugs[0], ctx.project_slug
    raise ValueError(
        f'{plugin_label} could not determine the target repository: '
        "set the project's GitHub Repository link or tag the project "
        'with a ProjectType'
    )
