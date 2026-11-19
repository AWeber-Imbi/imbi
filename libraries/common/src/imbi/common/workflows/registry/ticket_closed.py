"""Ticket closed trigger: a ticket that closes starts a run (ADR 0028).

The new name of :mod:`.task_completed`, with the same parameters and
output. Both types stay registered: saved ``task_completed`` bindings
keep working, and imbi-api starts the runs of both
(:mod:`imbi.api.workflows.ticket_trigger`).
"""

import dataclasses

from imbi.common.workflows.registry import task_completed

STEP = dataclasses.replace(
    task_completed.STEP,
    type='ticket_closed',
    label='Ticket closed',
    description='A ticket that closes starts a run.',
)

#: Both names of the trigger. Readers accept both.
TYPES = (task_completed.STEP.type, STEP.type)
