"""GitHub connection plugin.

A single connection plugin is attached to each GitHub
``ThirdPartyService`` and is the one place an operator configures the
GitHub flavor / host and the shared server-to-server credentials. It
carries no behavior of its own -- the identity, deployment, lifecycle,
and commit-/pr-sync plugins read its ``flavor`` + ``host`` options off
``ctx.service_plugins`` to resolve their host, and the Imbi host
resolves their App/PAT credentials from this plugin's
``plugin_configuration`` when they carry none themselves.

The identity plugin keeps its own OAuth App ``client_id`` /
``client_secret`` (a GitHub OAuth App is a separate registration from a
GitHub App), so those credentials are deliberately *not* declared here.
"""

from __future__ import annotations

from imbi_common.plugins.base import (
    ConnectionPlugin,
    CredentialField,
    PluginManifest,
    PluginOption,
)


class GitHubConnectionPlugin(ConnectionPlugin):
    manifest = PluginManifest(
        slug='github-connection',
        name='GitHub Connection',
        description=(
            'Holds the GitHub flavor/host and shared App/PAT credentials '
            'for every GitHub plugin on the service.'
        ),
        plugin_type='connection',
        auth_type='api_token',
        options=[
            PluginOption(
                name='flavor',
                label='Flavor',
                description=(
                    'github.com, GitHub Enterprise Cloud (ghec), or '
                    'GitHub Enterprise Server (ghes).'
                ),
                type='string',
                choices=['github.com', 'ghec', 'ghes'],
                required=True,
            ),
            PluginOption(
                name='host',
                label='Host',
                description=(
                    'Tenant host (tenant.ghe.com) for ghec or the '
                    'appliance hostname for ghes; ignored for github.com.'
                ),
                type='string',
            ),
        ],
        credentials=[
            CredentialField(
                name='app_id',
                label='GitHub App ID',
                description='GitHub App ID (App auth).',
                required=False,
            ),
            CredentialField(
                name='private_key',
                label='GitHub App private key',
                description='PEM or base64-encoded PEM (App auth).',
                required=False,
            ),
            CredentialField(
                name='access_token',
                label='Personal access token',
                description='PAT used when not using App auth.',
                required=False,
            ),
        ],
    )
