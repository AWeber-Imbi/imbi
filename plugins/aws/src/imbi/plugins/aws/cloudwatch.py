"""AWS CloudWatch Logs (Insights) LogsPlugin."""

from __future__ import annotations

import asyncio
import datetime
import logging
import typing

from imbi_common.plugins.base import (
    LogEntry,
    LogQuery,
    LogResult,
    LogsPlugin,
    PluginContext,
    PluginManifest,
    PluginOption,
)
from imbi_common.plugins.errors import (
    PluginCredentialsMissing,
    PluginTimeoutError,
    PluginUnavailableError,
)
from imbi_common.plugins.templates import expand_template

from imbi_plugin_aws._helpers import (
    assignment_region,
    assignment_timeout,
    template_vars,
)
from imbi_plugin_aws.aws_session import (
    AwsCredentials,
    call_aws_json,
    resolve_credentials,
)
from imbi_plugin_aws.query import (
    INSIGHTS_LIMIT_CEILING,
    build_query,
    decode_cursor,
    encode_cursor,
    query_fingerprint,
)

LOGGER = logging.getLogger(__name__)

_LOGS_ERROR_MAP: dict[str, type[Exception]] = {
    'AccessDeniedException': PluginCredentialsMissing,
    'UnrecognizedClientException': PluginCredentialsMissing,
    'ExpiredTokenException': PluginCredentialsMissing,
    'InvalidSignatureException': PluginCredentialsMissing,
    'ResourceNotFoundException': ValueError,
    'MalformedQueryException': ValueError,
    'InvalidParameterException': ValueError,
    'LimitExceededException': PluginUnavailableError,
    'ThrottlingException': PluginUnavailableError,
    'InternalServiceError': PluginUnavailableError,
    'ServiceUnavailableException': PluginUnavailableError,
}


def _epoch_seconds(value: datetime.datetime) -> int:
    return int(value.astimezone(datetime.UTC).timestamp())


def _parse_insights_timestamp(value: str) -> datetime.datetime:
    """Insights returns timestamps like ``2024-08-21 12:34:56.789``."""
    text = value.replace('T', ' ').rstrip('Z')
    fmt = '%Y-%m-%d %H:%M:%S.%f' if '.' in text else '%Y-%m-%d %H:%M:%S'
    return datetime.datetime.strptime(text, fmt).replace(tzinfo=datetime.UTC)


def _row_to_dict(
    row: list[dict[str, str]],
) -> dict[str, str]:
    return {
        field['field']: field['value'] for field in row if 'field' in field
    }


