"""Pydantic models for scoring policies and breakdown results."""

from __future__ import annotations

import datetime
import json
import re
import typing

import nanoid
import pydantic

_DURATION_RE = re.compile(r'^(\d+(?:\.\d+)?)\s*([smhdw])$')
_THRESHOLD_RE = re.compile(r'^(>=|>|<=|<|==)\s*(.+)$')
_DURATION_UNITS = {
    's': 1.0,
    'm': 60.0,
    'h': 3600.0,
    'd': 86400.0,
    'w': 604800.0,
}


class _PolicyBase(pydantic.BaseModel):
    """Fields shared by every scoring policy category."""

    model_config = pydantic.ConfigDict(extra='ignore')

    id: str = pydantic.Field(default_factory=nanoid.generate)
    name: str
    slug: str
    description: str | None = None
    weight: int = pydantic.Field(ge=0, le=100)
    enabled: bool = True
    priority: int = 0
    targets: list[str] = pydantic.Field(default_factory=list)


class AttributePolicy(_PolicyBase):
    """Map an attribute value to 0-100 via a value or range table."""

    category: typing.Literal['attribute'] = 'attribute'
    attribute_name: str
    value_score_map: dict[str, int] | None = None
    range_score_map: dict[str, int] | None = None

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
            mapped = self.value_score_map.get(_value_key(value))
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


class PresencePolicy(_PolicyBase):
    """Score based on whether an attribute is present (non-empty)."""

    category: typing.Literal['presence'] = 'presence'
    attribute_name: str
    present_score: int = pydantic.Field(default=100, ge=0, le=100)
    missing_score: int = pydantic.Field(default=0, ge=0, le=100)

    def evaluate(self, value: typing.Any) -> float:
        """Return ``present_score`` when *value* is non-empty."""
        return float(
            self.missing_score if is_missing(value) else self.present_score
        )


class LinkPresencePolicy(_PolicyBase):
    """Score based on whether a project has a link of *link_slug*."""

    category: typing.Literal['link_presence'] = 'link_presence'
    link_slug: str
    present_score: int = pydantic.Field(default=100, ge=0, le=100)
    missing_score: int = pydantic.Field(default=0, ge=0, le=100)

    def evaluate(self, links: typing.Any) -> float:
        """Return ``present_score`` when *links* contains a value for the
        configured slug."""
        if not isinstance(links, dict):
            return float(self.missing_score)
        value = links.get(self.link_slug)
        return float(
            self.missing_score if is_missing(value) else self.present_score
        )


#: Status emitted by an :class:`AnalysisResultItem`. Duplicated here to
#: avoid importing the plugins package from scoring (which would invert
#: the existing dependency direction).
AnalysisResultStatusLiteral = typing.Literal['pass', 'warn', 'fail']


