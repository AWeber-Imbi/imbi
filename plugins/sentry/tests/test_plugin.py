"""Tests for the Sentry plugin: manifest, lifecycle, doctor, action."""

import os
import unittest
from unittest import mock

import httpx
import respx

import imbi.plugins.sentry
from imbi.common.plugins.base import PluginContext, ServiceConnection
from imbi.plugins.sentry import actions, plugin
from imbi.plugins.sentry.doctor import SentryDoctor
from imbi.plugins.sentry.lifecycle import SentryLifecycle

_API = 'https://sentry.io/api/0'
_PROJECT_URL = f'{_API}/projects/acme/demo/'
_ISSUES_URL = f'{_API}/organizations/acme/issues/'
_CREATE_URL = f'{_API}/teams/acme/sentry-platform/projects/'
_PROJECT = {
    'id': '42',
    'slug': 'demo',
    'name': 'Demo',
    'teams': [{'slug': 'sentry-platform'}],
}
_TEAMS_URL = f'{_PROJECT_URL}teams'
_CREDS = {'auth_token': 't'}
_LINK = (
    'https://sentry.io/organizations/acme/issues/?project=42&statsPeriod=14d'
)
_FACTS = {'sentry_open_issues': 'is:unresolved', 'sentry_new': 'is:new'}


def _ctx(
    *,
    connected: bool = True,
    facts: dict[str, object] | None = None,
    links: dict[str, str] | None = None,
) -> PluginContext:
    return PluginContext(
        project_id='p1',
        project_slug='demo',
        project_name='Demo',
        org_slug='org',
        team_slug='platform',
        integration_slug='sentry',
        integration_options={
            'organization': 'acme',
            'team_mapping': {'platform': 'sentry-platform'},
            'issue_count_facts': _FACTS,
        },
        service_connections=[
            ServiceConnection(
                integration_slug='sentry',
                identifier='demo',
                canonical_url=_PROJECT_URL,
                verified_identifier='demo',
            )
        ]
        if connected
        else [],
        project_links=links if links is not None else {'sentry': _LINK},
        project_facts=facts or {},
    )


