"""The GitHub plugin — one :class:`Plugin` per package (Architecture v3).

A single :class:`GitHubPlugin` backs every GitHub Integration
(GitHub.com, a GHEC tenant, a GHES appliance — each a configured
instance). Its manifest declares the integration-level ``flavor`` /
``host`` options and the shared credential blob **once**, then binds a
handler for each capability the platform hosts:

* ``identity``        → ``identity.GitHubIdentity``
* ``deployment``      → ``deployment.GitHubDeployment``
* ``lifecycle``       → ``lifecycle.GitHubLifecycle``
* ``webhook-actions`` → :class:`GitHubWebhookActions`
* ``commit-sync``     → ``commits.GitHubCommitSync``
* ``pr-sync``         → ``pull_requests.GitHubPullRequestSync``
"""

from __future__ import annotations

from imbi.common.plugins.base import (
    ActionDescriptor,
    Capability,
    CredentialField,
    OpsLogTemplate,
    Plugin,
    PluginManifest,
    PluginOption,
    WebhookActionsCapability,
)
from imbi.plugins.github.commits import (
    GitHubCommitSync,
    sync_commits_descriptor,
    sync_tags_descriptor,
)
from imbi.plugins.github.deployment import GitHubDeployment
from imbi.plugins.github.doctor import GitHubDoctor
from imbi.plugins.github.identity import DEFAULT_SCOPES, GitHubIdentity
from imbi.plugins.github.lifecycle import GitHubLifecycle
from imbi.plugins.github.pull_requests import (
    GitHubPullRequestSync,
    sync_pull_requests_descriptor,
)


class GitHubWebhookActions(WebhookActionsCapability):
    """Catalog of gateway-dispatched GitHub webhook actions.

    Aggregates the push-driven commit / tag sync and the PR-driven sync
    into one ``webhook-actions`` capability. The host parses
    ``WebhookRule.handler`` as ``"github#<action_name>"``, resolves the
    matching :class:`ActionDescriptor`, and invokes its callable.
    """

    @classmethod
    def actions(cls) -> list[ActionDescriptor]:
        return [
            sync_commits_descriptor,
            sync_tags_descriptor,
            sync_pull_requests_descriptor,
        ]


# Integration-level options, asked once per Integration.
_OPTIONS: list[PluginOption] = [
    PluginOption(
        name='flavor',
        label='Flavor',
        description=(
            'github (github.com), GitHub Enterprise Cloud (ghec), or '
            'GitHub Enterprise Server (ghes).'
        ),
        type='string',
        choices=['github', 'ghec', 'ghes'],
        required=True,
    ),
    PluginOption(
        name='host',
        label='Host',
        description=(
            'Tenant host (tenant.ghe.com) for ghec or the appliance '
            'hostname for ghes; ignored for github.'
        ),
        type='string',
    ),
]

# The single credential store for the Integration. Every capability of
# the Integration receives this same decrypted blob. GitHub App auth
# (app_id + private_key, optional installation_id) powers the service
# capabilities (commit-sync / pr-sync); the OAuth App client credentials
# (client_id / client_secret) power the identity capability. All are
# optional so, e.g., an identity-only or App-only Integration is valid.
_CREDENTIALS: list[CredentialField] = [
    CredentialField(
        name='access_token',
        label='Personal access token',
        description=(
            'GitHub personal access token used as the bearer credential '
            'for PAT-based integrations (commit / pull-request sync, '
            'deployments, lifecycle). Leave blank when using GitHub App '
            'or OAuth authentication.'
        ),
        required=False,
        secret=True,
    ),
    CredentialField(
        name='app_id',
        label='GitHub App ID',
        description='GitHub App identifier used to mint installation tokens.',
        required=False,
        secret=False,
    ),
    CredentialField(
        name='private_key',
        label='GitHub App private key',
        description='App private key, raw PEM or base64-encoded PEM.',
        required=False,
        multiline=True,
    ),
    CredentialField(
        name='installation_id',
        label='GitHub App installation ID',
        description=(
            'Optional. When unset, the installation is discovered from the '
            'target repository.'
        ),
        required=False,
        secret=False,
    ),
    CredentialField(
        name='client_id',
        label='OAuth client ID',
        description='OAuth App client id for the identity capability.',
        required=False,
        secret=False,
    ),
    CredentialField(
        name='client_secret',
        label='OAuth client secret',
        description='OAuth App client secret for the identity capability.',
        required=False,
    ),
]

