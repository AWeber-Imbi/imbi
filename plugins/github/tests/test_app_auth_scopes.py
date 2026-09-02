"""Down-scoped installation tokens, and the cache key that keeps them so.

An installation token minted with no ``permissions`` body carries
everything the App installation grants.  Each deployment operation
declares the set it needs instead, and the requested set is part of the
token cache key -- serving a ``contents: read`` token to a caller that
asked for ``contents: write`` would silently undo the whole exercise and
fail at GitHub at the worst possible moment.
"""

import typing
import unittest

import httpx
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from imbi.common.plugins.base import PluginContext
from imbi.common.plugins.errors import PluginInstallationMissing
from imbi.plugins.github import _app_auth, deployment


def _gen_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


_APP_KEY_PEM = _gen_pem()
_FAR_FUTURE = '2099-01-01T00:00:00Z'
_BASE = 'https://api.github.com'
_TOKENS_URL = f'{_BASE}/app/installations/42/access_tokens'
_INSTALL_URL = f'{_BASE}/repos/octo/demo/installation'


def _ctx() -> PluginContext:
    return PluginContext(
        project_id='p1',
        project_slug='demo',
        org_slug='octo',
        integration_slug='github-deployment-prod',
        project_links={'github-repository': 'https://github.com/octo/demo'},
        integration_options={'flavor': 'github'},
    )


def _app_creds(*, installation_id: str | None = '42') -> dict[str, str]:
    creds = {'app_id': '971', 'private_key': _APP_KEY_PEM}
    if installation_id is not None:
        creds['installation_id'] = installation_id
    return creds


def _mock_token(token: str = 'ghs_minted') -> respx.Route:
    return respx.post(_TOKENS_URL).mock(
        return_value=httpx.Response(
            201, json={'token': token, 'expires_at': _FAR_FUTURE}
        )
    )


class FreezeScopeTestCase(unittest.TestCase):
    def test_key_order_does_not_split_the_cache(self) -> None:
        a = _app_auth.freeze_scope({'contents': 'read', 'checks': 'read'})
        b = _app_auth.freeze_scope({'checks': 'read', 'contents': 'read'})
        self.assertEqual(a, b)

    def test_none_is_distinct_from_every_declared_scope(self) -> None:
        """The App's full grant is not interchangeable with a subset."""
        self.assertIsNone(_app_auth.freeze_scope(None))
        self.assertNotEqual(
            _app_auth.freeze_scope(None), _app_auth.freeze_scope({})
        )

    def test_read_and_write_of_one_permission_differ(self) -> None:
        self.assertNotEqual(
            _app_auth.freeze_scope({'contents': 'read'}),
            _app_auth.freeze_scope({'contents': 'write'}),
        )


class ScopedMintTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _app_auth.reset_cache()

    def tearDown(self) -> None:
        _app_auth.reset_cache()

    async def _token(
        self, scope: dict[str, str] | None, **kwargs: typing.Any
    ) -> str:
        return await _app_auth.installation_token(
            base=_BASE,
            app_id='971',
            private_key=_APP_KEY_PEM,
            installation_id='42',
            owner='octo',
            repo='demo',
            scope=scope,
            **kwargs,
        )

    @respx.mock
    async def test_requested_permissions_reach_the_mint_body(self) -> None:
        route = _mock_token()
        await self._token({'contents': 'read'})
        self.assertEqual(1, route.call_count)
        request = route.calls[0].request
        self.assertEqual(
            {'permissions': {'contents': 'read'}},
            httpx.Response(200, content=request.content).json(),
        )

    @respx.mock
    async def test_no_scope_sends_no_body(self) -> None:
        """The pre-scoping behaviour: whatever the installation grants."""
        route = _mock_token()
        await self._token(None)
        self.assertEqual(b'', route.calls[0].request.content)

    @respx.mock
    async def test_same_scope_is_served_from_cache(self) -> None:
        route = _mock_token()
        first = await self._token({'contents': 'read'})
        second = await self._token({'contents': 'read'})
        self.assertEqual(first, second)
        self.assertEqual(1, route.call_count)

    @respx.mock
    async def test_a_read_token_is_never_served_to_a_write_request(
        self,
    ) -> None:
        """The correctness requirement behind the scoped cache key."""
        route = respx.post(_TOKENS_URL).mock(
            side_effect=[
                httpx.Response(
                    201,
                    json={'token': 'ghs_read', 'expires_at': _FAR_FUTURE},
                ),
                httpx.Response(
                    201,
                    json={'token': 'ghs_write', 'expires_at': _FAR_FUTURE},
                ),
            ]
        )
        read = await self._token({'contents': 'read'})
        write = await self._token({'contents': 'write'})
        self.assertEqual('ghs_read', read)
        self.assertEqual('ghs_write', write)
        self.assertEqual(2, route.call_count)


class NotInstalledTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _app_auth.reset_cache()

    def tearDown(self) -> None:
        _app_auth.reset_cache()

    async def _discover(self, **kwargs: typing.Any) -> str:
        return await _app_auth.installation_token(
            base=_BASE,
            app_id='971',
            private_key=_APP_KEY_PEM,
            installation_id=None,
            owner='octo',
            repo='demo',
            **kwargs,
        )

    @respx.mock
    async def test_read_paths_pay_the_404_once(self) -> None:
        route = respx.get(_INSTALL_URL).mock(
            return_value=httpx.Response(404, json={'message': 'nope'})
        )
        for _ in range(3):
            with self.assertRaises(_app_auth.AppNotInstalledError):
                await self._discover()
        self.assertEqual(1, route.call_count)

    @respx.mock
    async def test_mutating_paths_bypass_the_negative_cache(self) -> None:
        """An App installed mid-incident must not stay invisible.

        The negative cache exists so a sweep does not re-pay the 404 on
        every repository it touches.  A rollback cannot afford it: the
        answer it caches is exactly the one an operator is in the middle
        of changing.
        """
        route = respx.get(_INSTALL_URL).mock(
            return_value=httpx.Response(404, json={'message': 'nope'})
        )
        with self.assertRaises(_app_auth.AppNotInstalledError):
            await self._discover()
        with self.assertRaises(_app_auth.AppNotInstalledError):
            await self._discover(cache_misses=False)
        self.assertEqual(2, route.call_count)

    async def test_it_is_the_shared_terminal_error(self) -> None:
        """So the host maps it to 403 without importing the plugin."""
        self.assertTrue(
            issubclass(
                _app_auth.AppNotInstalledError, PluginInstallationMissing
            )
        )

    @respx.mock
    async def test_the_error_names_the_repository(self) -> None:
        respx.get(_INSTALL_URL).mock(
            return_value=httpx.Response(404, json={'message': 'nope'})
        )
        with self.assertRaises(_app_auth.AppNotInstalledError) as caught:
            await self._discover()
        self.assertEqual('octo/demo', caught.exception.owner_repo)


