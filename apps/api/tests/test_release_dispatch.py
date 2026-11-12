"""Tests for :mod:`imbi.api.plugins.release_dispatch`."""

import unittest
import unittest.mock as mock

from imbi.api.plugins import release_dispatch, resolution
from imbi.common.plugins import base, registry

_RELEASE = base.TrackedRelease(
    id='r1', tag='1.0.0', committish='abc1234', created_by='me@x'
)


class _Ok(base.ReleaseTrackingCapability):
    async def on_release_created(
        self,
        ctx: base.PluginContext,
        credentials: dict[str, str],
        release: base.TrackedRelease,
    ) -> base.LifecycleResult:
        assert ctx.org_slug == 'org'
        assert ctx.team_slug == 'team'
        return base.LifecycleResult(status='ok', message=release.tag)


class _Boom(base.ReleaseTrackingCapability):
    async def on_release_created(
        self,
        ctx: base.PluginContext,
        credentials: dict[str, str],
        release: base.TrackedRelease,
    ) -> base.LifecycleResult:
        raise RuntimeError('boom')


def _resolved(
    slug: str, handler: type[base.ReleaseTrackingCapability]
) -> resolution.ResolvedCapability:
    entry = registry.RegistryEntry(
        plugin_cls=object,  # type: ignore[arg-type]
        manifest=base.PluginManifest(
            slug=slug,
            name=slug,
            auth_type='api_token',
            capabilities=[
                base.Capability(
                    kind='release-tracking', label='R', handler=handler
                )
            ],
        ),
        package_name=f'imbi-plugin-{slug}',
        package_version='1.0.0',
    )
    return resolution.ResolvedCapability(
        integration_id=f'{slug}-id',
        integration_slug=slug,
        plugin_slug=slug,
        kind='release-tracking',
        entry=entry,
        capability_cls=handler,
        integration={'id': f'{slug}-id', 'slug': slug, 'plugin': slug},
        integration_options={},
        capability_options={},
        encrypted_credentials={},
    )


class DispatchReleaseCreatedTestCase(unittest.IsolatedAsyncioTestCase):
    async def _dispatch(
        self, resolved: list[resolution.ResolvedCapability]
    ) -> mock.AsyncMock:
        db = mock.AsyncMock()
        db.execute.return_value = [{'org_slug': '"org"'}]
        publish = mock.AsyncMock()
        with (
            mock.patch.object(
                release_dispatch,
                'resolve_all_capabilities',
                mock.AsyncMock(return_value=resolved),
            ),
            mock.patch.object(
                release_dispatch,
                'resolve_credentials',
                return_value={'auth_token': 't'},
            ),
            mock.patch(
                'imbi.api.endpoints._helpers.lookup_project_slugs',
                mock.AsyncMock(return_value=('proj', 'team')),
            ),
            mock.patch(
                'imbi.api.endpoints._helpers.lookup_project_links',
                mock.AsyncMock(return_value={}),
            ),
            mock.patch(
                'imbi.api.endpoints._helpers.lookup_project_exists_in',
                mock.AsyncMock(return_value=[]),
            ),
            mock.patch.object(release_dispatch.iggy, 'publish_rows', publish),
        ):
            await release_dispatch.dispatch_release_created(db, 'p1', _RELEASE)
        return publish

    async def test_records_one_event_per_integration(self) -> None:
        publish = await self._dispatch(
            [_resolved('sentry', _Ok), _resolved('other', _Boom)]
        )
        rows = publish.await_args.args[2]
        self.assertEqual(
            [
                ('sentry', 'ok', '1.0.0'),
                ('other', 'failed', 'RuntimeError: boom'),
            ],
            [
                (
                    r['integration'],
                    r['payload']['status'],
                    r['payload']['message'],
                )
                for r in rows
            ],
        )
        self.assertEqual('plugin.release-tracking.created', rows[0]['type'])
        self.assertEqual('r1', rows[0]['metadata']['release_id'])
        self.assertEqual('me@x', rows[0]['attributed_to'])

    async def test_no_bindings_publishes_nothing(self) -> None:
        publish = await self._dispatch([])
        publish.assert_not_awaited()
