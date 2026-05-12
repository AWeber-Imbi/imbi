"""Project configuration plugin endpoints."""

import datetime
import json
import logging
import os
import typing

import fastapi
import nanoid
from imbi_common import clickhouse, graph, valkey
from imbi_common import models as common_models
from imbi_common.plugins.base import (
    ConfigurationPlugin,
    ConfigValue,
    PluginContext,
)
from imbi_common.plugins.errors import (
    PluginCredentialsMissing,
)

from imbi_api.auth import permissions
from imbi_api.domain import models
from imbi_api.endpoints._helpers import lookup_project_slugs
from imbi_api.identity.host_integration import call_with_identity_retry
from imbi_api.plugins import call_with_timeout
from imbi_api.plugins.credentials import get_plugin_credentials
from imbi_api.plugins.resolution import resolve_plugin

LOGGER = logging.getLogger(__name__)

_CACHE_TTL = int(os.environ.get('IMBI_PLUGIN_CACHE_TTL', '60'))

project_configuration_router = fastapi.APIRouter(
    tags=['Project: Configuration'],
)


def _cache_key(
    plugin_id: str,
    project_id: str,
    source: str | None,
    environment: str | None,
) -> str:
    """Compose a per-(plugin, project, source, environment) cache key.

    ``list_keys`` results are context-dependent: switching ``source`` or
    ``environment`` can change which keys the plugin returns. Including
    both in the cache key prevents stale cross-context responses.
    """
    src = source or '_'
    env = environment or '_'
    return f'imbi:plugin-cache:{plugin_id}:{project_id}:{src}:{env}:list'


async def _invalidate_cache(
    plugin_id: str,
    project_id: str,
) -> None:
    """Drop every cached list response for a plugin/project pair.

    Writes invalidate across all (source, environment) combinations
    because we don't always know which contexts have cached entries.
    Falls back to a key scan via ``KEYS`` since the namespace is small
    and writes are infrequent.
    """
    try:
        client = valkey.get_client()
        pattern = f'imbi:plugin-cache:{plugin_id}:{project_id}:*:list'
        keys: list[bytes | str] = await client.keys(pattern)  # pyright: ignore[reportUnknownMemberType]
        if keys:
            await client.delete(*keys)
    except Exception:  # noqa: BLE001
        LOGGER.debug('Cache invalidate failed', exc_info=True)


async def _lookup_project_slug(
    db: graph.Graph,
    project_id: str,
) -> str:
    """Look up the project's slug for audit-log writes."""
    slug, _ = await lookup_project_slugs(db, project_id)
    return slug


@project_configuration_router.get('/')
async def get_configuration(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:configuration:read'),
        ),
    ],
    source: str | None = fastapi.Query(default=None),
    environment: str | None = fastapi.Query(default=None),
) -> list[models.ConfigKeyResponse]:
    """List configuration keys for a project via the assigned plugin."""
    resolved = await resolve_plugin(db, project_id, 'configuration', source)
    project_slug, team_slug = await lookup_project_slugs(db, project_id)
    ctx = PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        environment=environment,
        assignment_options=resolved.options,
    )
    try:
        credentials = await get_plugin_credentials(
            db, resolved.plugin_id, resolved.entry
        )
    except PluginCredentialsMissing as exc:
        raise fastapi.HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    cache_key = _cache_key(resolved.plugin_id, project_id, source, environment)
    try:
        client = valkey.get_client()
    except Exception:  # noqa: BLE001
        LOGGER.debug('Cache client unavailable', exc_info=True)
        client = None

    if client is not None:
        try:
            cached = await client.get(cache_key)
            if cached:
                return [
                    models.ConfigKeyResponse(**k) for k in json.loads(cached)
                ]
        except Exception:  # noqa: BLE001
            LOGGER.debug('Cache read failed', exc_info=True)

    handler = typing.cast(ConfigurationPlugin, resolved.entry.handler_cls())

    async def _list_keys(c: PluginContext) -> typing.Any:
        return await call_with_timeout(handler.list_keys(c, credentials))

    keys = await call_with_identity_retry(
        db, ctx, resolved, auth, fn=_list_keys
    )

    result = [
        models.ConfigKeyResponse(
            key=k.key,
            data_type=k.data_type,
            last_modified=k.last_modified,
            secret=k.secret,
        )
        for k in keys
    ]
    if client is not None:
        try:
            payload = json.dumps([r.model_dump(mode='json') for r in result])
            await client.setex(cache_key, _CACHE_TTL, payload)
        except Exception:  # noqa: BLE001
            LOGGER.debug('Cache write failed', exc_info=True)

    return result


@project_configuration_router.post('/values:fetch')
async def fetch_values(
    org_slug: str,
    project_id: str,
    body: dict[str, typing.Any],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'project:configuration:read_secrets',
            ),
        ),
    ],
    source: str | None = fastapi.Query(default=None),
    environment: str | None = fastapi.Query(default=None),
) -> list[models.ConfigKeyValueResponse]:
    """Fetch values for specific configuration keys."""
    resolved = await resolve_plugin(db, project_id, 'configuration', source)
    project_slug, team_slug = await lookup_project_slugs(db, project_id)
    ctx = PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        environment=environment,
        assignment_options=resolved.options,
    )
    try:
        credentials = await get_plugin_credentials(
            db, resolved.plugin_id, resolved.entry
        )
    except PluginCredentialsMissing as exc:
        raise fastapi.HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    keys: list[str] | None = body.get('keys')
    handler = typing.cast(ConfigurationPlugin, resolved.entry.handler_cls())

    async def _get_values(c: PluginContext) -> typing.Any:
        return await call_with_timeout(
            handler.get_values(c, credentials, keys)
        )

    values = await call_with_identity_retry(
        db, ctx, resolved, auth, fn=_get_values
    )

    return [
        models.ConfigKeyValueResponse(
            key=v.key,
            data_type=v.data_type,
            last_modified=v.last_modified,
            secret=v.secret,
            value=v.value,
        )
        for v in values
    ]


