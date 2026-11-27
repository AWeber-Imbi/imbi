"""Grafana workflow steps: gather metrics and a metric threshold gate.

The steps query a Prometheus data source through the Grafana data
source query API (``POST /api/ds/query``). The Grafana URL comes from
the Integration ``service_url`` option only, never from the step params.

A query can use ``$project``. When the workflow gives the step a
project, the plugin replaces it with the project's Grafana identifier
(the ``EXISTS_IN`` edge value, ``{slug}-{id}`` by default), for example
``rate(http_requests_total{service="$project"}[5m])``.
"""

import math
import re
import time
import typing
import urllib.parse

import httpx
import pydantic

from imbi.common.plugins import base, errors
from imbi.plugins.grafana import links

#: The maximum number of series that ``gather_metrics`` returns.
MAX_SERIES = 50
#: The maximum number of points in each series.
MAX_POINTS = 500
#: The maximum size of the ``gather_metrics`` output, in bytes. imbi-api
#: refuses a result larger than 1 MiB; this leaves space for the rest.
MAX_BYTES = 1000 * 1024

_TIMEOUT = 30.0

#: The query variable for the project identifier.
_PROJECT = re.compile(r'\$project\b')


def _datasource_field() -> typing.Any:
    return pydantic.Field(
        description='The UID of a Prometheus data source.',
        json_schema_extra={'x-imbi-choices': True},
    )


class GatherMetricsParams(pydantic.BaseModel):
    datasource: str = _datasource_field()
    expr: str = pydantic.Field(
        min_length=1,
        description='A PromQL query. $project is the project identifier.',
    )
    start: str = pydantic.Field(
        default='now-1h', description='Epoch ms or a time like now-1h.'
    )
    end: str = pydantic.Field(
        default='now', description='Epoch ms or a time like now.'
    )
    step_seconds: int = pydantic.Field(default=60, ge=1)


class Series(pydantic.BaseModel):
    labels: dict[str, str]
    #: ``[timestamp_ms, value]`` pairs. The value is ``None`` for a
    #: missing sample, NaN, or Infinity: JSON storage rejects these.
    points: list[tuple[int, float | None]]


class SeriesSummary(pydantic.BaseModel):
    labels: dict[str, str]
    min: float | None
    max: float | None
    last: float | None


class GatherMetricsOutput(pydantic.BaseModel):
    series: list[Series]
    summary: list[SeriesSummary]
    #: True when series or points were dropped to stay in the limits,
    #: including :data:`MAX_BYTES`.
    truncated: bool


class ThresholdParams(pydantic.BaseModel):
    datasource: str = _datasource_field()
    expr: str = pydantic.Field(
        min_length=1,
        description=(
            'A PromQL query that gives one value, e.g. sum(...). '
            '$project is the project identifier.'
        ),
    )
    operator: typing.Literal['lt', 'lte', 'gt', 'gte']
    threshold: pydantic.FiniteFloat


class ThresholdOutput(pydantic.BaseModel):
    value: float


_OPERATORS: dict[str, typing.Callable[[float, float], bool]] = {
    'lt': lambda v, t: v < t,
    'lte': lambda v, t: v <= t,
    'gt': lambda v, t: v > t,
    'gte': lambda v, t: v >= t,
}


async def gather_metrics(
    ctx: base.PluginContext,
    credentials: dict[str, str],
    params: GatherMetricsParams,
    call: base.StepCall,
) -> base.StepResult:
    """Run a Prometheus range query and return the series."""
    series = await _query(
        ctx,
        credentials,
        params.datasource,
        {
            'expr': params.expr,
            'range': True,
            'instant': False,
            'intervalMs': params.step_seconds * 1000,
            'maxDataPoints': MAX_POINTS,
        },
        params.start,
        params.end,
    )
    truncated = len(series) > MAX_SERIES
    kept: list[Series] = []
    for item in series[:MAX_SERIES]:
        truncated = truncated or len(item.points) > MAX_POINTS
        kept.append(
            Series(labels=item.labels, points=item.points[-MAX_POINTS:])
        )
    output = _output(kept, truncated)
    # ponytail: serializes once per dropped series; at most MAX_SERIES.
    while kept and len(output.model_dump_json().encode()) > MAX_BYTES:
        kept.pop()
        output = _output(kept, True)
    return base.StepResult(output=output.model_dump(mode='json'))