class AnalysisResultPolicy(_PolicyBase):
    """Score a project by the status of a specific analysis result.

    The scoring engine looks up the project's latest
    ``AnalysisResult`` whose ``slug`` matches ``result_slug``, then
    maps the result's ``status`` to a 0-100 score via
    ``status_score_map``. When no matching result exists,
    :meth:`evaluate` returns ``None`` (consistent with how the
    attribute / age categories treat missing data).
    """

    category: typing.Literal['analysis_result'] = 'analysis_result'
    result_slug: str
    status_score_map: dict[AnalysisResultStatusLiteral, int] = pydantic.Field(
        default_factory=lambda: typing.cast(
            'dict[AnalysisResultStatusLiteral, int]',
            {'pass': 100, 'warn': 50, 'fail': 0},
        )
    )

    @pydantic.field_validator('status_score_map', mode='before')
    @classmethod
    def _parse_json_status_map(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v

    @pydantic.model_validator(mode='after')
    def _validate_status_map(self) -> typing.Self:
        for score in self.status_score_map.values():
            if not 0 <= score <= 100:
                raise ValueError(
                    'status_score_map values must be between 0 and 100'
                )
        return self

    def evaluate(self, status: typing.Any) -> float | None:
        """Map an :class:`AnalysisResultItem` status to its score."""
        if status is None:
            return None
        key = str(status)
        if key not in ('pass', 'warn', 'fail'):
            return None
        mapped = self.status_score_map.get(
            typing.cast('AnalysisResultStatusLiteral', key)
        )
        return float(mapped) if mapped is not None else None


#: Status carried by a ``DeploymentEvent`` on a
#: ``Release -[:DEPLOYED_TO]-> Environment`` edge. Duplicated here as a
#: plain literal to avoid importing the models module into the scoring
#: package (which would invert the dependency direction).
DeploymentStatusLiteral = typing.Literal[
    'pending',
    'in_progress',
    'success',
    'failed',
    'rolled_back',
]


class DeploymentStatusPolicy(_PolicyBase):
    """Score a project by its latest deployment status in an environment.

    The scoring engine resolves the project's current deployment status
    in ``environment_slug`` — the ``status`` of the most recent
    ``DeploymentEvent`` across the project's releases deployed there —
    then maps it to a 0-100 score via ``status_score_map``.

    The synthetic ``'missing'`` key scores environments the project has
    not deployed to yet (default 100, i.e. no penalty). A status present
    on the edge but absent from the map falls back to the ``'missing'``
    score, so omitting a status (e.g. ``'rolled_back'``) can never
    implicitly score it 0.
    """

    category: typing.Literal['deployment_status'] = 'deployment_status'
    environment_slug: str
    status_score_map: dict[str, int] = pydantic.Field(
        default_factory=lambda: {
            'success': 100,
            'in_progress': 100,
            'pending': 100,
            'failed': 0,
            'missing': 100,
        }
    )

    @pydantic.field_validator('status_score_map', mode='before')
    @classmethod
    def _parse_json_status_map(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v

    @pydantic.model_validator(mode='after')
    def _validate_status_map(self) -> typing.Self:
        for score in self.status_score_map.values():
            if not 0 <= score <= 100:
                raise ValueError(
                    'status_score_map values must be between 0 and 100'
                )
        return self

    def evaluate(self, status: typing.Any) -> float | None:
        """Map a deployment status to its score.

        ``status`` is ``None`` when the project has no deployment in the
        target environment; that resolves through the ``'missing'`` key.
        A status with no explicit entry also falls back to ``'missing'``.
        Returns ``None`` only when neither the status nor ``'missing'`` is
        mapped, letting the engine treat it like any other absent value.
        """
        key = 'missing' if status is None else str(status)
        mapped = self.status_score_map.get(key)
        if mapped is None and key != 'missing':
            mapped = self.status_score_map.get('missing')
        return float(mapped) if mapped is not None else None


class AgePolicy(_PolicyBase):
    """Score based on age of a datetime attribute.

    ``age_score_map`` keys use the same threshold DSL the UI's
    ``color-age`` map uses: operator (``<``, ``<=``, ``==``, ``>``,
    ``>=``) followed by a duration with unit ``s``/``m``/``h``/``d``/``w``
    (e.g. ``">90d"``, ``"<=7d"``). The elapsed seconds since *value*
    is compared to each threshold in document order; **first match wins**.

    Because Python preserves ``dict`` insertion order, the order keys
    appear in ``age_score_map`` is significant — list the most specific
    or highest-priority thresholds first. For example, to score a stale
    item ``0`` only when older than 30 days but ``50`` between 7 and 30
    days, put ``">30d"`` before ``">7d"``.
    """

    category: typing.Literal['age'] = 'age'
    attribute_name: str
    age_score_map: dict[str, int]

    @pydantic.field_validator('age_score_map', mode='before')
    @classmethod
    def _parse_json_age_map(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v

    @pydantic.model_validator(mode='after')
    def _validate_age_map(self) -> typing.Self:
        if not self.age_score_map:
            raise ValueError('age_score_map must be non-empty')
        for key in self.age_score_map:
            entry = _parse_age_key(key)
            if entry is None:
                raise ValueError(f'invalid age threshold key: {key!r}')
        return self

    def evaluate(
        self,
        value: typing.Any,
        *,
        now: datetime.datetime | None = None,
    ) -> float | None:
        """Resolve the score for the configured date attribute.

        Returns ``None`` when *value* is missing or unparseable so the
        engine can treat it consistently with the other categories.
        """
        if value is None:
            return None
        parsed = _coerce_datetime(value)
        if parsed is None:
            return None
        reference = (
            now if now is not None else datetime.datetime.now(datetime.UTC)
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.UTC)
        elapsed = (reference - parsed).total_seconds()
        for key, score in self.age_score_map.items():
            entry = _parse_age_key(key)
            if entry is None:
                continue
            op, threshold = entry
            if _compare(op, elapsed, threshold):
                return float(score)
        return None


ScoringPolicy = typing.Annotated[
    AttributePolicy
    | PresencePolicy
    | LinkPresencePolicy
    | AgePolicy
    | AnalysisResultPolicy
    | DeploymentStatusPolicy,
    pydantic.Field(discriminator='category'),
]


def is_missing(value: typing.Any) -> bool:
    """Return True when *value* should be treated as absent for scoring."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _value_key(value: typing.Any) -> str:
    """Normalize a project value to a ``value_score_map`` lookup key.

    Booleans need special handling: ``str(True)`` is ``'True'`` but
    policy maps store the JSON-style lowercase ``'true'``/``'false'``.
    AGE persists some boolean attributes as real booleans and others as
    the strings ``'true'``/``'false'``; lowercasing only ``bool`` lets
    both representations match the same map keys without disturbing
    case-sensitive string values such as ``'GitHub Actions'``.
    """
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


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


def _parse_age_key(key: str) -> tuple[str, float] | None:
    match = _THRESHOLD_RE.match(key)
    if not match:
        return None
    op = match.group(1)
    duration_match = _DURATION_RE.match(match.group(2).strip())
    if not duration_match:
        return None
    amount = float(duration_match.group(1))
    unit = _DURATION_UNITS[duration_match.group(2)]
    return op, amount * unit


def _coerce_datetime(value: typing.Any) -> datetime.datetime | None:
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(
            value, datetime.time(0, 0), tzinfo=datetime.UTC
        )
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # fromisoformat handles trailing 'Z' starting in Python 3.11+ but
        # we normalize defensively for older serializations.
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        try:
            return datetime.datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def _compare(op: str, value: float, threshold: float) -> bool:
    if op == '<':
        return value < threshold
    if op == '<=':
        return value <= threshold
    if op == '==':
        return value == threshold
    if op == '>':
        return value > threshold
    if op == '>=':
        return value >= threshold
    return False


class PolicyContribution(pydantic.BaseModel):
    """Per-policy contribution to a project's base score."""

    policy_slug: str
    category: typing.Literal[
        'attribute',
        'presence',
        'link_presence',
        'age',
        'analysis_result',
        'deployment_status',
    ] = 'attribute'
    attribute_name: str | None = None
    link_slug: str | None = None
    result_slug: str | None = None
    environment_slug: str | None = None
    value: typing.Any | None = None
    mapped_score: float
    weight: int
    weighted_contribution: float


# Back-compat alias for callers that imported the old name.
AttributeContribution = PolicyContribution


class ScoreBreakdown(pydantic.BaseModel):
    """Result of scoring a project across all applicable policies."""

    base_score: float
    unfloored_total: float
    attribute_contributions: list[PolicyContribution] = []
