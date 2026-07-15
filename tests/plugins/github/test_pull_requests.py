"""Tests for the GitHub pull-request history sync capability."""

import typing
import unittest
from unittest import mock

import httpx
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from imbi_common.plugins.base import PluginContext

from imbi_plugin_github import _app_auth, pull_requests
from imbi_plugin_github.plugin import GitHubPlugin, GitHubWebhookActions

_CREDS = {'access_token': 'gho_test'}
_REPO = 'https://api.github.com/repos/octo/demo'


def _gen_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


# Generated once for the module; signing only needs a valid RSA key.
_APP_KEY_PEM = _gen_pem()
# ``sync_all_history`` inserts through ``_insert_best_effort`` (defined in
# commits.py), so its ClickHouse call resolves in the commits namespace.
_INSERT_BACKFILL = 'imbi_plugin_github.commits.clickhouse.insert'
# The webhook action inserts directly through the pull_requests namespace.
_INSERT_WEBHOOK = 'imbi_plugin_github.pull_requests.clickhouse.insert'


def _connection(
    flavor: str = 'github', host: str | None = None
) -> dict[str, typing.Any]:
    options: dict[str, typing.Any] = {'flavor': flavor}
    if host is not None:
        options['host'] = host
    return options


def _ctx(
    *,
    connection: dict[str, typing.Any] | None = None,
    project_links: dict[str, str] | None = None,
) -> PluginContext:
    return PluginContext(
        project_id='proj-1',
        project_slug='proj',
        org_slug='octo',
        integration_options=connection
        if connection is not None
        else _connection(),
        project_links=(
            project_links
            if project_links is not None
            else {'github-repository': 'https://github.com/octo/demo'}
        ),
    )


def _event(body: dict[str, typing.Any]) -> dict[str, typing.Any]:
    return {
        'type': '',
        'integration': '',
        'attributed_to': '',
        'metadata': {'headers': {}},
        'payload': body,
    }


def _pr(**overrides: typing.Any) -> dict[str, typing.Any]:
    pr: dict[str, typing.Any] = {
        'id': 555,
        'number': 7,
        'title': 'Add feature',
        'html_url': 'https://github.com/octo/demo/pull/7',
        'state': 'open',
        'user': {'login': 'octocat'},
        'draft': False,
        'merged': False,
        'created_at': '2026-01-01T00:00:00Z',
        'updated_at': '2026-01-02T00:00:00Z',
        'merged_at': None,
    }
    pr.update(overrides)
    return pr


class ManifestTestCase(unittest.TestCase):
    def test_pr_sync_capability(self) -> None:
        cap = GitHubPlugin.manifest.get_capability('pr-sync')
        assert cap is not None
        self.assertIs(cap.handler, pull_requests.GitHubPullRequestSync)

    def test_action_catalogued(self) -> None:
        names = [d.name for d in GitHubWebhookActions.actions()]
        self.assertIn('sync_pull_requests', names)


class SyncPullRequestsActionTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_opened_records_one_row(self) -> None:
        with mock.patch(_INSERT_WEBHOOK, new=mock.AsyncMock()) as insert:
            await pull_requests.sync_pull_requests(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=pull_requests.SyncPRsConfig(),
                event=_event({'action': 'opened', 'pull_request': _pr()}),
            )
        insert.assert_awaited_once()
        assert insert.await_args is not None
        table, records = insert.await_args.args
        self.assertEqual(table, 'pull_requests')
        self.assertEqual(records[0].pr_number, 7)
        self.assertEqual(records[0].author, 'octocat')

    async def test_ignored_action_no_insert(self) -> None:
        with mock.patch(_INSERT_WEBHOOK, new=mock.AsyncMock()) as insert:
            await pull_requests.sync_pull_requests(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=pull_requests.SyncPRsConfig(),
                event=_event({'action': 'labeled', 'pull_request': _pr()}),
            )
        insert.assert_not_awaited()

    async def test_malformed_pr_no_insert(self) -> None:
        with mock.patch(_INSERT_WEBHOOK, new=mock.AsyncMock()) as insert:
            await pull_requests.sync_pull_requests(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=pull_requests.SyncPRsConfig(),
                event=_event(
                    {'action': 'opened', 'pull_request': {'number': 7}}
                ),
            )
        insert.assert_not_awaited()


class SyncAllHistoryTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_records_full_history(self) -> None:
        respx.get(f'{_REPO}/pulls').mock(
            return_value=httpx.Response(
                200, json=[_pr(id=1, number=1), _pr(id=2, number=2)]
            )
        )
        with mock.patch(_INSERT_BACKFILL, new=mock.AsyncMock()) as insert:
            count = (
                await pull_requests.GitHubPullRequestSync().sync_all_history(
                    ctx=_ctx(), credentials=_CREDS
                )
            )
        self.assertEqual(count, 2)
        insert.assert_awaited_once()

    async def test_raises_without_host(self) -> None:
        with self.assertRaises(ValueError):
            await pull_requests.GitHubPullRequestSync().sync_all_history(
                ctx=_ctx(connection={}), credentials=_CREDS
            )

    @respx.mock
    async def test_repo_gone_404_skips(self) -> None:
        # IMBI-36: a renamed/removed repo returns 404 on the pulls list;
        # the backfill must skip cleanly (return 0, log a warning) so the
        # worker doesn't emit a Sentry error.
        pulls = respx.get(f'{_REPO}/pulls').mock(
            return_value=httpx.Response(404, json={'message': 'Not Found'})
        )
        handler = pull_requests.GitHubPullRequestSync()
        with mock.patch(_INSERT_BACKFILL, new=mock.AsyncMock()) as insert:
            with self.assertLogs(pull_requests.LOGGER, level='WARNING') as cm:
                count = await handler.sync_all_history(
                    ctx=_ctx(), credentials=_CREDS
                )
        self.assertEqual(count, 0)
        self.assertEqual(1, pulls.call_count)
        insert.assert_not_awaited()
        self.assertTrue(any('nothing to sync' in x for x in cm.output))

    @respx.mock
    async def test_pulls_non_404_propagates(self) -> None:
        # A non-404 failure on the pulls list is a real error and must
        # still propagate rather than be swallowed as "repo gone".
        respx.get(f'{_REPO}/pulls').mock(
            return_value=httpx.Response(500, json={'message': 'boom'})
        )
        with mock.patch(_INSERT_BACKFILL, new=mock.AsyncMock()):
            with self.assertRaises(httpx.HTTPStatusError):
                await pull_requests.GitHubPullRequestSync().sync_all_history(
                    ctx=_ctx(), credentials=_CREDS
                )

    @respx.mock
    async def test_app_not_installed_skips(self) -> None:
        # IMBI-37: the shared GitHub App discovery 404s when the App is
        # not installed for the repo; the backfill must skip cleanly.
        _app_auth.reset_cache()
        self.addCleanup(_app_auth.reset_cache)
        discovery = respx.get(f'{_REPO}/installation').mock(
            return_value=httpx.Response(404, json={'message': 'Not Found'})
        )
        creds = {'app_id': '971', 'private_key': _APP_KEY_PEM}
        handler = pull_requests.GitHubPullRequestSync()
        with mock.patch(_INSERT_BACKFILL, new=mock.AsyncMock()) as insert:
            with self.assertLogs(pull_requests.LOGGER, level='WARNING') as cm:
                count = await handler.sync_all_history(
                    ctx=_ctx(), credentials=creds
                )
        self.assertEqual(count, 0)
        self.assertEqual(1, discovery.call_count)
        insert.assert_not_awaited()
        self.assertTrue(any('skipping backfill' in x for x in cm.output))


class CheckAvailableTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_available_with_host_and_repo(self) -> None:
        available = (
            await pull_requests.GitHubPullRequestSync().check_available(
                ctx=_ctx(), credentials=_CREDS
            )
        )
        self.assertTrue(available)

    async def test_unavailable_without_host(self) -> None:
        available = (
            await pull_requests.GitHubPullRequestSync().check_available(
                ctx=_ctx(connection={}), credentials=_CREDS
            )
        )
        self.assertFalse(available)

    async def test_unavailable_without_repo(self) -> None:
        available = (
            await pull_requests.GitHubPullRequestSync().check_available(
                ctx=_ctx(project_links={}), credentials=_CREDS
            )
        )
        self.assertFalse(available)


if __name__ == '__main__':
    unittest.main()
