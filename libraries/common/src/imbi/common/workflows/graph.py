"""The graph and settings of a workflow version (ADR 0021)."""

import typing

import pydantic

#: The pattern of a node key. A reference names a node by its key.
KEY_PATTERN = r'^[a-z][a-z0-9_]*$'


class Position(pydantic.BaseModel):
    x: float
    y: float


class Node(pydantic.BaseModel):
    id: str = pydantic.Field(min_length=1)
    key: str = pydantic.Field(pattern=KEY_PATTERN)
    type: str = pydantic.Field(min_length=1)
    title: str
    position: Position
    params: dict[str, typing.Any] = {}
    join: typing.Literal['any', 'all'] = 'any'


class Edge(pydantic.BaseModel):
    """An edge from output ``port`` of ``source`` to ``target``."""

    source: str
    port: int = pydantic.Field(ge=0)
    target: str


class Graph(pydantic.BaseModel):
    nodes: list[Node] = []
    edges: list[Edge] = []


class Settings(pydantic.BaseModel):
    concurrency_mode: typing.Literal[
        'unlimited', 'one_at_a_time', 'one_per_key'
    ] = 'unlimited'
    #: A reference to a trigger value, such as ``{{ trigger.service }}``.
    #: Used only with ``one_per_key``.
    concurrency_key: str | None = None
    max_run_time_seconds: int = pydantic.Field(default=7200, gt=0)
    on_failure: typing.Literal['notify_owner_team', 'none'] = (
        'notify_owner_team'
    )


class ValidationIssue(pydantic.BaseModel):
    severity: typing.Literal['error', 'warning']
    code: str
    message: str
    node_id: str | None = None
    edge_index: int | None = None


class ValidationResult(pydantic.BaseModel):
    issues: list[ValidationIssue] = []
