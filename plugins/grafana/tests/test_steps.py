"""Grafana workflow steps with a mocked Grafana API."""

import json
import typing

import httpx
import pydantic
import pytest
import respx

from imbi.common import plugins
from imbi.common.plugins import base, errors
from imbi.common.workflows import registry
from imbi.plugins.grafana import steps

URL = 'https://grafana.example.com'
CREDS = {'api_token': 'glsa_token'}
CTX = base.PluginContext(
    project_id='',
    project_slug='',
    org_slug='org',
    integration_options={'service_url': f'{URL}/'},
)
CALL = base.StepCall(
    run_id='r', workflow_slug='w', node_id='n', attempt=1, idempotency_key='k'
)


def _frame(labels: dict[str, str], times: list[int], values: list[typing.Any]):
    return {
        'schema': {
            'fields': [
                {'name': 'Time', 'type': 'time'},
                {'name': 'Value', 'type': 'number', 'labels': labels},
            ]
        },
        'data': {'values': [times, values]},
    }


def _results(*frames: dict[str, typing.Any]) -> dict[str, typing.Any]:
    return {'results': {'A': {'status': 200, 'frames': list(frames)}}}


def _threshold(operator: str = 'lt', threshold: float = 1.0):
    return steps.ThresholdParams(
        datasource='prom',
        expr='sum(x)',
        operator=operator,
        threshold=threshold,
    )


def _ds_query(kind: str = 'prometheus') -> respx.Route:
    """The query route. The lookup of ``prom`` gives a ``kind`` source."""
    respx.get(f'{URL}/api/datasources/uid/prom').mock(
        return_value=httpx.Response(200, json={'uid': 'prom', 'type': kind})
    )
    return respx.post(f'{URL}/api/ds/query')


@pytest.mark.parametrize('value', ['NaN', 'inf', '-inf'])
def test_threshold_must_be_finite(value: str) -> None:
    with pytest.raises(pydantic.ValidationError):
        steps.ThresholdParams.model_validate(
            {
                'datasource': 'prom',
                'expr': 'sum(x)',
                'operator': 'lt',
                'threshold': value,
            }
        )


@respx.mock
async def test_query_refuses_other_data_source_types() -> None:
    route = _ds_query('mysql')
    with pytest.raises(ValueError, match='not a Prometheus'):
        await steps.metric_threshold(CTX, CREDS, _threshold(), CALL)
    assert not route.called


@respx.mock
async def test_gather_metrics_stays_in_the_byte_limit() -> None:
    times = list(range(steps.MAX_POINTS))
    frames = [
        _frame({'pad': 'x' * 12000, 'i': str(i)}, times, [1.0] * len(times))
        for i in range(steps.MAX_SERIES)
    ]
    _ds_query().mock(return_value=httpx.Response(200, json=_results(*frames)))
    params = steps.GatherMetricsParams(datasource='prom', expr='up')
    result = await steps.gather_metrics(CTX, CREDS, params, CALL)
    output = steps.GatherMetricsOutput.model_validate(result.output)
    assert len(result.model_dump_json().encode()) <= steps.MAX_BYTES
    assert 0 < len(output.series) < steps.MAX_SERIES
    assert output.truncated is True


def test_plugin_loads_and_registers_steps() -> None:
    result = plugins.load_plugins()
    assert 'grafana' in result.loaded
    assert registry.get('grafana.metric_threshold') is not None
    assert registry.get('grafana.gather_metrics') is not None


@respx.mock
async def test_gather_metrics() -> None:
    route = _ds_query().mock(
        return_value=httpx.Response(
            200,
            json=_results(
                _frame({'job': 'api'}, [1000, 2000, 3000], [3, None, 1])
            ),
        )
    )
    params = steps.GatherMetricsParams(datasource='prom', expr='up')
    result = await steps.gather_metrics(CTX, CREDS, params, CALL)

    request = route.calls.last.request
    assert request.headers['Authorization'] == 'Bearer glsa_token'
    body = json.loads(request.content)
    assert body['from'] == 'now-1h'
    assert body['to'] == 'now'
    assert body['queries'][0]['datasource'] == {'uid': 'prom'}
    assert body['queries'][0]['range'] is True
    assert body['queries'][0]['intervalMs'] == 60000
    output = steps.GatherMetricsOutput.model_validate(result.output)
    assert output.series[0].labels == {'job': 'api'}
    assert len(output.series[0].points) == 3
    assert output.summary[0].model_dump() == {
        'labels': {'job': 'api'},
        'min': 1.0,
        'max': 3.0,
        'last': 1.0,
    }
    assert output.truncated is False


@respx.mock
async def test_gather_metrics_stores_non_finite_values_as_null() -> None:
    _ds_query().mock(
        return_value=httpx.Response(
            200,
            json=_results(
                _frame({}, [1000, 2000, 3000], [None, '+Inf', 'NaN'])
            ),
        )
    )
    params = steps.GatherMetricsParams(datasource='prom', expr='up')
    result = await steps.gather_metrics(CTX, CREDS, params, CALL)
    # PostgreSQL jsonb rejects NaN and Infinity.
    json.dumps(result.output, allow_nan=False)
    assert result.output['series'][0]['points'] == [
        [1000, None],
        [2000, None],
        [3000, None],
    ]


