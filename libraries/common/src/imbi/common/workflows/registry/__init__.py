"""The workflow step types (ADR 0021).

One module per type. A type that is not here fails validation, so a
type is added only when the engine can execute it.
"""

from imbi.common.workflows.registry import (
    agent,
    deploy,
    email,
    manual,
    model_decision,
    rollback,
    schedule,
    task_completed,
    wait,
    webhook,
)
from imbi.common.workflows.step_type import StepType

STEP_TYPES: dict[str, StepType] = {
    module.STEP.type: module.STEP
    for module in (
        manual,
        schedule,
        webhook,
        task_completed,
        wait,
        model_decision,
        email,
        deploy,
        rollback,
        agent,
    )
}
