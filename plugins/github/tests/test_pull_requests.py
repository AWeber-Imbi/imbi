"""Tests for the GitHub pull-request history sync capability."""

import datetime
import typing
import unittest
from unittest import mock

import httpx
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from imbi.common.plugins.base import PluginContext
from imbi.plugins.github import _app_auth, pull_requests
from imbi.plugins.github.plugin import GitHubPlugin, GitHubWebhookActions

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
# ``sync_all_history`` publishes through ``_publish_best_effort`` (defined in
# commits.py), so its ClickHouse call resolves in the commits namespace.
_INSERT_BACKFILL = 'imbi.plugins.github.commits.iggy.publish'
# The webhook action publishes directly through the pull_requests namespace.
_INSERT_WEBHOOK = 'imbi.plugins.github.pull_requests.iggy.publish'
# The stale-row prune ``sync_all_history`` runs after a complete walk.
_DELETE_STALE = 'imbi.plugins.github.pull_requests.clickhouse.command'


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


class PrRecordTestCase(unittest.TestCase):
    def test_merged_from_flag(self) -> None:
        record = pull_requests._pr_record(
            _pr(state='closed', merged=True, merged_at='2026-01-03T00:00:00Z'),
            project_id='p1',
        )
        assert record is not None
        self.assertTrue(record.merged)

    def test_merged_inferred_from_merged_at_on_list_payload(self) -> None:
        # ``GET /pulls`` (the backfill source) has no ``merged`` key.
        pr = _pr(state='closed', merged_at='2026-01-03T00:00:00Z')
        del pr['merged']
        record = pull_requests._pr_record(pr, project_id='p1')
        assert record is not None
        self.assertTrue(record.merged)

    def test_closed_without_merge_is_not_merged(self) -> None:
        pr = _pr(state='closed')
        del pr['merged']
        record = pull_requests._pr_record(pr, project_id='p1')
        assert record is not None
        self.assertFalse(record.merged)


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
        table, _topic, records = insert.await_args.args
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
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # Every test patches the prune so none of them reaches ClickHouse.
        patcher = mock.patch(_DELETE_STALE, new=mock.AsyncMock())
        self.delete: mock.AsyncMock = patcher.start()
        self.addCleanup(patcher.stop)

    def _delete_params(self) -> dict[str, typing.Any]:
        self.delete.assert_awaited_once()
        sql, params = self.delete.await_args.args
        self.assertIn('DELETE FROM pull_requests', sql)
        return typing.cast('dict[str, typing.Any]', params)

    def _excluded(self) -> list[str]:
        params = self._delete_params()
        return [
            pr_id
            for name in sorted(params, key=lambda k: (len(k), k))
            if name.startswith('pr_ids_')
            for pr_id in params[name]
        ]

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
        params = self._delete_params()
        self.assertEqual(params['project_id'], 'proj-1')
        # Only rows on the synced host are deleted; a second pr-sync
        # Integration's rows on another host are left alone.
        self.assertEqual(params['url_prefix'], 'https://github.com/')
        sql = self.delete.await_args.args[0]
        self.assertIn('startsWith(url, {url_prefix:String})', sql)
        self.assertEqual(self._excluded(), ['1', '2'])
        started_at = params['started_at_64']
        self.assertIsInstance(started_at, datetime.datetime)
        self.assertIsNotNone(started_at.tzinfo)

    @respx.mock
    async def test_malformed_pr_keeps_its_row(self) -> None:
        # A PR too malformed to record is still listed by GitHub, so its
        # existing row must not be pruned.
        respx.get(f'{_REPO}/pulls').mock(
            return_value=httpx.Response(
                200,
                json=[_pr(id=1, number=1), _pr(id=2, created_at=None)],
            )
        )
        with mock.patch(_INSERT_BACKFILL, new=mock.AsyncMock()) as insert:
            count = (
                await pull_requests.GitHubPullRequestSync().sync_all_history(
                    ctx=_ctx(), credentials=_CREDS
                )
            )
        self.assertEqual(count, 1)
        insert.assert_awaited_once()
        self.assertEqual(len(insert.await_args.args[2]), 1)
        self.assertEqual(self._excluded(), ['1', '2'])

    @respx.mock
    async def test_empty_repo_prunes_everything(self) -> None:
        respx.get(f'{_REPO}/pulls').mock(
            return_value=httpx.Response(200, json=[])
        )
        with mock.patch(_INSERT_BACKFILL, new=mock.AsyncMock()) as insert:
            count = (
                await pull_requests.GitHubPullRequestSync().sync_all_history(
                    ctx=_ctx(), credentials=_CREDS
                )
            )
        self.assertEqual(count, 0)
        insert.assert_not_awaited()
        sql, _params = self.delete.await_args.args
        self.assertNotIn('NOT IN', sql)
        self.assertEqual(self._excluded(), [])

    @respx.mock
    async def test_page_cap_skips_prune(self) -> None:
        link = f'<{_REPO}/pulls?page=2>; rel="next"'
        respx.get(f'{_REPO}/pulls').mock(
            return_value=httpx.Response(
                200, json=[_pr(id=1, number=1)], headers={'link': link}
            )
        )
        handler = pull_requests.GitHubPullRequestSync()
        with (
            mock.patch.object(pull_requests, '_MAX_HISTORY_PAGES', 2),
            mock.patch(_INSERT_BACKFILL, new=mock.AsyncMock()),
            self.assertLogs(pull_requests.LOGGER, level='WARNING') as cm,
        ):
            await handler.sync_all_history(ctx=_ctx(), credentials=_CREDS)
        self.delete.assert_not_awaited()
        self.assertTrue(any('2-page cap' in x for x in cm.output))

    @respx.mock
    async def test_unfollowable_next_link_skips_prune(self) -> None:
        # A next link with no page param leaves later pages unread, so
        # the listing is incomplete and must not drive a delete.
        link = f'<{_REPO}/pulls?after=abc>; rel="next"'
        respx.get(f'{_REPO}/pulls').mock(
            return_value=httpx.Response(
                200, json=[_pr(id=1, number=1)], headers={'link': link}
            )
        )
        handler = pull_requests.GitHubPullRequestSync()
        with (
            mock.patch(_INSERT_BACKFILL, new=mock.AsyncMock()) as insert,
            self.assertLogs(pull_requests.LOGGER, level='WARNING') as cm,
        ):
            count = await handler.sync_all_history(
                ctx=_ctx(), credentials=_CREDS
            )
        self.assertEqual(count, 1)
        insert.assert_awaited_once()
        self.delete.assert_not_awaited()
        self.assertTrue(any('without a page param' in x for x in cm.output))

    @respx.mock
    async def test_type_slug_fallback_skips_prune(self) -> None:
        # A repo guessed from the project type and slug has no authority,
        # so it still backfills but never deletes stored rows.
        ctx = PluginContext(
            project_id='proj-1',
            project_slug='demo',
            org_slug='octo',
            integration_options=_connection(),
            project_links={},
            project_type_slugs=['octo'],
        )
        respx.get(f'{_REPO}/pulls').mock(
            return_value=httpx.Response(200, json=[_pr(id=1, number=1)])
        )
        with mock.patch(_INSERT_BACKFILL, new=mock.AsyncMock()) as insert:
            count = (
                await pull_requests.GitHubPullRequestSync().sync_all_history(
                    ctx=ctx, credentials=_CREDS
                )
            )
        self.assertEqual(count, 1)
        insert.assert_awaited_once()
        self.delete.assert_not_awaited()

    @respx.mock
    async def test_other_same_host_link_skips_prune(self) -> None:
        # A link to some other repo on the same host resolves a target,
        # but it is not the project's repository link, so no delete.
        ctx = _ctx(
            project_links={'docs': 'https://github.com/octo/demo'},
        )
        respx.get(f'{_REPO}/pulls').mock(
            return_value=httpx.Response(200, json=[])
        )
        with mock.patch(_INSERT_BACKFILL, new=mock.AsyncMock()):
            await pull_requests.GitHubPullRequestSync().sync_all_history(
                ctx=ctx, credentials=_CREDS
            )
        self.delete.assert_not_awaited()

    async def test_large_listing_splits_excluded_ids(self) -> None:
        # Near the 10k page cap, one array would overrun ClickHouse's
        # per-field limit; every ID must still be excluded.
        pr_ids = [str(1_000_000_000 + n) for n in range(9_999)]
        started_at = datetime.datetime.now(datetime.UTC)
        await pull_requests._prune_stale_prs(  # pyright: ignore[reportPrivateUsage]
            'proj-1', 'github.com', started_at, pr_ids
        )
        sql, params = self.delete.await_args.args
        chunks = [v for k, v in params.items() if k.startswith('pr_ids_')]
        self.assertEqual(len(chunks), 10)
        for index, chunk in enumerate(chunks):
            self.assertLessEqual(len(chunk), 1000)
            self.assertIn(
                f'pr_id NOT IN {{pr_ids_{index}:Array(String)}}', sql
            )
        self.assertEqual(self._excluded(), pr_ids)

    @respx.mock
    async def test_prune_failure_is_swallowed(self) -> None:
        self.delete.side_effect = Exception('boom')
        respx.get(f'{_REPO}/pulls').mock(
            return_value=httpx.Response(200, json=[_pr(id=1, number=1)])
        )
        handler = pull_requests.GitHubPullRequestSync()
        with (
            mock.patch(_INSERT_BACKFILL, new=mock.AsyncMock()),
            self.assertLogs(pull_requests.LOGGER, level='ERROR') as cm,
        ):
            count = await handler.sync_all_history(
                ctx=_ctx(), credentials=_CREDS
            )
        self.assertEqual(count, 1)
        self.assertTrue(any('proj-1' in x for x in cm.output))

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
        self.delete.assert_not_awaited()
        self.assertTrue(any('nothing to sync' in x for x in cm.output))

    @respx.mock
    async def test_later_page_404_keeps_partial(self) -> None:
        # A 404 on a later page (not the first) stops pagination but keeps
        # the PRs already collected; the count and warning must reflect the
        # partial result rather than claiming "nothing to sync".
        link = f'<{_REPO}/pulls?page=2>; rel="next"'
        pulls = respx.get(f'{_REPO}/pulls').mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[_pr(id=1, number=1)],
                    headers={'link': link},
                ),
                httpx.Response(404, json={'message': 'Not Found'}),
            ]
        )
        handler = pull_requests.GitHubPullRequestSync()
        with mock.patch(_INSERT_BACKFILL, new=mock.AsyncMock()) as insert:
            with self.assertLogs(pull_requests.LOGGER, level='WARNING') as cm:
                count = await handler.sync_all_history(
                    ctx=_ctx(), credentials=_CREDS
                )
        self.assertEqual(count, 1)
        self.assertEqual(2, pulls.call_count)
        insert.assert_awaited_once()
        self.delete.assert_not_awaited()
        self.assertTrue(any('stopping after 1 PRs' in x for x in cm.output))

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
        self.delete.assert_not_awaited()
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
