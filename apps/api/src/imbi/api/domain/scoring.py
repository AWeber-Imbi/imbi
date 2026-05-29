"""API request/response models for scoring."""

from __future__ import annotations

import typing

import pydantic
from imbi_common.scoring import (
    AgePolicy,
    AnalysisResultPolicy,
    AttributeContribution,
    AttributePolicy,
    LinkPresencePolicy,
    PolicyContribution,
    PresencePolicy,
    ScoreBreakdown,
    ScoringPolicy,
)

__all__ = [
    'AgePolicy',
    'AnalysisResultPolicy',
    'AttributeContribution',
    'AttributePolicy',
    'GlobalScoreEvent',
    'LinkPresencePolicy',
    'MonthlyImprovementRow',
    'PolicyContribution',
    'PolicyCreate',
    'PolicyUpdate',
    'PresencePolicy',
    'RescoreRequest',
    'RescoreResponse',
    'ScoreBreakdown',
    'ScoreHistoryByTeamResponse',
    'ScoreHistoryPoint',
    'ScoreHistoryResponse',
    'ScoreRollupRow',
    'ScoreTrend',
    'ScoringPolicy',
    'TeamScoreHistoryPoint',
    'TeamScoreSeries',
]


class PolicyCreate(pydantic.BaseModel):
    """Request body for creating a scoring policy.

    The shape is intentionally loose: the endpoint reshapes this into
    the appropriate ``ScoringPolicy`` discriminated-union variant and
    relies on the variant validator to enforce required fields per
    category.
    """

    model_config = pydantic.ConfigDict(extra='ignore')

    name: str
    slug: str
    description: str | None = None
    category: typing.Literal[
        'attribute', 'presence', 'link_presence', 'age', 'analysis_result'
    ] = 'attribute'
    weight: int = pydantic.Field(ge=0, le=100)
    enabled: bool = True
    priority: int = 0
    targets: list[str] = pydantic.Field(default_factory=list)
    attribute_name: str | None = None
    link_slug: str | None = None
    result_slug: str | None = None
    present_score: int | None = pydantic.Field(default=None, ge=0, le=100)
    missing_score: int | None = pydantic.Field(default=None, ge=0, le=100)
    value_score_map: dict[str, int] | None = None
    range_score_map: dict[str, int] | None = None
    age_score_map: dict[str, int] | None = None
    status_score_map: dict[str, int] | None = None


class PolicyUpdate(pydantic.BaseModel):
    """PATCH body for a scoring policy."""

    model_config = pydantic.ConfigDict(extra='forbid')

    name: str | None = None
    description: str | None = None
    attribute_name: str | None = None
    link_slug: str | None = None
    result_slug: str | None = None
    weight: int | None = pydantic.Field(default=None, ge=0, le=100)
    enabled: bool | None = None
    priority: int | None = None
    value_score_map: dict[str, int] | None = None
    range_score_map: dict[str, int] | None = None
    age_score_map: dict[str, int] | None = None
    status_score_map: dict[str, int] | None = None
    present_score: int | None = pydantic.Field(default=None, ge=0, le=100)
    missing_score: int | None = pydantic.Field(default=None, ge=0, le=100)
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


class GlobalScoreEvent(pydantic.BaseModel):
    timestamp: str
    project_id: str
    project_name: str
    team_key: str
    score: float
    previous_score: float | None = None
    change_reason: str | None = None


class TeamScoreHistoryPoint(pydantic.BaseModel):
    timestamp: str
    score: float


class TeamScoreSeries(pydantic.BaseModel):
    key: str
    points: list[TeamScoreHistoryPoint]


class ScoreHistoryByTeamResponse(pydantic.BaseModel):
    granularity: typing.Literal['hour', 'day']
    teams: list[TeamScoreSeries]


class MonthlyImprovementRow(pydantic.BaseModel):
    dimension: str
    key: str
    current_avg_score: float | None
    previous_avg_score: float | None
    improvement: float | None
    project_count: int
