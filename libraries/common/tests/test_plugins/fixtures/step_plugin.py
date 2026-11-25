"""A plugin with workflow steps: one action and one polling gate."""

import typing

import pydantic

from imbi.common.plugins import base

_FIX = 'libraries.common.tests.test_plugins.fixtures.step_plugin'


class QueryParams(pydantic.BaseModel):
    datasource: str = pydantic.Field(
        json_schema_extra={'x-imbi-choices': True}
    )
    query: str


class QueryOutput(pydantic.BaseModel):
    value: float


class ThresholdParams(pydantic.BaseModel):
    query: str
    below: float


class ThresholdOutput(pydantic.BaseModel):
    value: float


async def run_query(
    ctx: base.PluginContext,
    credentials: dict[str, str],
    params: QueryParams,
    call: base.StepCall,
) -> base.StepResult:
    return base.StepResult(output={'value': 1.0})


async def run_threshold(
    ctx: base.PluginContext,
    credentials: dict[str, str],
    params: ThresholdParams,
    call: base.StepCall,
) -> base.StepResult:
    return base.StepResult(output={'value': 1.0}, port='Pass')


async def datasources(
    ctx: base.PluginContext,
    credentials: dict[str, str],
    field: str,
    params: dict[str, typing.Any],
) -> list[base.Choice]:
    return [base.Choice(value='prom', label='Prometheus')]


def query_descriptor(**overrides: typing.Any) -> base.WorkflowStepDescriptor:
    return base.WorkflowStepDescriptor.model_validate(
        {
            'name': 'gather_metrics',
            'category': 'action',
            'label': 'Gather metrics',
            'description': 'Runs a metrics query.',
            'params_model': f'{_FIX}:QueryParams',
            'output_model': f'{_FIX}:QueryOutput',
            'sample_output': {'value': 1.0},
            'callable': f'{_FIX}:run_query',
            'choices': f'{_FIX}:datasources',
            **overrides,
        }
    )


def threshold_descriptor(
    **overrides: typing.Any,
) -> base.WorkflowStepDescriptor:
    return base.WorkflowStepDescriptor.model_validate(
        {
            'name': 'metric_threshold',
            'category': 'logic',
            'label': 'Metric threshold',
            'description': 'Waits until a metric is below a value.',
            'params_model': f'{_FIX}:ThresholdParams',
            'output_model': f'{_FIX}:ThresholdOutput',
            'sample_output': {'value': 1.0},
            'ports': ('Pass', 'Failed'),
            'poll_seconds': 60,
            'timeout_seconds': 3600,
            'project_scoped': True,
            'callable': f'{_FIX}:run_threshold',
            **overrides,
        }
    )


class StepperSteps(base.WorkflowStepsCapability):
    @classmethod
    def steps(cls) -> list[base.WorkflowStepDescriptor]:
        return [query_descriptor(), threshold_descriptor()]


class StepperPlugin(base.Plugin):
    manifest = base.PluginManifest(
        slug='stepper',
        name='Stepper',
        icon='si-grafana',
        capabilities=[
            base.Capability(
                kind='workflow-steps',
                label='Workflow steps',
                project_scoped=False,
                handler=StepperSteps,
            )
        ],
    )


PLUGIN = StepperPlugin