@project_configuration_router.put('/{key:path}')
async def set_configuration_value(
    org_slug: str,
    project_id: str,
    key: str,
    body: ConfigValue,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:configuration:write'),
        ),
    ],
    source: str | None = fastapi.Query(default=None),
    environment: str | None = fastapi.Query(default=None),
) -> models.ConfigKeyResponse:
    """Set a configuration value via the assigned plugin."""
    resolved = await resolve_plugin(db, project_id, 'configuration', source)
    project_slug, team_slug = await lookup_project_slugs(db, project_id)
    ctx = PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        environment=environment,
        assignment_options=resolved.options,
    )
    try:
        credentials = await get_plugin_credentials(
            db, resolved.plugin_id, resolved.entry
        )
    except PluginCredentialsMissing as exc:
        raise fastapi.HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    handler = typing.cast(ConfigurationPlugin, resolved.entry.handler_cls())

    async def _set_value(c: PluginContext) -> typing.Any:
        return await call_with_timeout(
            handler.set_value(c, credentials, key, body)
        )

    result_key = await call_with_identity_retry(
        db, ctx, resolved, auth, fn=_set_value
    )

    await _invalidate_cache(resolved.plugin_id, project_id)
    project_slug = await _lookup_project_slug(db, project_id)
    await _write_audit(
        project_id=project_id,
        project_slug=project_slug,
        environment_slug=environment or '',
        recorded_by=auth.principal_name,
        action='set_value',
        plugin_slug=resolved.plugin_slug,
        key=key,
        data_type=body.data_type,
        secret=body.secret,
    )
    return models.ConfigKeyResponse(
        key=result_key.key,
        data_type=result_key.data_type,
        last_modified=result_key.last_modified,
        secret=result_key.secret,
    )


@project_configuration_router.delete('/{key:path}', status_code=204)
async def delete_configuration_key(
    org_slug: str,
    project_id: str,
    key: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:configuration:write'),
        ),
    ],
    source: str | None = fastapi.Query(default=None),
    environment: str | None = fastapi.Query(default=None),
) -> None:
    """Delete a configuration key via the assigned plugin."""
    resolved = await resolve_plugin(db, project_id, 'configuration', source)
    project_slug, team_slug = await lookup_project_slugs(db, project_id)
    ctx = PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        environment=environment,
        assignment_options=resolved.options,
    )
    try:
        credentials = await get_plugin_credentials(
            db, resolved.plugin_id, resolved.entry
        )
    except PluginCredentialsMissing as exc:
        raise fastapi.HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    handler = typing.cast(ConfigurationPlugin, resolved.entry.handler_cls())

    async def _delete_key(c: PluginContext) -> None:
        await call_with_timeout(handler.delete_key(c, credentials, key))

    await call_with_identity_retry(db, ctx, resolved, auth, fn=_delete_key)

    await _invalidate_cache(resolved.plugin_id, project_id)
    project_slug = await _lookup_project_slug(db, project_id)
    await _write_audit(
        project_id=project_id,
        project_slug=project_slug,
        environment_slug=environment or '',
        recorded_by=auth.principal_name,
        action='delete_key',
        plugin_slug=resolved.plugin_slug,
        key=key,
        data_type='',
        secret=False,
    )


async def _write_audit(
    *,
    project_id: str,
    project_slug: str,
    environment_slug: str,
    recorded_by: str,
    action: str,
    plugin_slug: str,
    key: str,
    data_type: str,
    secret: bool,
) -> None:
    """Write a configuration-change audit row to ``operations_log``.

    Uses the canonical ``OperationLog`` model so the row matches the
    schema used by ``operations_log.py``. ``entry_type`` is fixed to
    ``'Configured'`` per the Literal in ``imbi_common.models``; the
    plugin/key/data_type/secret payload is encoded in ``description`` as
    JSON so consumers can decode the exact change without us having to
    extend the schema.

    Audit failures are intentionally **not** swallowed: a write that
    succeeded against the plugin but failed to be recorded would leave
    the operations log silently inconsistent. Letting the exception
    propagate surfaces the bad state to the caller (and to monitoring).
    """
    description = json.dumps(
        {
            'action': action,
            'plugin_slug': plugin_slug,
            'key': key,
            'data_type': data_type,
            'secret': secret,
        },
        sort_keys=True,
    )
    entry = common_models.OperationLog(
        id=nanoid.generate(),
        recorded_at=datetime.datetime.now(datetime.UTC),
        recorded_by=recorded_by,
        performed_by=recorded_by,
        project_id=project_id,
        project_slug=project_slug,
        environment_slug=environment_slug,
        entry_type='Configured',
        description=description,
        plugin_slug=plugin_slug,
    )
    row = entry.model_dump(by_alias=True, mode='python')
    row['is_deleted'] = 1 if entry.is_deleted else 0
    await clickhouse.client.Clickhouse.get_instance().insert(
        'operations_log',
        [list(row.values())],
        list(row.keys()),
    )
