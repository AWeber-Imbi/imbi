"""Logz.io LogsPlugin implementation."""

import datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import cast

from imbi_common.plugins.base import (
    CredentialField,
    LogEntry,
    LogQuery,
    LogResult,
    LogsPlugin,
    PluginContext,
    PluginManifest,
    PluginOption,
)
from imbi_common.plugins.errors import PluginCredentialsMissing

from imbi_plugin_logzio.client import get_log_types, post_search
from imbi_plugin_logzio.query import (
    build_query_body,
    compute_fp,
    decode_cursor,
    encode_cursor,
)
from imbi_plugin_logzio.schema import build_schema


def _get_version() -> str:
    try:
        return _pkg_version('imbi-plugin-logzio')
    except PackageNotFoundError:
        return 'dev'


_VERSION = _get_version()


class LogzioPlugin(LogsPlugin):
    manifest = PluginManifest(
        slug='logzio',
        name='Logz.io',
        description='Search Logz.io logs from the Imbi project logs tab.',
        plugin_type='logs',
        api_version=1,
        cacheable=False,
        options=[
            PluginOption(
                name='region',
                label='Region',
                type='string',
                required=False,
                default='us',
                choices=['us', 'eu', 'uk', 'au', 'ca'],
                description='Logz.io account region.',
            ),
            PluginOption(
                name='base_query',
                label='Base Query Template',
                type='string',
                required=False,
                description=(
                    'Elasticsearch query_string applied as a must clause. '
                    'Supports ${project_slug}, ${org_slug}, ${environment}, '
                    '${project_id}.'
                ),
            ),
            PluginOption(
                name='timestamp_field',
                label='Timestamp Field',
                type='string',
                default='@timestamp',
            ),
            PluginOption(
                name='message_field',
                label='Message Field',
                type='string',
                default='message',
            ),
            PluginOption(
                name='level_field',
                label='Level Field',
                type='string',
                default='level',
            ),
            PluginOption(
                name='timeout_seconds',
                label='Request Timeout',
                type='integer',
                default=15,
            ),
        ],
        credentials=[
            CredentialField(
                name='api_token',
                label='Logz.io API Token',
                description='X-API-TOKEN with search privileges.',
            ),
        ],
    )

    async def search(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        query: LogQuery,
    ) -> LogResult:
        api_token = credentials.get('api_token', '')
        if not api_token:
            raise PluginCredentialsMissing('api_token is required')

        opts = ctx.assignment_options
        region, timeout = _connection_opts(ctx)
        timestamp_field = str(opts.get('timestamp_field', '@timestamp'))
        message_field = str(opts.get('message_field', 'message'))
        level_field = str(opts.get('level_field', 'level'))
        raw_bq = opts.get('base_query')
        base_query_template = str(raw_bq) if raw_bq is not None else None

        ctx_vars: dict[str, str | None] = {
            'project_slug': ctx.project_slug,
            'org_slug': ctx.org_slug,
            'environment': ctx.environment,
            'project_id': ctx.project_id,
        }

        size = min(query.limit, 1000)
        query_body = build_query_body(
            query,
            base_query=base_query_template,
            timestamp_field=timestamp_field,
            message_field=message_field,
            ctx_vars=ctx_vars,
        )
        fp = compute_fp(query_body)

        request_body: dict[str, object] = dict(query_body)
        if query.cursor:
            search_after = decode_cursor(query.cursor, fp)
            request_body['search_after'] = search_after

        data = await post_search(
            api_token=api_token,
            region=region,
            body=request_body,
            timeout=timeout,
            version=_VERSION,
        )

        hits_wrapper_raw = data.get('hits', {})
        if not isinstance(hits_wrapper_raw, dict):
            return LogResult(entries=[], total=0)
        hits_wrapper = cast('dict[str, object]', hits_wrapper_raw)

        raw_entries_val = hits_wrapper.get('hits', [])
        raw_entries: list[object] = (
            cast('list[object]', raw_entries_val)
            if isinstance(raw_entries_val, list)
            else []
        )

        total_raw = hits_wrapper.get('total')
        total: int | None
        if isinstance(total_raw, dict):
            total_raw_dict = cast('dict[str, object]', total_raw)
            total = int(cast('int', total_raw_dict.get('value', 0)))
        elif isinstance(total_raw, int):
            total = total_raw
        else:
            total = None

        entries: list[LogEntry] = []
        last_sort: list[object] | None = None
        for hit_raw in raw_entries:
            if not isinstance(hit_raw, dict):
                continue
            hit = cast('dict[str, object]', hit_raw)
            source_raw = hit.get('_source', {})
            source: dict[str, object] = (
                cast('dict[str, object]', source_raw)
                if isinstance(source_raw, dict)
                else {}
            )
            ts = _parse_timestamp(source.get(timestamp_field))
            message = str(source.get(message_field, ''))
            level_val = source.get(level_field)
            level = str(level_val) if level_val is not None else None
            entries.append(
                LogEntry(
                    timestamp=ts,
                    message=message,
                    level=level,
                    raw=source,
                )
            )
            sort_val = hit.get('sort')
            if isinstance(sort_val, list):
                last_sort = cast('list[object]', sort_val)

        next_cursor: str | None = None
        if len(entries) == size and last_sort is not None:
            next_cursor = encode_cursor(last_sort, fp)

        return LogResult(entries=entries, next_cursor=next_cursor, total=total)

    async def schema(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[dict[str, object]]:
        api_token = credentials.get('api_token', '')
        region, timeout = _connection_opts(ctx)

        log_types: list[str] | None = None
        if api_token:
            log_types = await get_log_types(
                api_token=api_token,
                region=region,
                timeout=timeout,
                version=_VERSION,
            )

        return build_schema(log_types)


def _connection_opts(ctx: PluginContext) -> tuple[str, float]:
    opts = ctx.assignment_options
    region = str(opts.get('region', 'us'))
    timeout = float(opts.get('timeout_seconds', 15))
    return region, timeout


def _parse_timestamp(value: object) -> datetime.datetime:
    if not isinstance(value, str) or not value:
        return datetime.datetime.now(datetime.UTC)
    try:
        dt = datetime.datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=datetime.UTC)
        return dt
    except (ValueError, TypeError):
        return datetime.datetime.now(datetime.UTC)
