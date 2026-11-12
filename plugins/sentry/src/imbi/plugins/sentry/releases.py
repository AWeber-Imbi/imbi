"""Sentry release-tracking capability: create a Sentry release per Imbi one.

The Sentry version must equal the ``release`` value the project's Sentry
SDK sends, or Sentry cannot tie events to it. The ``version_format``
option sets it; the default is Sentry's ``package@version`` form.
"""

from __future__ import annotations

from imbi.common.plugins import templates
from imbi.common.plugins.base import (
    LifecycleResult,
    PluginContext,
    ReleaseTrackingCapability,
    TrackedRelease,
)
from imbi.plugins.sentry import client
from imbi.plugins.sentry.doctor import connection

DEFAULT_VERSION_FORMAT = '${project_slug}@${tag}'


def version(ctx: PluginContext, release: TrackedRelease) -> str | None:
    """Return the Sentry version, or ``None`` when it needs a missing tag.

    Raises :class:`ValueError` for an unknown ``${...}`` placeholder.
    """
    fmt = str(
        ctx.capability_options.get('version_format') or DEFAULT_VERSION_FORMAT
    )
    if '${tag}' in fmt and not release.tag:
        return None
    return templates.expand_template(
        fmt,
        {
            'project_slug': ctx.project_slug,
            'tag': release.tag,
            'committish': release.committish,
        },
    )


class SentryReleaseTracking(ReleaseTrackingCapability):
    """Create the release in Sentry for the project's Sentry project."""

    async def on_release_created(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        release: TrackedRelease,
    ) -> LifecycleResult:
        # A hand-set identifier could name another team's Sentry project.
        conn = connection(ctx)
        if conn is None or conn.verified_identifier != conn.identifier:
            return LifecycleResult(
                status='skipped',
                message='The Sentry project link is not verified; run the '
                'Project Doctor to link it.',
            )
        try:
            name = version(ctx, release)
        except ValueError as exc:
            return LifecycleResult(status='failed', message=str(exc))
        if name is None:
            return LifecycleResult(
                status='skipped',
                message='The release has no tag and the version needs one',
            )
        try:
            s = client.settings(ctx, credentials)
            # The verified canonical URL holds the Sentry host and
            # organization; a settings change since then is unverified.
            if conn.canonical_url != client.canonical_url(s, conn.identifier):
                return LifecycleResult(
                    status='skipped',
                    message='The Sentry settings changed after the project '
                    'link was verified; run the Project Doctor to link it.',
                )
            created = await client.create_release(s, name, conn.identifier)
        except client.SentryClientError as exc:
            return LifecycleResult(status='failed', message=str(exc))
        verb = 'Created' if created else 'Updated existing'
        return LifecycleResult(
            status='ok',
            message=f'{verb} Sentry release {name!r}',
            artifacts={'version': name},
        )
