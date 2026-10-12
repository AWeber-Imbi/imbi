"""The declaration of a workflow step type (ADR 0021)."""

import builtins
import dataclasses
import typing
from collections import abc

import pydantic

Category = typing.Literal['trigger', 'logic', 'action', 'agent']


def _no_permissions(_params: dict[str, typing.Any]) -> set[str]:
    return set()


@dataclasses.dataclass(frozen=True)
class StepType:
    """One step type. Each module in :mod:`.registry` declares one."""

    type: str
    category: Category
    label: str
    description: str
    params: builtins.type[pydantic.BaseModel]
    output: builtins.type[pydantic.BaseModel]
    sample_output: dict[str, typing.Any]
    #: Output port names. A type with one output has ``('',)``.
    #: ``None`` means one port per entry of ``params.branches``.
    ports: tuple[str, ...] | None = ('',)
    trigger: bool = False
    side_effect: bool = False
    idempotent: bool = True
    required_permissions: abc.Callable[[dict[str, typing.Any]], set[str]] = (
        _no_permissions
    )

    def ports_for(self, params: dict[str, typing.Any]) -> list[str]:
        """Return the output ports of a node of this type."""
        if self.ports is not None:
            return list(self.ports)
        raw: typing.Any = params.get('branches')
        branches: list[typing.Any] = raw if isinstance(raw, list) else []
        return [str(b) for b in branches]

    def describe(self) -> dict[str, typing.Any]:
        """Return the step type as the API serves it."""
        return {
            'type': self.type,
            'category': self.category,
            'label': self.label,
            'description': self.description,
            'trigger': self.trigger,
            'ports': None if self.ports is None else list(self.ports),
            'params_schema': self.params.model_json_schema(),
            'output_schema': self.output.model_json_schema(),
            'sample_output': self.sample_output,
            'side_effect': self.side_effect,
            'idempotent': self.idempotent,
        }
