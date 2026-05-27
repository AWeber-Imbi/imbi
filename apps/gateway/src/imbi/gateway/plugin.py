"""Built-in webhook-action plugin shipped with imbi-gateway.

Wraps the bundled actions (``update_project``, ``create_release``,
``add_deployment_event``, ``ingest_sbom``) as a
:class:`WebhookActionPlugin` so they participate in the same
discovery, validation, and dispatch flow as externally-installed
plugins. Declares no credentials -- the host always passes an empty
``credentials`` dict to these callables.
"""

import typing

from imbi_common.plugins import base as plugin_base


def _descriptor(
    name: str,
    label: str,
    description: str,
    callable_path: str,
    model_path: str,
) -> plugin_base.ActionDescriptor:
    """Build an :class:`ActionDescriptor` from string import paths.

    pydantic's ``ImportString`` validator accepts a string and resolves
    it lazily; the static type checkers do not know that, so the cast
    suppresses spurious "incompatible type" diagnostics without leaving
    unused per-line ignores.
    """
    return plugin_base.ActionDescriptor(
        name=name,
        label=label,
        description=description,
        callable=typing.cast('typing.Any', callable_path),
        config_model=typing.cast('typing.Any', model_path),
    )


class GatewayActionsPlugin(plugin_base.WebhookActionPlugin):
    """Built-in plugin exposing the gateway's bundled webhook actions."""

    manifest = plugin_base.PluginManifest(
        slug='gateway-actions',
        name='Gateway Actions',
        description=(
            'Webhook actions shipped with imbi-gateway: update project '
            'facts, create a release, and append a deployment event.'
        ),
        plugin_type='webhook',
        credentials=[],
    )

    @classmethod
    def actions(cls) -> list[plugin_base.ActionDescriptor]:
        return [
            _descriptor(
                name='update_project',
                label='Update Project from Webhook',
                description=(
                    'Patches Imbi project facts using values read out of '
                    'the webhook payload via JSON Pointer mappings.'
                ),
                callable_path='imbi_gateway.actions:update_project',
                model_path='imbi_gateway.actions:UpdateProjectConfig',
            ),
            _descriptor(
                name='create_release',
                label='Create Release from Deployment Webhook',
                description=(
                    'Creates (or idempotently confirms) the Release on the '
                    "matched Imbi project using the payload's version "
                    'expression and title selector.'
                ),
                callable_path='imbi_gateway.actions:create_release',
                model_path='imbi_gateway.actions:CreateReleaseConfig',
            ),
            _descriptor(
                name='add_deployment_event',
                label='Add Deployment Event from Webhook',
                description=(
                    "Appends a deployment event to the release's "
                    'DEPLOYED_TO edge for the matching environment.'
                ),
                callable_path='imbi_gateway.actions:add_deployment_event',
                model_path='imbi_gateway.actions:AddDeploymentEventConfig',
            ),
            _descriptor(
                name='ingest_sbom',
                label='Ingest CycloneDX SBoM for Release',
                description=(
                    'Forwards a CycloneDX 1.7 SBoM document to the '
                    'Imbi API for the matched project release.'
                ),
                callable_path='imbi_gateway.actions:ingest_sbom',
                model_path='imbi_gateway.actions:IngestSbomConfig',
            ),
        ]
