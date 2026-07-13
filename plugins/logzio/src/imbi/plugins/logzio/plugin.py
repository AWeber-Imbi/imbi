"""Logz.io logs capability implementation (Plugin Architecture v3)."""

import asyncio
import datetime
import logging
from collections.abc import Coroutine, Sequence
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Any, cast

from imbi_common.plugins.base import (
    Capability,
    CredentialField,
    LogEntry,
    LogHistogramBucket,
    LogQuery,
    LogResult,
    LogsCapability,
    Plugin,
    PluginContext,
    PluginManifest,
    PluginOption,
)
from imbi_common.plugins.errors import PluginCredentialsMissing

from imbi_plugin_logzio.client import get_log_types, post_search
from imbi_plugin_logzio.query import (
    build_histogram_body,
    build_query_body,
    compute_fp,
    decode_cursor,
    encode_cursor,
)
from imbi_plugin_logzio.schema import build_schema

LOGGER = logging.getLogger(__name__)


def _get_version() -> str:
    try:
        return _pkg_version('imbi-plugin-logzio')
    except PackageNotFoundError:
        return 'dev'


_VERSION = _get_version()


class LogzioLogs(LogsCapability):
    """Logs capability backed by the Logz.io search API."""

    async def search(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        query: LogQuery,
    ) -> LogResult:
        api_token = credentials.get('api_token', '')
        if not api_token:
            raise PluginCredentialsMissing('api_token is required')

        opts = ctx.capability_options
        region, timeout = _connection_opts(ctx)
        timestamp_field = str(opts.get('timestamp_field', '@timestamp'))
        message_field = str(opts.get('message_field', 'message'))
        level_field = str(opts.get('level_field', 'level'))
        raw_bq = opts.get('base_query')
        base_query_template = str(raw_bq) if raw_bq is not None else None
        raw_ef = opts.get('environment_field')
        environment_field = str(raw_ef) if raw_ef else None

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
            environment_field=environment_field,
            environment_value=ctx.environment,
            level_field=level_field,
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

    async def histogram(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        query: LogQuery,
        bucket_count: int = 60,
    ) -> list[LogHistogramBucket]:
        api_token = credentials.get('api_token', '')
        if not api_token:
            raise PluginCredentialsMissing('api_token is required')

        opts = ctx.capability_options
        region, timeout = _connection_opts(ctx)
        timestamp_field = str(opts.get('timestamp_field', '@timestamp'))
        message_field = str(opts.get('message_field', 'message'))
        raw_bq = opts.get('base_query')
        base_query_template = str(raw_bq) if raw_bq is not None else None
        raw_ef = opts.get('environment_field')
        environment_field = str(raw_ef) if raw_ef else None

        ctx_vars: dict[str, str | None] = {
            'environment': ctx.environment,
            'org_slug': ctx.org_slug,
            'project_id': ctx.project_id,
            'project_slug': ctx.project_slug,
        }

        level_field = str(opts.get('level_field', 'level'))

        def _body(level: str | None) -> dict[str, object]:
            return build_histogram_body(
                query,
                base_query=base_query_template,
                bucket_count=bucket_count,
                ctx_vars=ctx_vars,
                message_field=message_field,
                timestamp_field=timestamp_field,
                level_filter=level,
                level_field=level_field,
                environment_field=environment_field,
                environment_value=ctx.environment,
            )

        # Logz.io /v1/search only searches a 2-calendar-day (UTC) window per
        # request.  dayOffset=N shifts the window so that day N and day N+1
        # (counting back from today) are searched.  Step by 2 to get
        # non-overlapping windows that together cover the full requested range.
        today = datetime.datetime.now(datetime.UTC).date()
        end_offset = max(
            0,
            (today - query.end_time.astimezone(datetime.UTC).date()).days,
        )
        start_offset = max(
            0,
            (today - query.start_time.astimezone(datetime.UTC).date()).days,
        )
        day_offsets = list(range(end_offset, start_offset + 2, 2))

        # Fan out: one total query + one per level per day offset.
        level_names = ['ERROR', 'WARN', 'WARNING', 'INFO', 'DEBUG']
        labels: list[str | None] = []
        coros: list[Coroutine[Any, Any, dict[str, object]]] = []
        for lvl in [None, *level_names]:
            body = _body(lvl)
            for offset in day_offsets:
                labels.append(lvl)
                coros.append(
                    post_search(
                        api_token=api_token,
                        body=body,
                        day_offset=offset,
                        region=region,
                        timeout=timeout,
                        version=_VERSION,
                    )
                )

        raw_responses: Sequence[object] = await asyncio.gather(
            *coros, return_exceptions=True
        )
        by_ts = _merge_histogram_totals(
            labels, raw_responses, query.start_time, query.end_time
        )
        _overlay_histogram_levels(labels, raw_responses, by_ts)
        return sorted(by_ts.values(), key=lambda b: b.timestamp)

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


