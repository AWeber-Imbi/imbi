"""Pydantic models for scoring policies and breakdown results."""

from __future__ import annotations

import json
import typing

import nanoid
import pydantic


class AttributePolicy(pydantic.BaseModel):
    """A scoring policy that maps an attribute value to 0-100."""

    model_config = pydantic.ConfigDict(extra='ignore')

    category: typing.Literal['attribute'] = 'attribute'
    id: str = pydantic.Field(default_factory=nanoid.generate)
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

    # AGE serializes nested objects as JSON strings; parse them back.
    @pydantic.field_validator(
        'value_score_map', 'range_score_map', mode='before'
    )
    @classmethod
    def _parse_json_map(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v

    @pydantic.model_validator(mode='after')
    def _exactly_one_map(self) -> typing.Self:
        has_value_map = self.value_score_map is not None
        has_range_map = self.range_score_map is not None
        if has_value_map == has_range_map:
            raise ValueError(
                'exactly one of value_score_map or range_score_map is required'
            )
        if self.range_score_map is not None:
            _validate_ranges(self.range_score_map)
        return self

    def evaluate(self, value: typing.Any) -> float | None:
        """Map a project value to 0-100; ``None`` if missing/unmapped."""
        if value is None:
            return None
        if self.value_score_map is not None:
            mapped = self.value_score_map.get(str(value))
            return float(mapped) if mapped is not None else None
        if self.range_score_map is not None:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return None
            for key, score in self.range_score_map.items():
                lo, hi = _parse_range(key)
                if lo <= numeric <= hi:
                    return float(score)
            return None
        return None


# Discriminated-union-ready alias; only the attribute variant exists.
ScoringPolicy = AttributePolicy


def _parse_range(key: str) -> tuple[float, float]:
    if '..' not in key:
        raise ValueError(f'invalid range key: {key!r}')
    lo_str, hi_str = key.split('..', 1)
    return float(lo_str), float(hi_str)


def _validate_ranges(ranges: dict[str, int]) -> None:
    parsed: list[tuple[float, float]] = []
    for key in ranges:
        lo, hi = _parse_range(key)
        if not lo < hi:
            raise ValueError(f'range {key!r} must have lo < hi')
        parsed.append((lo, hi))
    parsed.sort()
    for i in range(1, len(parsed)):
        prev_lo, prev_hi = parsed[i - 1]
        cur_lo, _ = parsed[i]
        if cur_lo <= prev_hi:
            raise ValueError(
                f'overlapping ranges: [{prev_lo}, {prev_hi}] and [{cur_lo}, _]'
            )


class AttributeContribution(pydantic.BaseModel):
    policy_slug: str
    attribute_name: str
    value: typing.Any | None = None
    mapped_score: float
    weight: int
    weighted_contribution: float


class ScoreBreakdown(pydantic.BaseModel):
    base_score: float
    unfloored_total: float
    attribute_contributions: list[AttributeContribution] = []
