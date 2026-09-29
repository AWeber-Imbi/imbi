"""Tests for PagerDuty service-dependency sync."""

import json
import unittest

import httpx
import respx

from imbi.common.plugins.base import (
    PluginContext,
    ProjectDependency,
    ServiceConnection,
)
from imbi.plugins.pagerduty import _client, _dependencies
from imbi.plugins.pagerduty.lifecycle import PagerDutyLifecycle

_SLUG = 'pagerduty'
_CREDS = {'api_key': 'k'}
_SVC = 'PSELF'
_BASE = 'https://api.pagerduty.com'
_DEPS_URL = f'{_BASE}/service_dependencies/technical_services/{_SVC}'


def _pair(dependent: str, supporting: str) -> _dependencies.Pair:
    return _dependencies.Pair(dependent=dependent, supporting=supporting)


def _conn(identifier: str, slug: str = _SLUG) -> ServiceConnection:
    return ServiceConnection(integration_slug=slug, identifier=identifier)


def _dep(
    direction: str, slug: str, service_id: str | None
) -> ProjectDependency:
    return ProjectDependency.model_validate(
        {
            'direction': direction,
            'project_id': f'id-{slug}',
            'project_slug': slug,
            'service_connections': (
                [_conn(service_id)] if service_id is not None else []
            ),
        }
    )


def _ctx(
    dependencies: list[ProjectDependency],
    *,
    linked: set[str] | None = None,
) -> PluginContext:
    async def _resolve(identifiers: list[str]) -> set[str]:
        return {i for i in identifiers if i in (linked or set())}

    return PluginContext(
        project_id='p',
        project_slug='demo',
        org_slug='org',
        integration_slug=_SLUG,
        service_connections=[_conn(_SVC)],
        dependencies=dependencies,
        resolve_linked_identifiers=_resolve if linked is not None else None,
    )


def _rel(
    dependent: str, supporting: str, kind: str = 'service'
) -> dict[str, object]:
    return {
        'dependent_service': {'id': dependent, 'type': kind},
        'supporting_service': {'id': supporting, 'type': kind},
    }


def _mock_current(*relationships: dict[str, object]) -> None:
    respx.get(_DEPS_URL).mock(
        return_value=httpx.Response(
            200, json={'relationships': list(relationships)}
        )
    )


class DesiredPairsTestCase(unittest.TestCase):
    def test_maps_directions_and_reports_unlinked(self) -> None:
        ctx = _ctx(
            [
                _dep('outbound', 'db', 'PDB'),
                _dep('inbound', 'web', 'PWEB'),
                _dep('outbound', 'cache', None),
            ]
        )
        desired, unlinked = _dependencies.desired_pairs(ctx, _SVC)
        self.assertEqual(desired, {_pair(_SVC, 'PDB'), _pair('PWEB', _SVC)})
        self.assertEqual(unlinked, ['cache'])

    def test_ignores_connections_to_other_integrations(self) -> None:
        dep = ProjectDependency(
            direction='outbound',
            project_id='x',
            project_slug='repo',
            service_connections=[_conn('123', slug='github')],
        )
        desired, unlinked = _dependencies.desired_pairs(_ctx([dep]), _SVC)
        self.assertEqual(desired, set())
        self.assertEqual(unlinked, ['repo'])


class PlanTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_adds_missing_and_removes_only_linked_extras(self) -> None:
        _mock_current(
            _rel(_SVC, 'PDB'),  # desired, keep
            _rel(_SVC, 'PGONE'),  # Imbi-linked, no DEPENDS_ON -> remove
            _rel(_SVC, 'PHAND'),  # not linked to Imbi -> keep
            _rel(_SVC, 'PBIZ', kind='business_service'),  # never touched
        )
        ctx = _ctx(
            [_dep('outbound', 'db', 'PDB'), _dep('inbound', 'web', 'PWEB')],
            linked={'PDB', 'PWEB', 'PGONE'},
        )
        async with _client.client(_CREDS) as client:
            changes = await _dependencies.plan(client, ctx, _SVC)
        self.assertEqual(changes.add, [_pair('PWEB', _SVC)])
        self.assertEqual(changes.remove, [_pair(_SVC, 'PGONE')])
        self.assertFalse(changes.in_sync)

    @respx.mock
    async def test_without_resolver_never_removes(self) -> None:
        _mock_current(_rel(_SVC, 'PGONE'))
        async with _client.client(_CREDS) as client:
            changes = await _dependencies.plan(client, _ctx([]), _SVC)
        self.assertEqual(changes.remove, [])
        self.assertTrue(changes.in_sync)


class ApplyTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_associates_and_disassociates(self) -> None:
        associate = respx.post(f'{_BASE}/service_dependencies/associate').mock(
            return_value=httpx.Response(200, json={})
        )
        disassociate = respx.post(
            f'{_BASE}/service_dependencies/disassociate'
        ).mock(return_value=httpx.Response(200, json={}))
        changes = _dependencies.Plan(
            add=[_pair(_SVC, 'PDB')], remove=[_pair(_SVC, 'PGONE')]
        )
        async with _client.client(_CREDS) as client:
            await _dependencies.apply(client, changes)
        body = json.loads(associate.calls.last.request.content)
        self.assertEqual(
            body['relationships'],
            [
                {
                    'dependent_service': {'id': _SVC, 'type': 'service'},
                    'supporting_service': {'id': 'PDB', 'type': 'service'},
                }
            ],
        )
        body = json.loads(disassociate.calls.last.request.content)
        self.assertEqual(
            body['relationships'][0]['supporting_service']['id'], 'PGONE'
        )


class LifecycleDependenciesChangedTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_syncs_changes(self) -> None:
        _mock_current()
        associate = respx.post(f'{_BASE}/service_dependencies/associate').mock(
            return_value=httpx.Response(200, json={})
        )
        ctx = _ctx([_dep('outbound', 'db', 'PDB')], linked=set())
        result = await PagerDutyLifecycle().on_project_dependencies_changed(
            ctx, _CREDS
        )
        self.assertEqual(result.status, 'ok')
        self.assertIn('add 1', result.message or '')
        self.assertTrue(associate.called)

    @respx.mock
    async def test_in_sync_is_skipped(self) -> None:
        _mock_current(_rel(_SVC, 'PDB'))
        ctx = _ctx([_dep('outbound', 'db', 'PDB')], linked=set())
        result = await PagerDutyLifecycle().on_project_dependencies_changed(
            ctx, _CREDS
        )
        self.assertEqual(result.status, 'skipped')

    @respx.mock
    async def test_no_service_is_skipped(self) -> None:
        respx.get(f'{_BASE}/services').mock(
            return_value=httpx.Response(200, json={'services': []})
        )
        ctx = PluginContext(
            project_id='p',
            project_slug='demo',
            org_slug='org',
            integration_slug=_SLUG,
        )
        result = await PagerDutyLifecycle().on_project_dependencies_changed(
            ctx, _CREDS
        )
        self.assertEqual(result.status, 'skipped')