def _parse_histogram(data: dict[str, object]) -> list[LogHistogramBucket]:
    aggs = data.get('aggregations', {})
    if not isinstance(aggs, dict):
        return []
    over_time = cast('dict[str, object]', aggs).get('over_time', {})
    if not isinstance(over_time, dict):
        return []
    raw_buckets_val = cast('dict[str, object]', over_time).get('buckets', [])
    if not isinstance(raw_buckets_val, list):
        return []
    raw_buckets = cast('list[object]', raw_buckets_val)

    buckets: list[LogHistogramBucket] = []
    for raw_item in raw_buckets:
        if not isinstance(raw_item, dict):
            continue
        b = cast('dict[str, object]', raw_item)
        key_ms = b.get('key')
        if not isinstance(key_ms, (int, float)):
            continue
        doc_count = b.get('doc_count', 0)
        count = int(doc_count) if isinstance(doc_count, (int, float)) else 0
        ts = datetime.datetime.fromtimestamp(
            int(key_ms) / 1000, tz=datetime.UTC
        )
        buckets.append(LogHistogramBucket(timestamp=ts, count=count))
    return buckets


def _merge_histogram_totals(
    labels: list[str | None],
    responses: Sequence[object],
    start_time: datetime.datetime,
    end_time: datetime.datetime,
) -> dict[datetime.datetime, LogHistogramBucket]:
    by_ts: dict[datetime.datetime, LogHistogramBucket] = {}
    for label, resp in zip(labels, responses, strict=True):
        if label is not None:
            continue
        if isinstance(resp, Exception):
            LOGGER.warning('Logz.io histogram shard failed: %s', resp)
            continue
        if not isinstance(resp, dict):
            continue
        resp_dict = cast('dict[str, object]', resp)
        for bucket in _parse_histogram(resp_dict):
            if not (start_time <= bucket.timestamp <= end_time):
                continue
            existing = by_ts.get(bucket.timestamp)
            if existing is None:
                by_ts[bucket.timestamp] = bucket
            else:
                by_ts[bucket.timestamp] = existing.model_copy(
                    update={'count': existing.count + bucket.count}
                )
    return by_ts


def _overlay_histogram_levels(
    labels: list[str | None],
    responses: Sequence[object],
    by_ts: dict[datetime.datetime, LogHistogramBucket],
) -> None:
    level_counts: dict[str, dict[datetime.datetime, int]] = {}
    for label, resp in zip(labels, responses, strict=True):
        if label is None:
            continue
        if isinstance(resp, Exception):
            LOGGER.warning(
                'Logz.io histogram level=%s shard failed: %s', label, resp
            )
            continue
        if not isinstance(resp, dict):
            continue
        counts_for_level = level_counts.setdefault(label, {})
        resp_dict = cast('dict[str, object]', resp)
        for bucket in _parse_histogram(resp_dict):
            if bucket.timestamp not in by_ts:
                continue
            counts_for_level[bucket.timestamp] = (
                counts_for_level.get(bucket.timestamp, 0) + bucket.count
            )
    for label, counts_for_level in level_counts.items():
        for ts, count in counts_for_level.items():
            existing = by_ts[ts]
            new_levels = dict(existing.levels)
            new_levels[label] = count
            by_ts[ts] = existing.model_copy(update={'levels': new_levels})


def _connection_opts(ctx: PluginContext) -> tuple[str, float]:
    opts = ctx.integration_options
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


class LogzioPlugin(Plugin):
    """Logz.io plugin package declaration.

    Connection concerns (region, request timeout, and the API token
    credential) live at the Integration level; the query-shaping options
    are scoped to the single ``logs`` capability.
    """

    manifest = PluginManifest(
        slug='logzio',
        name='Logz.io',
        icon='tabler-logs',
        description='Search Logz.io logs from the Imbi project logs tab.',
        api_version=2,
        auth_type='api_token',
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
        capabilities=[
            Capability(
                kind='logs',
                label='Logs',
                description=(
                    'Search Logz.io logs from the Imbi project logs tab.'
                ),
                hints={'supports_histogram': True, 'cacheable': False},
                handler=LogzioLogs,
                options=[
                    PluginOption(
                        name='base_query',
                        label='Base Query Template',
                        type='string',
                        required=False,
                        description=(
                            'Elasticsearch query_string applied as a must '
                            'clause. Supports ${project_slug}, ${org_slug}, '
                            '${environment}, ${project_id}.'
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
                        name='environment_field',
                        label='Environment Field',
                        type='string',
                        required=False,
                        description=(
                            'Log field used to filter by environment. Leave '
                            'blank to disable automatic environment filtering.'
                        ),
                    ),
                    PluginOption(
                        name='default_environments',
                        label='Default Environments',
                        type='string',
                        required=False,
                        description=(
                            'Comma-separated list of environments '
                            'pre-selected in the UI (e.g. '
                            '"production,staging"). Leave blank to use the '
                            "UI's own default."
                        ),
                    ),
                ],
            ),
        ],
    )