# Capability-scoped options for repository lifecycle. Values live in
# ``Integration.capabilities['lifecycle'].options`` (layered with any
# per-project-type / per-project USES-edge overrides) and arrive on
# ``ctx.capability_options``.
_LIFECYCLE_OPTIONS: list[PluginOption] = [
    PluginOption(
        name='archive_target_org',
        label='Transfer to org on archive',
        description=(
            'When set, repos are transferred to this organization before '
            'being archived.  Useful for moving sunset projects into a '
            'dedicated "archive" org so they no longer count against your '
            "primary org's repo quota or surface in default searches.  "
            'Leave blank to archive in place.  Requires admin permission '
            'on both the source repo and the destination organization.'
        ),
        type='string',
        required=False,
    ),
    PluginOption(
        name='create_org',
        label='Default org for repo creation',
        description=(
            'Org used by project creation (and the relocate-target '
            'preview) when no per-project-type override matches in '
            '``org_mapping``.  Supports the template variables '
            '``${project_slug}``, ``${org_slug}``, ``${team_slug}``, '
            '``${project_type_slug}``, ``${project_id}``.  Leave blank '
            'to skip create / relocate when no mapping matches.'
        ),
        type='string',
        required=False,
    ),
    PluginOption(
        name='org_mapping',
        label='Project-type to org overrides',
        description=(
            'Per-project-type-slug overrides for the target GitHub org.  '
            'The first ``project_type_slug`` that has a mapping wins '
            'over ``create_org``.  Use this when different project types '
            'live in different orgs (e.g. ``api`` → ``aweber-services``, '
            '``library`` → ``aweber-libs``).'
        ),
        type='mapping',
        required=False,
    ),
]

# Capability-scoped options for the identity capability.
_IDENTITY_OPTIONS: list[PluginOption] = [
    PluginOption(
        name='default_scopes',
        label='Default scopes (space-separated)',
        type='string',
    ),
]

_LIFECYCLE_EVENTS: list[str] = [
    'created',
    'updated',
    'archived',
    'unarchived',
    'deleted',
    'relocated',
]

# Templates for the operations-log JSON payload the API writes from
# ``_record_deployment_event`` in imbi-api: ``{action, plugin_slug,
# run_url, release_url, from_environment}``.  Row-level fields
# ``version`` and ``environment`` are also in scope.
_OPS_LOG_TEMPLATES: dict[str, OpsLogTemplate] = {
    'deploy': OpsLogTemplate(
        label='Deployed {{version}} to {{environment}}',
        summary='deployed',
    ),
    'redeploy': OpsLogTemplate(
        label='Re-deployed {{version}} to {{environment}}',
        summary='re-deployed',
    ),
    'promote': OpsLogTemplate(
        label=(
            'Promoted {{from_environment}} to {{environment}} as {{version}}.'
        ),
        summary='promoted',
    ),
    'resync': OpsLogTemplate(
        label='Recorded {{version}} deploy in {{environment}}',
        summary='recorded a deploy in',
    ),
}


class GitHubPlugin(Plugin):
    """One plugin per package; the manifest is the complete declaration."""

    manifest = PluginManifest(
        slug='github',
        name='GitHub',
        icon='si-github',
        description=(
            'GitHub integration for identity, deployments, repository '
            'lifecycle, and commit / pull-request history sync across '
            'github.com, GHEC, and GHES.'
        ),
        auth_type='oauth2',
        options=_OPTIONS,
        credentials=_CREDENTIALS,
        capabilities=[
            Capability(
                kind='identity',
                label='Sign in with GitHub',
                description='GitHub OAuth App identity provider.',
                options=_IDENTITY_OPTIONS,
                default_enabled=False,
                project_scoped=False,
                hints={
                    'login_capable': True,
                    'default_scopes': DEFAULT_SCOPES,
                    'widget_text': (
                        'Connect to enable functionality such as '
                        'pull-request visibility, project creation, and '
                        'deployments.'
                    ),
                },
                handler=GitHubIdentity,
            ),
            Capability(
                kind='deployment',
                label='Deployments',
                description=(
                    'Drive GitHub Deployments and record GitHub Releases '
                    'so environment protection rules apply server-side.'
                ),
                hints={'supports_deployment_sync': True},
                handler=GitHubDeployment,
            ),
            Capability(
                kind='lifecycle',
                label='Repository lifecycle',
                description=(
                    'Create, rename, archive, transfer, or delete the '
                    'matching repository on project lifecycle changes.'
                ),
                options=_LIFECYCLE_OPTIONS,
                hints={
                    'supports_lifecycle_sync': True,
                    'lifecycle_events': _LIFECYCLE_EVENTS,
                },
                handler=GitHubLifecycle,
            ),
            Capability(
                kind='webhook-actions',
                label='Webhook actions',
                description=(
                    'Gateway-dispatched commit, tag, and pull-request '
                    'sync from GitHub webhook deliveries.'
                ),
                handler=GitHubWebhookActions,
            ),
            Capability(
                kind='commit-sync',
                label='Commit history sync',
                description=(
                    'Ingest commit and tag history into ClickHouse for '
                    'analytics.'
                ),
                handler=GitHubCommitSync,
            ),
            Capability(
                kind='pr-sync',
                label='Pull request sync',
                description=(
                    'Ingest pull-request history into ClickHouse for '
                    'analytics.'
                ),
                handler=GitHubPullRequestSync,
            ),
            Capability(
                kind='analysis',
                label='Project doctor',
                description=(
                    'Validate the GitHub repository link (EXISTS_IN edge) '
                    'against the live GitHub API — identifier, canonical '
                    'URL shape, and dashboard / github-repository links — '
                    'and offer one-click repairs.'
                ),
                handler=GitHubDoctor,
            ),
        ],
        ops_log_templates=_OPS_LOG_TEMPLATES,
    )