class CloudWatchLogsPlugin(LogsPlugin):
    """LogsPlugin backed by CloudWatch Logs Insights."""

    manifest = PluginManifest(
        slug='aws-cloudwatch-logs',
        name='AWS CloudWatch Logs',
        description='Search CloudWatch Logs from the Imbi project logs tab.',
        plugin_type='logs',
        api_version=1,
        cacheable=False,
        options=[
            PluginOption(
                name='region',
                label='AWS Region',
                type='string',
                required=True,
                description='Region holding the project log groups.',
            ),
            PluginOption(
                name='log_group_names',
                label='Log Group Names',
                type='string',
                required=True,
                description=(
                    'Comma-separated list of log group names. Supports '
                    '${project_slug}, ${org_slug}, ${environment}, '
                    '${project_id}. Up to 50 groups per query (Insights '
                    'limit).'
                ),
            ),
            PluginOption(
                name='base_filter',
                label='Base Filter Expression',
                type='string',
                required=False,
                description=(
                    'Logs Insights expression (without leading "filter") '
                    'applied as an additional must clause. Supports the '
                    'same template variables as Log Group Names.'
                ),
            ),
            PluginOption(
                name='message_field',
                label='Message Field',
                type='string',
                default='@message',
            ),
            PluginOption(
                name='timestamp_field',
                label='Timestamp Field',
                type='string',
                default='@timestamp',
            ),
            PluginOption(
                name='level_field',
                label='Level Field',
                type='string',
                default='level',
            ),
            PluginOption(
                name='poll_interval_ms',
                label='Poll Interval (ms)',
                type='integer',
                default=500,
            ),
            PluginOption(
                name='timeout_seconds',
                label='Query Timeout',
                type='integer',
                default=30,
            ),
        ],
        credentials=[],
    )

    async def search(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        query: LogQuery,
    ) -> LogResult:
        creds = resolve_credentials(credentials, region=assignment_region(ctx))
        log_group_names = self._log_groups(ctx)
        message_field = self._option(ctx, 'message_field', '@message')
        timestamp_field = self._option(ctx, 'timestamp_field', '@timestamp')
        level_field = self._option(ctx, 'level_field', 'level')
        base_filter = self._expanded_base_filter(ctx)
        poll_interval = self._poll_interval(ctx)
        timeout = assignment_timeout(ctx, default=30.0)

        fields: list[str] = [timestamp_field, message_field, '@logStream']
        if level_field and level_field not in fields:
            fields.append(level_field)

        capped_limit = max(1, min(query.limit, INSIGHTS_LIMIT_CEILING))
        query_string = build_query(
            base_filter=base_filter,
            filters=query.filters,
            limit=capped_limit,
            timestamp_field=timestamp_field,
            fields=fields,
        )

        fingerprint = query_fingerprint(
            query_string=query_string, log_group_names=log_group_names
        )
        end_time = query.end_time
        if query.cursor:
            cursor_ts = decode_cursor(query.cursor, fingerprint=fingerprint)
            end_time = cursor_ts - datetime.timedelta(milliseconds=1)

        start_body: dict[str, typing.Any] = {
            'queryString': query_string,
            'logGroupNames': log_group_names,
            'startTime': _epoch_seconds(query.start_time),
            'endTime': _epoch_seconds(end_time),
            'limit': capped_limit,
        }
        start_resp = await call_aws_json(
            service='logs',
            action='StartQuery',
            body=start_body,
            credentials=creds,
            error_map=_LOGS_ERROR_MAP,
            timeout=timeout,
        )
        query_id = str(start_resp['queryId'])

        results = await self._poll_results(
            creds=creds,
            query_id=query_id,
            poll_interval=poll_interval,
            timeout=timeout,
        )

        entries = [
            self._row_to_entry(
                row,
                message_field=message_field,
                timestamp_field=timestamp_field,
                level_field=level_field,
            )
            for row in results.get('results', [])
        ]
        next_cursor: str | None = None
        if entries and len(entries) >= capped_limit:
            next_cursor = encode_cursor(
                last_seen=entries[-1].timestamp,
                fingerprint=fingerprint,
            )
        statistics = typing.cast(
            dict[str, typing.Any], results.get('statistics') or {}
        )
        total: int | None = None
        records_matched = statistics.get('recordsMatched')
        if records_matched is not None:
            total = int(records_matched)
        return LogResult(entries=entries, next_cursor=next_cursor, total=total)

    async def _poll_results(
        self,
        *,
        creds: AwsCredentials,
        query_id: str,
        poll_interval: float,
        timeout: float,
    ) -> dict[str, typing.Any]:
        deadline = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            seconds=timeout
        )
        while True:
            response = await call_aws_json(
                service='logs',
                action='GetQueryResults',
                body={'queryId': query_id},
                credentials=creds,
                error_map=_LOGS_ERROR_MAP,
                timeout=timeout,
            )
            status = str(response.get('status', '')).lower()
            if status == 'complete':
                return response
            if status in {'failed', 'cancelled', 'timeout'}:
                raise PluginUnavailableError(
                    f'CloudWatch Logs Insights query {status}'
                )
            if datetime.datetime.now(datetime.UTC) >= deadline:
                await self._stop_query(
                    creds=creds, query_id=query_id, timeout=timeout
                )
                raise PluginTimeoutError(
                    'CloudWatch Logs Insights query timed out'
                )
            await asyncio.sleep(poll_interval)

    async def _stop_query(
        self,
        *,
        creds: AwsCredentials,
        query_id: str,
        timeout: float,
    ) -> None:
        try:
            await call_aws_json(
                service='logs',
                action='StopQuery',
                body={'queryId': query_id},
                credentials=creds,
                error_map=_LOGS_ERROR_MAP,
                timeout=timeout,
            )
        except (PluginUnavailableError, ValueError) as exc:
            LOGGER.debug('StopQuery failed for %s: %s', query_id, exc)

    async def schema(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[dict[str, typing.Any]]:
        baseline: list[dict[str, typing.Any]] = [
            {
                'name': '@timestamp',
                'label': 'Timestamp',
                'type': 'date',
                'builtin': True,
            },
            {
                'name': '@message',
                'label': 'Message',
                'type': 'text',
                'builtin': True,
            },
            {
                'name': '@logStream',
                'label': 'Log Stream',
                'type': 'keyword',
                'builtin': True,
            },
            {
                'name': '@log',
                'label': 'Log Group',
                'type': 'keyword',
                'builtin': True,
            },
            {
                'name': '@requestId',
                'label': 'Request ID',
                'type': 'keyword',
                'builtin': True,
            },
            {'name': 'level', 'label': 'Level', 'type': 'keyword'},
            {'name': 'logger', 'label': 'Logger', 'type': 'keyword'},
            {'name': 'service', 'label': 'Service', 'type': 'keyword'},
            {'name': 'env', 'label': 'Environment', 'type': 'keyword'},
            {
                'name': 'request_id',
                'label': 'Request ID',
                'type': 'keyword',
            },
        ]
        try:
            creds = resolve_credentials(
                credentials, region=assignment_region(ctx)
            )
            response = await call_aws_json(
                service='logs',
                action='DescribeLogGroups',
                body={'limit': 50},
                credentials=creds,
                error_map=_LOGS_ERROR_MAP,
                timeout=assignment_timeout(ctx, default=30.0),
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug('DescribeLogGroups enrichment skipped: %s', exc)
            return baseline
        groups = [
            str(group.get('logGroupName'))
            for group in response.get('logGroups', [])
            if group.get('logGroupName')
        ]
        if groups:
            baseline.append(
                {
                    'name': '@log',
                    'label': 'Log Group',
                    'type': 'keyword',
                    'builtin': True,
                    'choices': groups,
                }
            )
        return baseline

    def _row_to_entry(
        self,
        row: list[dict[str, str]],
        *,
        message_field: str,
        timestamp_field: str,
        level_field: str,
    ) -> LogEntry:
        as_dict = _row_to_dict(row)
        ts_raw = as_dict.get(timestamp_field) or as_dict.get('@timestamp')
        if not ts_raw:
            timestamp = datetime.datetime.now(datetime.UTC)
        else:
            timestamp = _parse_insights_timestamp(ts_raw)
        return LogEntry(
            timestamp=timestamp,
            message=as_dict.get(message_field, ''),
            level=as_dict.get(level_field) if level_field else None,
            raw=dict(as_dict),
        )

    def _log_groups(self, ctx: PluginContext) -> list[str]:
        raw = ctx.assignment_options.get('log_group_names')
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(
                'aws-cloudwatch-logs requires the "log_group_names" '
                'option (comma-separated)'
            )
        expanded = expand_template(raw, template_vars(ctx))
        names = [n.strip() for n in expanded.split(',') if n.strip()]
        if not names:
            raise ValueError(
                'aws-cloudwatch-logs: log_group_names expanded to empty'
            )
        return names

    def _expanded_base_filter(self, ctx: PluginContext) -> str | None:
        raw = ctx.assignment_options.get('base_filter')
        if not raw:
            return None
        return expand_template(str(raw), template_vars(ctx)) or None

    def _option(self, ctx: PluginContext, name: str, default: str) -> str:
        value = ctx.assignment_options.get(name)
        return str(value) if value else default

    def _poll_interval(self, ctx: PluginContext) -> float:
        raw = ctx.assignment_options.get('poll_interval_ms')
        try:
            return float(raw) / 1000.0 if raw is not None else 0.5
        except (TypeError, ValueError):
            return 0.5


__all__ = ['CloudWatchLogsPlugin']