@respx.mock
async def test_gather_metrics_bounds_output() -> None:
    times = list(range(steps.MAX_POINTS + 10))
    frames = [
        _frame({'i': str(i)}, times, [1.0] * len(times))
        for i in range(steps.MAX_SERIES + 1)
    ]
    _ds_query().mock(return_value=httpx.Response(200, json=_results(*frames)))
    params = steps.GatherMetricsParams(datasource='prom', expr='up')
    result = await steps.gather_metrics(CTX, CREDS, params, CALL)
    output = steps.GatherMetricsOutput.model_validate(result.output)
    assert len(output.series) == steps.MAX_SERIES
    assert len(output.series[0].points) == steps.MAX_POINTS
    assert output.truncated is True


@respx.mock
async def test_threshold_pass() -> None:
    route = _ds_query().mock(
        return_value=httpx.Response(200, json=_results(_frame({}, [1], [0.5])))
    )
    result = await steps.metric_threshold(CTX, CREDS, _threshold(), CALL)
    assert result.port == 'Pass'
    assert result.output == {'value': 0.5}
    query = json.loads(route.calls.last.request.content)['queries'][0]
    assert query['instant'] is True


@pytest.mark.parametrize(
    ('operator', 'threshold', 'passes'),
    [('lt', 2, False), ('lte', 2, True), ('gt', 2, False), ('gte', 3, False)],
)
@respx.mock
async def test_threshold_operators(
    operator: str, threshold: float, passes: bool
) -> None:
    _ds_query().mock(
        return_value=httpx.Response(200, json=_results(_frame({}, [1], [2])))
    )
    result = await steps.metric_threshold(
        CTX, CREDS, _threshold(operator, threshold), CALL
    )
    assert (result.port == 'Pass') is passes
    assert result.poll is not passes


@respx.mock
async def test_threshold_polls_with_last_value() -> None:
    _ds_query().mock(
        return_value=httpx.Response(200, json=_results(_frame({}, [1], [5])))
    )
    result = await steps.metric_threshold(CTX, CREDS, _threshold(), CALL)
    assert result.poll is True
    assert result.state == {'last': 5.0}


@pytest.mark.parametrize(
    'payload', [_results(), _results(_frame({}, [1], [None]))]
)
@respx.mock
async def test_threshold_polls_without_value(
    payload: dict[str, typing.Any],
) -> None:
    _ds_query().mock(return_value=httpx.Response(200, json=payload))
    result = await steps.metric_threshold(CTX, CREDS, _threshold(), CALL)
    assert result.poll is True
    assert result.state == {'last': None}


@respx.mock
async def test_threshold_refuses_many_series() -> None:
    _ds_query().mock(
        return_value=httpx.Response(
            200, json=_results(_frame({}, [1], [1]), _frame({}, [1], [2]))
        )
    )
    with pytest.raises(ValueError, match='2 series'):
        await steps.metric_threshold(CTX, CREDS, _threshold(), CALL)


@respx.mock
async def test_query_error_in_result() -> None:
    _ds_query().mock(
        return_value=httpx.Response(
            200, json={'results': {'A': {'error': 'parse error'}}}
        )
    )
    with pytest.raises(ValueError, match='parse error'):
        await steps.metric_threshold(CTX, CREDS, _threshold(), CALL)


@respx.mock
async def test_datasource_choices() -> None:
    respx.get(f'{URL}/api/datasources').mock(
        return_value=httpx.Response(
            200,
            json=[
                {'uid': 'p1', 'name': 'Prometheus', 'type': 'prometheus'},
                {'uid': 'e1', 'name': 'Logs', 'type': 'elasticsearch'},
            ],
        )
    )
    choices = await steps.datasources(CTX, CREDS, 'datasource', {})
    assert choices == [base.Choice(value='p1', label='Prometheus')]


@pytest.mark.parametrize(
    ('status', 'error'),
    [
        (401, errors.PluginAuthenticationFailed),
        (403, errors.PluginAuthenticationFailed),
        (429, errors.PluginRateLimited),
        (502, errors.PluginUnavailableError),
        (400, ValueError),
    ],
)
@respx.mock
async def test_http_errors(status: int, error: type[Exception]) -> None:
    respx.get(f'{URL}/api/datasources').mock(
        return_value=httpx.Response(status, text='nope')
    )
    with pytest.raises(error):
        await steps.datasources(CTX, CREDS, 'datasource', {})


@respx.mock
async def test_timeout() -> None:
    respx.get(f'{URL}/api/datasources').mock(
        side_effect=httpx.ReadTimeout('x')
    )
    with pytest.raises(errors.PluginTimeoutError):
        await steps.datasources(CTX, CREDS, 'datasource', {})


async def test_missing_config() -> None:
    with pytest.raises(errors.PluginCredentialsMissing):
        await steps.datasources(CTX, {}, 'datasource', {})
    ctx = CTX.model_copy(update={'integration_options': {}})
    with pytest.raises(errors.PluginCredentialsMissing):
        await steps.datasources(ctx, CREDS, 'datasource', {})