class DeploymentScopeDeclarationTestCase(unittest.IsolatedAsyncioTestCase):
    """The handler asks for what the operation needs, and no more."""

    def setUp(self) -> None:
        _app_auth.reset_cache()

    def tearDown(self) -> None:
        _app_auth.reset_cache()

    @respx.mock
    async def test_compare_mints_for_contents_read(self) -> None:
        token_route = _mock_token()
        base, head = 'a' * 40, 'b' * 40
        respx.get(f'{_BASE}/repos/octo/demo/compare/{base}...{head}').mock(
            return_value=httpx.Response(
                200, json={'ahead_by': 1, 'behind_by': 0, 'commits': []}
            )
        )
        await deployment.GitHubDeployment().compare(
            _ctx(), _app_creds(), base=base, head=head
        )
        body = httpx.Response(
            200, content=token_route.calls[0].request.content
        ).json()
        self.assertEqual({'permissions': {'contents': 'read'}}, body)

    @respx.mock
    async def test_create_tag_mints_for_contents_write(self) -> None:
        token_route = _mock_token()
        respx.post(f'{_BASE}/repos/octo/demo/git/tags').mock(
            return_value=httpx.Response(201, json={'sha': 'b' * 40})
        )
        respx.post(f'{_BASE}/repos/octo/demo/git/refs').mock(
            return_value=httpx.Response(
                201, json={'ref': 'refs/tags/v1', 'object': {'sha': 'b' * 40}}
            )
        )
        await deployment.GitHubDeployment().create_tag(
            _ctx(), _app_creds(), sha='a' * 40, tag='v1', message='m'
        )
        body = httpx.Response(
            200, content=token_route.calls[0].request.content
        ).json()
        self.assertEqual({'permissions': {'contents': 'write'}}, body)

    @respx.mock
    async def test_trigger_deployment_mints_for_deployments_write(
        self,
    ) -> None:
        """Not ``actions: write``: Imbi creates a Deployment object.

        The repo's ``on: deployment`` workflow is what GitHub dispatches
        from it, so Imbi never needs authority over Actions here.
        """
        token_route = _mock_token()
        respx.post(f'{_BASE}/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(201, json={'id': 7})
        )
        ctx = _ctx().model_copy(update={'environment': 'staging'})
        await deployment.GitHubDeployment().trigger_deployment(
            ctx, _app_creds(), ref_or_sha='v1'
        )
        body = httpx.Response(
            200, content=token_route.calls[0].request.content
        ).json()
        self.assertEqual({'permissions': {'deployments': 'write'}}, body)

    @respx.mock
    async def test_a_pat_is_unaffected_by_the_declared_scope(self) -> None:
        """Nothing here can narrow a token an operator already issued."""
        mint = _mock_token()
        base, head = 'a' * 40, 'b' * 40
        respx.get(f'{_BASE}/repos/octo/demo/compare/{base}...{head}').mock(
            return_value=httpx.Response(
                200, json={'ahead_by': 0, 'behind_by': 0, 'commits': []}
            )
        )
        await deployment.GitHubDeployment().compare(
            _ctx(), {'access_token': 'gho_pat'}, base=base, head=head
        )
        self.assertEqual(0, mint.call_count)


class CredentialNoteTestCase(unittest.IsolatedAsyncioTestCase):
    """What the host records as the credential an action ran on."""

    def setUp(self) -> None:
        _app_auth.reset_cache()

    def tearDown(self) -> None:
        _app_auth.reset_cache()

    @respx.mock
    async def test_app_credentials_name_the_installation(self) -> None:
        _mock_token()
        base, head = 'a' * 40, 'b' * 40
        respx.get(f'{_BASE}/repos/octo/demo/compare/{base}...{head}').mock(
            return_value=httpx.Response(
                200, json={'ahead_by': 0, 'behind_by': 0, 'commits': []}
            )
        )
        ctx = _ctx()
        await deployment.GitHubDeployment().compare(
            ctx, _app_creds(), base=base, head=head
        )
        self.assertEqual('github-app installation 42', ctx.credential_note)

    @respx.mock
    async def test_a_pat_records_nothing(self) -> None:
        """The principal already describes an actor's own token."""
        base, head = 'a' * 40, 'b' * 40
        respx.get(f'{_BASE}/repos/octo/demo/compare/{base}...{head}').mock(
            return_value=httpx.Response(
                200, json={'ahead_by': 0, 'behind_by': 0, 'commits': []}
            )
        )
        ctx = _ctx()
        await deployment.GitHubDeployment().compare(
            ctx, {'access_token': 'gho_pat'}, base=base, head=head
        )
        self.assertIsNone(ctx.credential_note)
