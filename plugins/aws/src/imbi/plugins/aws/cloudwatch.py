"""AWS CloudWatch Logs (Insights) LogsPlugin."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import hashlib
import json
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
from imbi_plugin_aws.log_groups import (
    LOG_GROUP_NAME_LIMIT,
    SOURCE_PREFIX_LIMIT,
    Entry,
    compile_matcher,
    literal_prefix,
    parse_entries,
)
from imbi_plugin_aws.query import (
    INSIGHTS_LIMIT_CEILING,
    build_query,
    decode_cursor,
    encode_cursor,
    query_fingerprint,
)

LOGGER = logging.getLogger(__name__)


class _ResourceNotFound(ValueError):
    """ResourceNotFoundException from CloudWatch Logs.

    Subclassed off ``ValueError`` for backwards compatibility — the
    plugin's error map historically surfaced this code as a plain
    ``ValueError`` and existing tests / call sites rely on that.  The
    subclass lets the resolve path bust its Valkey cache and retry
    once before propagating.
    """


_LOGS_ERROR_MAP: dict[str, type[Exception]] = {
    'AccessDeniedException': PluginCredentialsMissing,
    'UnrecognizedClientException': PluginCredentialsMissing,
    'ExpiredTokenException': PluginCredentialsMissing,
    'InvalidSignatureException': PluginCredentialsMissing,
    'ResourceNotFoundException': _ResourceNotFound,
    'MalformedQueryException': ValueError,
    'InvalidParameterException': ValueError,
    'LimitExceededException': PluginUnavailableError,
    'ThrottlingException': PluginUnavailableError,
    'InternalServiceError': PluginUnavailableError,
    'ServiceUnavailableException': PluginUnavailableError,
}

_RESOLVE_CACHE_TTL_SECONDS = 300
_DESCRIBE_PAGE_SIZE = 50

# Hard ceiling on DescribeLogGroups pagination so a loose prefix
# (e.g. ``/aws/lambda/`` on an account with millions of groups)
# can't iterate past the request timeout.  100 pages x 50/page →
# 5 000 candidates, well above the 50-cap the matcher truncates to.
_DESCRIBE_PAGE_LIMIT = 100


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


@dataclasses.dataclass
class _Selection:
    """Resolved log group selection for a single ``search()`` call.

    Either ``names`` is set (resolve mode → ``StartQuery`` with an
    explicit ``logGroupNames`` list) or ``source_clause`` is set
    (SOURCE mode → ``logGroupNames`` omitted, prefix selector embedded
    in ``queryString``).  ``cache_keys`` is the list of Valkey keys
    that backed any cached resolves, so the caller can bust them on a
    ``ResourceNotFoundException`` retry.  ``warnings`` surfaces
    truncation / "no matches" notices to the operator.
    """

    names: list[str] | None
    source_clause: str | None
    warnings: list[str]
    cache_keys: list[str]


def _quote_source_string(value: str) -> str:
    """Quote a string literal for a SOURCE clause (single quotes)."""
    escaped = value.replace('\\', '\\\\').replace("'", "\\'")
    return f"'{escaped}'"


def _resolve_cache_key(
    creds: AwsCredentials, pattern: str, *, account_id: str | None
) -> str:
    """Cache key scoped to a stable AWS-account identity, not session.

    IAM IC mints fresh STS keys per session; using ``access_key_id`` as
    the cache scope would cold-cache every reconnect.  When the caller
    can supply ``account_id`` (typically from
    ``ctx.identity.extra['aws_account_id']`` after ``materialize``),
    we scope by it instead — same account → same DescribeLogGroups
    output, regardless of which session is asking.
    """
    pattern_digest = hashlib.sha1(
        pattern.encode(), usedforsecurity=False
    ).hexdigest()
    if account_id:
        scope = f'a:{account_id}'
    else:
        scope = (
            'k:'
            + hashlib.sha1(
                creds.access_key_id.encode(), usedforsecurity=False
            ).hexdigest()[:16]
        )
    return f'cwlogs:{scope}:{creds.region}:{pattern_digest}'


def _account_id_from_ctx(ctx: PluginContext) -> str | None:
    """Pull the resolved AWS account id off ``ctx.identity.extra``.

    IAM IC's ``materialize`` stamps ``aws_account_id`` into
    ``IdentityCredentials.extra`` after picking the env-mapped account,
    so the data plugin can scope its caches to that stable id rather
    than the rotating STS access key.
    """
    if ctx.identity is None:
        return None
    value = ctx.identity.extra.get('aws_account_id')
    return str(value) if value else None


def _try_get_valkey() -> typing.Any | None:
    """Best-effort Valkey client lookup.

    Returns ``None`` when the Valkey lifespan isn't running (plugin
    tests, smoke harnesses) so the resolver degrades to no-cache mode
    instead of failing the whole search.
    """
    try:
        from imbi_common import valkey as common_valkey
    except ImportError:
        return None
    try:
        return common_valkey.get_client()
    except RuntimeError:
        return None
    except Exception:  # noqa: BLE001
        LOGGER.debug('valkey client unavailable', exc_info=True)
        return None


async def _cache_get(client: typing.Any | None, key: str) -> list[str] | None:
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except Exception:  # noqa: BLE001
        LOGGER.debug('valkey GET failed for %s', key, exc_info=True)
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        data: typing.Any = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    items = typing.cast(list[typing.Any], data)
    if all(isinstance(s, str) for s in items):
        return [typing.cast(str, s) for s in items]
    return None


async def _cache_set(
    client: typing.Any | None, key: str, names: list[str]
) -> None:
    if client is None:
        return
    try:
        await client.setex(key, _RESOLVE_CACHE_TTL_SECONDS, json.dumps(names))
    except Exception:  # noqa: BLE001
        LOGGER.debug('valkey SETEX failed for %s', key, exc_info=True)


async def _cache_delete(client: typing.Any | None, keys: list[str]) -> None:
    if client is None or not keys:
        return
    try:
        await client.delete(*keys)
    except Exception:  # noqa: BLE001
        LOGGER.debug('valkey DELETE failed', exc_info=True)


async def _resolve_pattern(
    *,
    creds: AwsCredentials,
    entry: Entry,
    timeout: float,
) -> list[str]:
    """Page DescribeLogGroups by literal prefix and filter by matcher."""
    matcher = compile_matcher(entry.expanded, is_regex=entry.kind == 'regex')
    prefix = literal_prefix(entry.expanded, is_regex=entry.kind == 'regex')
    matches: set[str] = set()
    next_token: str | None = None
    for _ in range(_DESCRIBE_PAGE_LIMIT):
        body: dict[str, typing.Any] = {'limit': _DESCRIBE_PAGE_SIZE}
        if prefix:
            body['logGroupNamePrefix'] = prefix
        if next_token:
            body['nextToken'] = next_token
        resp = await call_aws_json(
            service='logs',
            action='DescribeLogGroups',
            body=body,
            credentials=creds,
            error_map=_LOGS_ERROR_MAP,
            timeout=timeout,
        )
        for group in resp.get('logGroups', []):
            name = group.get('logGroupName')
            if isinstance(name, str) and matcher.match(name):
                matches.add(name)
        next_token = resp.get('nextToken')
        if not next_token:
            break
    else:
        if next_token:
            LOGGER.warning(
                'DescribeLogGroups page limit reached for prefix=%r '
                '(%d pages x %d); truncating early',
                prefix,
                _DESCRIBE_PAGE_LIMIT,
                _DESCRIBE_PAGE_SIZE,
            )
    return sorted(matches)


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
                    'Comma-separated list of log group selectors. '
                    'Supports ${project_slug}, ${org_slug}, '
                    '${environment}, ${project_id}. Each entry can be: '
                    'a literal name; a glob (`*` / `?` / `[...]`); '
                    '`regex:<pattern>` for an explicit regex; or '
                    '`prefix:<name>` for SOURCE-mode prefix selection. '
                    'Glob and regex entries page DescribeLogGroups and '
                    'match client-side (capped at 50 results per query); '
                    '`prefix:` entries use CloudWatch SOURCE selection '
                    'and may not be combined with other entries (max 5).'
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
        creds = resolve_credentials(
            credentials, region=assignment_region(ctx), ctx=ctx
        )
        timeout = assignment_timeout(ctx, default=30.0)
        selection = await self._build_selection(ctx, creds, timeout=timeout)

        if selection.names is not None and not selection.names:
            return LogResult(
                entries=[],
                next_cursor=None,
                total=0,
                warnings=selection.warnings,
            )

        message_field = self._option(ctx, 'message_field', '@message')
        timestamp_field = self._option(ctx, 'timestamp_field', '@timestamp')
        level_field = self._option(ctx, 'level_field', 'level')
        base_filter = self._expanded_base_filter(ctx)
        poll_interval = self._poll_interval(ctx)

        fields: list[str] = [timestamp_field, message_field, '@logStream']
        if level_field and level_field not in fields:
            fields.append(level_field)

        capped_limit = max(1, min(query.limit, INSIGHTS_LIMIT_CEILING))
        base_query_string = build_query(
            base_filter=base_filter,
            filters=query.filters,
            limit=capped_limit,
            timestamp_field=timestamp_field,
            fields=fields,
        )

        start_resp = await self._start_with_cache_bust(
            creds=creds,
            ctx=ctx,
            timeout=timeout,
            selection=selection,
            base_query_string=base_query_string,
            query=query,
            capped_limit=capped_limit,
        )
        # _start_with_cache_bust may have replaced selection on retry.
        selection = start_resp.selection
        if start_resp.empty:
            return LogResult(
                entries=[],
                next_cursor=None,
                total=0,
                warnings=selection.warnings,
            )

        results = await self._poll_results(
            creds=creds,
            query_id=start_resp.query_id,
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
                fingerprint=start_resp.fingerprint,
            )
        statistics = typing.cast(
            dict[str, typing.Any], results.get('statistics') or {}
        )
        total: int | None = None
        records_matched = statistics.get('recordsMatched')
        if records_matched is not None:
            total = int(records_matched)
        return LogResult(
            entries=entries,
            next_cursor=next_cursor,
            total=total,
            warnings=selection.warnings,
        )

    async def _start_with_cache_bust(
        self,
        *,
        creds: AwsCredentials,
        ctx: PluginContext,
        timeout: float,
        selection: _Selection,
        base_query_string: str,
        query: LogQuery,
        capped_limit: int,
    ) -> _StartResult:
        """Build the StartQuery body and dispatch with one bust+retry.

        ``ResourceNotFoundException`` from StartQuery means a name in
        the resolved set no longer exists.  We bust the cached resolves
        and rerun ``_build_selection`` once before propagating.
        """
        body, fingerprint = _start_body(
            selection=selection,
            base_query_string=base_query_string,
            query=query,
            capped_limit=capped_limit,
        )
        try:
            resp = await call_aws_json(
                service='logs',
                action='StartQuery',
                body=body,
                credentials=creds,
                error_map=_LOGS_ERROR_MAP,
                timeout=timeout,
            )
        except _ResourceNotFound:
            if not selection.cache_keys:
                raise
            await _cache_delete(_try_get_valkey(), selection.cache_keys)
            selection = await self._build_selection(
                ctx, creds, timeout=timeout
            )
            if selection.names is not None and not selection.names:
                # Replay path: empty result handled by caller.
                return _StartResult(
                    query_id='',
                    fingerprint='',
                    selection=selection,
                    empty=True,
                )
            body, fingerprint = _start_body(
                selection=selection,
                base_query_string=base_query_string,
                query=query,
                capped_limit=capped_limit,
            )
            resp = await call_aws_json(
                service='logs',
                action='StartQuery',
                body=body,
                credentials=creds,
                error_map=_LOGS_ERROR_MAP,
                timeout=timeout,
            )
        return _StartResult(
            query_id=str(resp['queryId']),
            fingerprint=fingerprint,
            selection=selection,
            empty=False,
        )

    async def _build_selection(
        self,
        ctx: PluginContext,
        creds: AwsCredentials,
        *,
        timeout: float,
    ) -> _Selection:
        raw = ctx.assignment_options.get('log_group_names')
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(
                'aws-cloudwatch-logs requires the "log_group_names" '
                'option (comma-separated)'
            )
        entries = parse_entries(raw, ctx)

        prefix_entries = [e for e in entries if e.kind == 'prefix']
        other_entries = [e for e in entries if e.kind != 'prefix']

        if prefix_entries and other_entries:
            raise ValueError(
                "aws-cloudwatch-logs: cannot combine 'prefix:' selection "
                f'with literal/glob/regex entries '
                f'({other_entries[0].raw!r}); use one mode per query'
            )
        if prefix_entries:
            return _build_source_selection(prefix_entries)
        return await _build_resolve_selection(
            other_entries,
            creds=creds,
            timeout=timeout,
            account_id=_account_id_from_ctx(ctx),
        )

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
                credentials, region=assignment_region(ctx), ctx=ctx
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


@dataclasses.dataclass
class _StartResult:
    query_id: str
    fingerprint: str
    selection: _Selection
    empty: bool


def _start_body(
    *,
    selection: _Selection,
    base_query_string: str,
    query: LogQuery,
    capped_limit: int,
) -> tuple[dict[str, typing.Any], str]:
    if selection.source_clause is not None:
        query_string = f'{selection.source_clause} | {base_query_string}'
        log_groups_for_fp: list[str] = []
    else:
        query_string = base_query_string
        log_groups_for_fp = selection.names or []
    fingerprint = query_fingerprint(
        query_string=query_string,
        log_group_names=log_groups_for_fp,
    )
    end_time = query.end_time
    if query.cursor:
        cursor_ts = decode_cursor(query.cursor, fingerprint=fingerprint)
        end_time = cursor_ts - datetime.timedelta(milliseconds=1)
    body: dict[str, typing.Any] = {
        'queryString': query_string,
        'startTime': _epoch_seconds(query.start_time),
        'endTime': _epoch_seconds(end_time),
        'limit': capped_limit,
    }
    if selection.names is not None:
        body['logGroupNames'] = selection.names
    return body, fingerprint


def _build_source_selection(prefix_entries: list[Entry]) -> _Selection:
    if len(prefix_entries) > SOURCE_PREFIX_LIMIT:
        raise ValueError(
            'aws-cloudwatch-logs: SOURCE namePrefix selection is capped '
            f'at {SOURCE_PREFIX_LIMIT} entries '
            f'({len(prefix_entries)} provided)'
        )
    formatted = ', '.join(
        _quote_source_string(e.expanded) for e in prefix_entries
    )
    clause = f'SOURCE logGroups(namePrefix: [{formatted}])'
    return _Selection(
        names=None, source_clause=clause, warnings=[], cache_keys=[]
    )


async def _build_resolve_selection(
    entries: list[Entry],
    *,
    creds: AwsCredentials,
    timeout: float,
    account_id: str | None,
) -> _Selection:
    client = _try_get_valkey()
    all_names: set[str] = set()
    cache_keys: list[str] = []
    sample_entry: Entry | None = None
    for entry in entries:
        if entry.kind == 'literal':
            all_names.add(entry.expanded)
            continue
        if sample_entry is None:
            sample_entry = entry
        cache_key = _resolve_cache_key(
            creds, entry.expanded, account_id=account_id
        )
        cache_keys.append(cache_key)
        cached = await _cache_get(client, cache_key)
        if cached is None:
            resolved = await _resolve_pattern(
                creds=creds, entry=entry, timeout=timeout
            )
            await _cache_set(client, cache_key, resolved)
        else:
            resolved = cached
        all_names.update(resolved)

    sorted_names = sorted(all_names)
    warnings: list[str] = []
    if len(sorted_names) > LOG_GROUP_NAME_LIMIT:
        total_matches = len(sorted_names)
        sorted_names = sorted_names[:LOG_GROUP_NAME_LIMIT]
        sample = (
            sample_entry.raw if sample_entry is not None else entries[0].raw
        )
        warnings.append(
            f'Pattern {sample!r} matched {total_matches} log groups; '
            f'CloudWatch Logs Insights only allows '
            f'{LOG_GROUP_NAME_LIMIT} per query, so the first '
            f'{LOG_GROUP_NAME_LIMIT} (alphabetical order) were searched.'
        )
    if not sorted_names and sample_entry is not None:
        warnings.append(f'No log groups matched {sample_entry.raw!r}.')
    return _Selection(
        names=sorted_names,
        source_clause=None,
        warnings=warnings,
        cache_keys=cache_keys,
    )


__all__ = ['CloudWatchLogsPlugin']
