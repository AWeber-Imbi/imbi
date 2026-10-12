"""Model decision: a decision model picks one branch."""

import pydantic

from imbi.common.workflows import step_type


class Params(pydantic.BaseModel):
    model_id: str = pydantic.Field(
        min_length=1, description='A decision model of the AI Model catalog.'
    )
    prompt: str = pydantic.Field(min_length=1)
    context: str | None = None
    min_confidence: float = pydantic.Field(default=0.7, ge=0, le=1)
    branches: list[str] = pydantic.Field(
        min_length=2,
        description='One output port per branch. Below min_confidence, '
        'the step takes the last branch.',
    )


class Output(pydantic.BaseModel):
    choice: str
    probability: float
    reasoning: str | None = None


STEP = step_type.StepType(
    type='model_decision',
    category='logic',
    label='Model decision',
    description='A decision model picks one branch.',
    params=Params,
    output=Output,
    sample_output={
        'choice': 'yes',
        'probability': 0.9,
        'reasoning': 'Sample output of a test run.',
    },
    ports=None,
    timeout_seconds=60,
    retries=2,
)