def _output(kept: list[Series], truncated: bool) -> GatherMetricsOutput:
    return GatherMetricsOutput(
        series=kept,
        summary=[_summarize(item) for item in kept],
        truncated=truncated,
    )


async def metric_threshold(
    ctx: base.PluginContext,
    credentials: dict[str, str],
    params: ThresholdParams,
    call: base.StepCall,
) -> base.StepResult:
    """Take ``Pass`` when the value meets the condition, else poll."""
    series = await _query(
        ctx,
        credentials,
        params.datasource,
        {'expr': params.expr, 'range': False, 'instant': True},
        'now-5m',
        'now',
    )
    if len(series) > 1:
        raise ValueError(
            f'The query gives {len(series)} series. '
            'Reduce it to one value, for example with sum() or max().'
        )
    points = series[0].points if series else []
    value = points[-1][1] if points else None
    if value is not None and _OPERATORS[params.operator](
        value, params.threshold
    ):
        return base.StepResult(output={'value': value}, port='Pass')
    # No value yet, or the condition is false: try again on the next poll.
    return base.StepResult(poll=True, state={'last': value})


async def datasources(
    ctx: base.PluginContext,
    credentials: dict[str, str],
    field: str,
    params: dict[str, typing.Any],
) -> list[base.Choice]:
    """List the Prometheus data sources of the Grafana organization."""
    data = await request(ctx, credentials, 'GET', '/api/datasources')
    items = typing.cast('list[dict[str, typing.Any]]', data)
    return [
        base.Choice(value=str(item['uid']), label=str(item['name']))
        for item in items
        if item.get('type') == 'prometheus' and item.get('uid')
    ]


def _summarize(series: Series) -> SeriesSummary:
    values = [v for _, v in series.points if v is not None]
    return SeriesSummary(
        labels=series.labels,
        min=min(values) if values else None,
        max=max(values) if values else None,
        last=values[-1] if values else None,
    )


async def _query(
    ctx: base.PluginContext,
    credentials: dict[str, str],
    datasource: str,
    query: dict[str, typing.Any],
    start: str,
    end: str,
) -> list[Series]:
    query = {**query, 'expr': _expand(ctx, query['expr'])}
    # The picker lists only Prometheus data sources; a rendered or saved
    # UID can name another type, so check it before the query.
    found = await request(
        ctx,
        credentials,
        'GET',
        '/api/datasources/uid/' + urllib.parse.quote(datasource, safe=''),
    )
    if typing.cast('dict[str, typing.Any]', found).get('type') != 'prometheus':
        raise ValueError(
            f'The data source {datasource!r} is not a Prometheus data source'
        )
    body = {
        'queries': [
            {'refId': 'A', 'datasource': {'uid': datasource}, **query}
        ],
        'from': start,
        'to': end,
    }
    data = await request(ctx, credentials, 'POST', '/api/ds/query', body)
    result = typing.cast('dict[str, typing.Any]', data)['results']['A']
    if result.get('error'):
        raise ValueError(f'Grafana query failed: {result["error"]}')
    return [s for f in result.get('frames', []) for s in _frame_series(f)]


def _expand(ctx: base.PluginContext, expr: str) -> str:
    """Replace ``$project`` with the project's Grafana identifier."""
    if not _PROJECT.search(expr):
        return expr
    if not ctx.project_id:
        raise ValueError(
            'The query uses $project, but the step has no project_id'
        )
    value = links.identifier(ctx)
    return _PROJECT.sub(lambda _: value, expr)