class _RespxCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        respx.mock.start()
        self.addCleanup(respx.mock.stop, quiet=True)

    def _issues(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        self.assertEqual('42', params['project'])
        self.assertEqual('14d', params['statsPeriod'])
        hits = {'is:unresolved': '7', 'is:new': '2'}[params['query']]
        return httpx.Response(200, json=[], headers={'X-Hits': hits})


class ManifestTests(unittest.TestCase):
    def test_capabilities(self) -> None:
        manifest = imbi.plugins.sentry.PLUGIN.manifest
        self.assertEqual('sentry', manifest.slug)
        for kind in ('lifecycle', 'webhook-actions', 'analysis'):
            self.assertIsNotNone(manifest.get_capability(kind), kind)
        descriptor = plugin.SentryWebhookActions.actions()[0]
        self.assertIs(actions.sync_issue_counts, descriptor.callable)
        signature = plugin.SentryWebhookActions.signature()
        self.assertEqual('sentry-hook-signature', signature.header)
        self.assertEqual('', signature.prefix)


class LifecycleTests(_RespxCase):
    async def test_creates_missing_project_in_mapped_team(self) -> None:
        respx.get(_PROJECT_URL).respond(404)
        create = respx.post(_CREATE_URL).respond(201, json=_PROJECT)
        ctx = _ctx(connected=False)
        result = await SentryLifecycle().on_project_created(ctx, _CREDS)
        self.assertEqual('ok', result.status)
        self.assertIn(b'"slug":"demo"', create.calls.last.request.content)
        assert ctx.service_writeback is not None
        self.assertEqual('demo', ctx.service_writeback.identifier)
        self.assertEqual(
            {'sentry': _LINK}, ctx.service_writeback.dashboard_links
        )

    async def test_links_existing_project(self) -> None:
        respx.get(_PROJECT_URL).respond(200, json=_PROJECT)
        ctx = _ctx(connected=False)
        result = await SentryLifecycle().on_project_created(ctx, _CREDS)
        self.assertEqual('ok', result.status)
        self.assertIn('Linked existing', result.message or '')

    async def test_unknown_team_fails(self) -> None:
        respx.get(_PROJECT_URL).respond(404)
        respx.post(_CREATE_URL).respond(404)
        result = await SentryLifecycle().on_project_created(_ctx(), _CREDS)
        self.assertEqual('failed', result.status)
        self.assertIn('team_mapping', result.message or '')

    async def test_missing_organization_fails(self) -> None:
        ctx = _ctx().model_copy(update={'integration_options': {}})
        result = await SentryLifecycle().on_project_created(ctx, _CREDS)
        self.assertEqual('failed', result.status)


class DoctorTests(_RespxCase):
    async def test_all_pass(self) -> None:
        respx.get(_PROJECT_URL).respond(200, json=_PROJECT)
        respx.get(_ISSUES_URL).mock(side_effect=self._issues)
        ctx = _ctx(facts={'sentry_open_issues': 7, 'sentry_new': 2})
        items = await SentryDoctor().analyze(ctx, _CREDS)
        self.assertEqual(['pass'] * 4, [i.status for i in items])

    async def test_stale_fact_offers_sweepable_sync(self) -> None:
        respx.get(_PROJECT_URL).respond(200, json=_PROJECT)
        respx.get(_ISSUES_URL).mock(side_effect=self._issues)
        ctx = _ctx(facts={'sentry_open_issues': 3, 'sentry_new': 2})
        items = {i.slug: i for i in await SentryDoctor().analyze(ctx, _CREDS)}
        stale = items['issue-count:sentry_open_issues']
        self.assertEqual('warn', stale.status)
        assert stale.remediation is not None
        self.assertTrue(stale.remediation.sweepable)

        result = await SentryDoctor().remediate(
            ctx, _CREDS, stale.remediation.id
        )
        self.assertEqual('fixed', result.status)
        self.assertEqual(
            {'sentry_open_issues': 7, 'sentry_new': 2}, ctx.fact_writeback
        )

    async def test_sync_noop_when_current(self) -> None:
        respx.get(_PROJECT_URL).respond(200, json=_PROJECT)
        respx.get(_ISSUES_URL).mock(side_effect=self._issues)
        ctx = _ctx(facts={'sentry_open_issues': 7, 'sentry_new': 2})
        result = await SentryDoctor().remediate(
            ctx, _CREDS, 'sync-issue-counts'
        )
        self.assertEqual('noop', result.status)
        self.assertIsNone(ctx.fact_writeback)

    async def test_missing_project_offers_create(self) -> None:
        respx.get(_PROJECT_URL).respond(404)
        items = await SentryDoctor().analyze(_ctx(), _CREDS)
        self.assertEqual('fail', items[0].status)
        assert items[0].remediation is not None
        self.assertEqual('create-project', items[0].remediation.id)

        respx.post(_CREATE_URL).respond(201, json=_PROJECT)
        ctx = _ctx()
        result = await SentryDoctor().remediate(ctx, _CREDS, 'create-project')
        self.assertEqual('fixed', result.status)
        self.assertIsNotNone(ctx.service_writeback)

    async def test_drifted_link_offers_link_repair(self) -> None:
        respx.get(_PROJECT_URL).respond(200, json=_PROJECT)
        respx.get(_ISSUES_URL).mock(side_effect=self._issues)
        ctx = _ctx(links={})
        items = await SentryDoctor().analyze(ctx, _CREDS)
        self.assertEqual('fail', items[0].status)
        result = await SentryDoctor().remediate(ctx, _CREDS, 'link-project')
        self.assertEqual('fixed', result.status)

    async def test_link_repair_never_creates(self) -> None:
        respx.get(_PROJECT_URL).respond(404)
        result = await SentryDoctor().remediate(_ctx(), _CREDS, 'link-project')
        self.assertEqual('failed', result.status)

    async def test_extra_team_is_removed(self) -> None:
        project = {
            **_PROJECT,
            'teams': [{'slug': 'old'}, {'slug': 'sentry-platform'}],
        }
        respx.get(_PROJECT_URL).respond(200, json=project)
        respx.get(_ISSUES_URL).mock(side_effect=self._issues)
        items = {
            i.slug: i for i in await SentryDoctor().analyze(_ctx(), _CREDS)
        }
        team = items['sentry-team']
        self.assertEqual('fail', team.status)
        assert team.remediation is not None
        self.assertTrue(team.remediation.destructive)
        self.assertFalse(team.remediation.sweepable)

        remove = respx.delete(f'{_TEAMS_URL}/old/').respond(204)
        result = await SentryDoctor().remediate(_ctx(), _CREDS, 'set-team')
        self.assertEqual('fixed', result.status)
        self.assertIn('removed old', result.message)
        self.assertTrue(remove.called)

    async def test_unowned_project_gets_mapped_team(self) -> None:
        respx.get(_PROJECT_URL).respond(200, json={**_PROJECT, 'teams': []})
        add = respx.post(f'{_TEAMS_URL}/sentry-platform/').respond(201)
        result = await SentryDoctor().remediate(_ctx(), _CREDS, 'set-team')
        self.assertEqual('fixed', result.status)
        self.assertTrue(add.called)

    async def test_foreign_project_is_never_claimed(self) -> None:
        project = {**_PROJECT, 'teams': [{'slug': 'other'}]}
        respx.get(_PROJECT_URL).respond(200, json=project)
        respx.get(_ISSUES_URL).mock(side_effect=self._issues)
        items = {
            i.slug: i for i in await SentryDoctor().analyze(_ctx(), _CREDS)
        }
        self.assertIsNone(items['sentry-team'].remediation)
        result = await SentryDoctor().remediate(_ctx(), _CREDS, 'set-team')
        self.assertEqual('failed', result.status)
        linked = await SentryLifecycle().on_project_created(
            _ctx(connected=False), _CREDS
        )
        self.assertEqual('failed', linked.status)
        self.assertFalse(
            any(c.request.method in ('POST', 'DELETE') for c in respx.calls)
        )

    async def test_hand_set_identifier_gets_no_team_fix(self) -> None:
        ctx = _ctx()
        ctx.service_connections[0].verified_identifier = None
        project = {**_PROJECT, 'teams': [{'slug': 'other'}]}
        respx.get(_PROJECT_URL).respond(200, json=project)
        respx.get(_ISSUES_URL).mock(side_effect=self._issues)
        items = {i.slug: i for i in await SentryDoctor().analyze(ctx, _CREDS)}
        self.assertEqual('fail', items['sentry-team'].status)
        self.assertIsNone(items['sentry-team'].remediation)
        result = await SentryDoctor().remediate(ctx, _CREDS, 'set-team')
        self.assertEqual('failed', result.status)
        self.assertFalse(
            any(c.request.method == 'DELETE' for c in respx.calls)
        )

    async def test_invalid_slug_makes_no_request(self) -> None:
        ctx = _ctx()
        ctx.service_connections[0].identifier = '../x'
        items = await SentryDoctor().analyze(ctx, _CREDS)
        self.assertEqual('warn', items[0].status)
        self.assertIn('not a valid Sentry slug', items[0].description)
        self.assertEqual(0, len(respx.calls))

    async def test_set_team_noop_when_correct(self) -> None:
        respx.get(_PROJECT_URL).respond(200, json=_PROJECT)
        result = await SentryDoctor().remediate(_ctx(), _CREDS, 'set-team')
        self.assertEqual('noop', result.status)

    async def test_set_team_unknown_team_fails(self) -> None:
        respx.get(_PROJECT_URL).respond(200, json={**_PROJECT, 'teams': []})
        respx.post(f'{_TEAMS_URL}/sentry-platform/').respond(404)
        result = await SentryDoctor().remediate(_ctx(), _CREDS, 'set-team')
        self.assertEqual('failed', result.status)
        self.assertIn('team_mapping', result.message)

    async def test_unreachable_sentry_warns(self) -> None:
        respx.get(_PROJECT_URL).mock(side_effect=httpx.ConnectError('down'))
        items = await SentryDoctor().analyze(_ctx(), _CREDS)
        self.assertEqual(['warn'], [i.status for i in items])

    async def test_missing_x_hits_warns(self) -> None:
        respx.get(_PROJECT_URL).respond(200, json=_PROJECT)
        respx.get(_ISSUES_URL).respond(200, json=[])
        items = await SentryDoctor().analyze(_ctx(), _CREDS)
        self.assertEqual('issue-counts', items[-1].slug)
        self.assertEqual('warn', items[-1].status)


class ActionTests(_RespxCase):
    async def test_patches_counts(self) -> None:
        respx.get(_PROJECT_URL).respond(200, json=_PROJECT)
        respx.get(_ISSUES_URL).mock(side_effect=self._issues)
        patch = respx.patch(
            'http://imbi-api/api/organizations/org/projects/p1'
        ).respond(200, json={})
        env = {
            'IMBI_INTERNAL_API_URL': 'http://imbi-api',
            'IMBI_API_URL': 'https://imbi.example.com/api',
            'IMBI_GATEWAY_API_TOKEN': 'gw',
        }
        with mock.patch.dict(os.environ, env):
            await actions.sync_issue_counts(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='demo',
                action_config=actions.SyncIssueCountsConfig(),
                event={},
            )
        self.assertEqual(
            b'[{"op":"add","path":"/sentry_open_issues","value":7},'
            b'{"op":"add","path":"/sentry_new","value":2}]',
            patch.calls.last.request.content,
        )

    async def test_unknown_project_patches_nothing(self) -> None:
        respx.get(_PROJECT_URL).respond(404)
        await actions.sync_issue_counts(
            ctx=_ctx(),
            credentials=_CREDS,
            external_identifier='demo',
            action_config=actions.SyncIssueCountsConfig(),
            event={},
        )
        self.assertEqual(1, len(respx.calls))
