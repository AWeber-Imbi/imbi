"""The workflow step types (ADR 0021).

One module per type. A type that is not here fails validation, so a
type is added only when the engine can execute it.
"""

from imbi.common.workflows.registry import (
    agent,
    condition,
    deploy,
    email,
    llm_call,
    manual,
    model_decision,
    rollback,
    schedule,
    script,
    slack,
    ticket_state_changed,
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
        ticket_state_changed,
        wait,
        model_decision,
        llm_call,
        condition,
        script,
        email,
        slack,
        deploy,
        rollback,
        agent,
    )
}