def _frame_series(frame: dict[str, typing.Any]) -> list[Series]:
    """Convert a data frame (a time field and value fields) to series."""
    fields: list[dict[str, typing.Any]] = frame['schema']['fields']
    columns: list[list[typing.Any]] = frame.get('data', {}).get('values', [])
    times: list[typing.Any] = next(
        (columns[i] for i, f in enumerate(fields) if f.get('type') == 'time'),
        list[typing.Any](),
    )
    series: list[Series] = []
    for i, field in enumerate(fields):
        if field.get('type') != 'number' or i >= len(columns):
            continue
        points = [
            (int(ts), _finite(v))
            for ts, v in zip(times, columns[i], strict=False)
        ]
        labels: dict[str, typing.Any] = field.get('labels') or {}
        series.append(
            Series(
                labels={k: str(v) for k, v in labels.items()},
                points=points,
            )
        )
    return series


def _finite(value: typing.Any) -> float | None:
    """The value as a float, or ``None`` when it is not finite."""
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


async def request(
    ctx: base.PluginContext,
    credentials: dict[str, str],
    method: str,
    path: str,
    body: dict[str, typing.Any] | None = None,
) -> object:
    base_url = str(ctx.integration_options.get('service_url') or '').rstrip(
        '/'
    )
    if not base_url:
        raise errors.PluginCredentialsMissing(
            'The Grafana service_url is not set'
        )
    token = credentials.get('api_token', '').strip()
    if not token:
        raise errors.PluginCredentialsMissing('api_token is required')
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.request(
                method,
                f'{base_url}{path}',
                json=body,
                headers={'Authorization': f'Bearer {token}'},
            )
    except httpx.TimeoutException as exc:
        raise errors.PluginTimeoutError('Grafana request timed out') from exc
    except httpx.RequestError as exc:
        raise errors.PluginUnavailableError(
            f'Grafana request failed: {exc}'
        ) from exc
    status = response.status_code
    if status in (401, 403):
        raise errors.PluginAuthenticationFailed(
            f'Grafana rejected the api_token (status {status})'
        )
    if status == 429:
        retry = response.headers.get('Retry-After', '')
        delay = int(retry) if retry.isdigit() else 60
        raise errors.PluginRateLimited(time.time() + delay)
    if status >= 500:
        raise errors.PluginUnavailableError(
            f'Grafana returned status {status}'
        )
    if status >= 400:
        raise ValueError(f'Grafana returned status {status}: {response.text}')
    try:
        return response.json()
    except ValueError as exc:
        raise errors.PluginUnavailableError(
            'Grafana returned non-JSON'
        ) from exc


class GrafanaSteps(base.WorkflowStepsCapability):
    """A metrics action and a metric threshold gate."""

    @classmethod
    def steps(cls) -> list[base.WorkflowStepDescriptor]:
        return [
            base.WorkflowStepDescriptor.model_validate(
                {
                    'name': 'gather_metrics',
                    'category': 'action',
                    'label': 'Gather metrics',
                    'description': (
                        'Runs a PromQL range query and gives the series '
                        'with their min, max, and last values.'
                    ),
                    'params_model': f'{__name__}:GatherMetricsParams',
                    'output_model': f'{__name__}:GatherMetricsOutput',
                    'sample_output': {
                        'series': [
                            {
                                'labels': {'job': 'api'},
                                'points': [[1700000000000, 0.4]],
                            }
                        ],
                        'summary': [
                            {
                                'labels': {'job': 'api'},
                                'min': 0.4,
                                'max': 0.4,
                                'last': 0.4,
                            }
                        ],
                        'truncated': False,
                    },
                    'callable': f'{__name__}:gather_metrics',
                    'choices': f'{__name__}:datasources',
                }
            ),
            base.WorkflowStepDescriptor.model_validate(
                {
                    'name': 'metric_threshold',
                    'category': 'logic',
                    'label': 'Metric threshold',
                    'description': (
                        'Waits until a PromQL value meets a threshold.'
                    ),
                    'params_model': f'{__name__}:ThresholdParams',
                    'output_model': f'{__name__}:ThresholdOutput',
                    'sample_output': {'value': 0.4},
                    'ports': ('Pass', 'Failed'),
                    'poll_seconds': 60,
                    'timeout_seconds': 1800,
                    'callable': f'{__name__}:metric_threshold',
                    'choices': f'{__name__}:datasources',
                }
            ),
        ]
