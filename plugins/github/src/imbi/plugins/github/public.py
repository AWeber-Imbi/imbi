"""Credential-free reads of a public ``github.com`` repository.

:meth:`GitHubDeployment.public_reader
<imbi.plugins.github.deployment.GitHubDeployment.public_reader>`
returns a :class:`PublicRepository`. The host uses it when no
Integration of the organization can read a repository, for example a
public Claude Code plugin marketplace.
"""

import re
import typing
import urllib.parse

import httpx

from imbi.common.plugins import base

_GITHUB_REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')


class PublicRepository:
    """The :class:`~imbi.common.plugins.base.RepositoryReader` of a public
    ``github.com`` repository. It ignores ``ctx`` and ``credentials``."""

    # ponytail: 60 unauthenticated requests an hour per API pod IP; use
    # an org token if many public marketplaces sync often.
    def __init__(self, owner: str, repo: str) -> None:
        self.base = f'https://api.github.com/repos/{owner}/{repo}'

    @classmethod
    def for_url(cls, url: str) -> PublicRepository | None:
        """Return the reader of a ``github.com`` repository URL, or
        ``None`` for another host or a path that is not a repository."""
        parts = urllib.parse.urlsplit(url)
        path = parts.path.strip('/').removesuffix('.git')
        if parts.hostname != 'github.com' or not _GITHUB_REPO.fullmatch(path):
            return None
        return cls(*path.split('/'))

    async def _get(
        self, path: str, accept: str = 'application/vnd.github+json'
    ) -> httpx.Response:
        # A renamed or moved repository answers 301 to /repositories/{id}.
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True
        ) as client:
            return await client.get(
                f'{self.base}{path}', headers={'Accept': accept}
            )

    async def resolve_committish(
        self, _ctx: object, _credentials: object, ref: str, /
    ) -> base.Ref:
        response = await self._get(f'/commits/{urllib.parse.quote(ref)}')
        response.raise_for_status()
        return base.Ref(name=ref, kind='branch', sha=response.json()['sha'])

    async def list_refs(
        self,
        _ctx: object,
        _credentials: object,
        /,
        kind: typing.Literal['default', 'branch', 'tag', 'all'] = 'all',
    ) -> list[base.Ref]:
        """Return the default branch only, whatever ``kind`` is."""
        del kind
        response = await self._get('')
        response.raise_for_status()
        branch = str(response.json()['default_branch'])
        ref = await self.resolve_committish(None, None, branch)
        return [ref.model_copy(update={'kind': 'default', 'is_default': True})]

    async def get_file(
        self, _ctx: object, _credentials: object, path: str, ref: str, /
    ) -> str | None:
        response = await self._get(
            f'/contents/{urllib.parse.quote(path)}?'
            f'{urllib.parse.urlencode({"ref": ref})}',
            'application/vnd.github.raw+json',
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text
