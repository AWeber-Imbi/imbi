"""API request/response models for scoring."""

from __future__ import annotations

import typing

import pydantic
from imbi_common.scoring import (
    AttributeContribution,
    AttributePolicy,
    ScoreBreakdown,
    ScoringPolicy,
)

__all__ = [
    'AttributeContribution',
    'AttributePolicy',
    'PolicyCreate',
    'PolicyUpdate',
    'RescoreRequest',
    'RescoreResponse',
    'ScoreBreakdown',
    'ScoreHistoryPoint',
    'ScoreHistoryResponse',
    'ScoreRollupRow',
    'ScoreTrend',
    'ScoringPolicy',
]


class PolicyCreate(pydantic.BaseModel):
    """Request body for creating a scoring policy."""

    model_config = pydantic.ConfigDict(extra='forbid')

    name: str
    slug: str
    description: str | None = None
    attribute_name: str
    weight: int = pydantic.Field(ge=0, le=100)
    enabled: bool = True
    priority: int = 0
    value_score_map: dict[str, int] | None = None
    range_score_map: dict[str, int] | None = None
    targets: list[str] = pydantic.Field(default_factory=list)


class PolicyUpdate(pydantic.BaseModel):
    """PATCH body for a scoring policy."""

    model_config = pydantic.ConfigDict(extra='forbid')

    name: str | None = None
    description: str | None = None
    attribute_name: str | None = None
    weight: int | None = pydantic.Field(default=None, ge=0, le=100)
    enabled: bool | None = None
    priority: int | None = None
    value_score_map: dict[str, int] | None = None
    range_score_map: dict[str, int] | None = None
    targets: list[str] | None = None


class RescoreRequest(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='forbid')

    project_id: str | None = None
    project_type_slug: str | None = None
    blueprint_slug: str | None = None
    policy_slug: str | None = None


class RescoreResponse(pydantic.BaseModel):
    enqueued: int


class ScoreTrend(pydantic.BaseModel):
    current: float | None
    previous: float | None
    delta: float | None
    period_days: int


class ScoreHistoryPoint(pydantic.BaseModel):
    timestamp: str
    score: float
    previous_score: float | None = None
    change_reason: str | None = None


class ScoreHistoryResponse(pydantic.BaseModel):
    project_id: str
    granularity: typing.Literal['raw', 'hour', 'day']
    points: list[ScoreHistoryPoint]


class ScoreRollupRow(pydantic.BaseModel):
    dimension: str
    key: str
    latest_score: float
    avg_score: float
    last_updated: str | None = None
