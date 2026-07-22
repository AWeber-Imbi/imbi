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


#: Maximum nesting depth of a condition tree. Bounds evaluation work and
#: rejects pathological policies. Counts combinator/relationship levels.
_MAX_CONDITION_DEPTH = 6

ConditionOp = typing.Literal[
    'eq', 'ne', 'gt', 'ge', 'lt', 'le', 'present', 'absent'
]
_NUMERIC_OPS = {'gt', 'ge', 'lt', 'le'}
_NO_VALUE_OPS = {'present', 'absent'}


class RelationshipSpec(pydantic.BaseModel):
    """Traverse an edge and test ``where`` against the reached projects.

    v1 supports only outgoing ``DEPENDS_ON`` edges (the projects a project
    depends on). ``quantifier`` reduces the per-neighbour results to one
    boolean: ``any`` (∃ match), ``all`` (∀ match, vacuously true when there
    are no neighbours), ``none`` (no match, vacuously true when empty).
    """

    model_config = pydantic.ConfigDict(extra='ignore')

    edge: typing.Literal['DEPENDS_ON'] = 'DEPENDS_ON'
    direction: typing.Literal['outgoing'] = 'outgoing'
    quantifier: typing.Literal['any', 'all', 'none']
    where: Condition


class Condition(pydantic.BaseModel):
    """A node in a boolean condition tree.

    Exactly one node shape is populated:

    * combinator — ``all`` / ``any`` (lists of child nodes) or ``not``
      (a single child),
    * attribute leaf — ``attribute`` + ``op`` (+ ``value`` unless the op is
      ``present`` / ``absent``), a predicate on the project being scored,
    * relationship leaf — ``relationship``, a predicate on the project's
      outgoing ``DEPENDS_ON`` neighbours.

    ``all``/``any``/``not`` are stored under aliases because they collide
    with Python builtins/keywords.
    """

    model_config = pydantic.ConfigDict(extra='ignore', populate_by_name=True)

    all_: list[Condition] | None = pydantic.Field(default=None, alias='all')
    any_: list[Condition] | None = pydantic.Field(default=None, alias='any')
    not_: Condition | None = pydantic.Field(default=None, alias='not')
    attribute: str | None = None
    op: ConditionOp | None = None
    value: typing.Any = None
    relationship: RelationshipSpec | None = None

    @pydantic.model_validator(mode='after')
    def _exactly_one_shape(self) -> typing.Self:
        anchors = {
            'all': self.all_ is not None,
            'any': self.any_ is not None,
            'not': self.not_ is not None,
            'attribute': self.attribute is not None,
            'relationship': self.relationship is not None,
        }
        set_anchors = [name for name, present in anchors.items() if present]
        if len(set_anchors) != 1:
            raise ValueError(
                'a condition must set exactly one of all/any/not/attribute/'
                f'relationship (got {set_anchors or "none"})'
            )
        if self.all_ is not None and not self.all_:
            raise ValueError('all requires at least one child condition')
        if self.any_ is not None and not self.any_:
            raise ValueError('any requires at least one child condition')
        if self.attribute is not None:
            if not self.attribute:
                raise ValueError(
                    'attribute condition requires a non-empty attribute name'
                )
            if self.op is None:
                raise ValueError('attribute condition requires an op')
            if self.op in _NO_VALUE_OPS and self.value is not None:
                raise ValueError(f'op {self.op!r} takes no value')
            if self.op not in _NO_VALUE_OPS and self.value is None:
                raise ValueError(f'op {self.op!r} requires a value')
        elif self.op is not None or self.value is not None:
            raise ValueError('op/value are only valid on attribute conditions')
        return self


# Resolve the mutual forward references between Condition and
# RelationshipSpec now that both classes exist.
RelationshipSpec.model_rebuild()
Condition.model_rebuild()


class ConditionPolicy(_PolicyBase):
    """Score a project by whether a boolean condition tree holds.

    The tree combines attribute predicates on the project with predicates
    on its outgoing ``DEPENDS_ON`` neighbours (see :class:`Condition`). The
    result maps to ``true_score`` / ``false_score`` and participates as an
    ordinary weighted policy. Unlike the value-mapped categories, it never
    returns ``None`` — quantifiers give an empty neighbour set a definite
    answer, so a condition policy always contributes.
    """

    category: typing.Literal['condition'] = 'condition'
    condition: Condition
    true_score: int = pydantic.Field(default=100, ge=0, le=100)
    false_score: int = pydantic.Field(default=0, ge=0, le=100)

    @pydantic.field_validator('condition', mode='before')
    @classmethod
    def _parse_json_condition(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v

    @pydantic.model_validator(mode='after')
    def _validate_tree(self) -> typing.Self:
        _validate_condition(self.condition)
        return self

    def matches(
        self, project: typing.Any, neighbours: list[typing.Any]
    ) -> bool:
        """Evaluate the condition tree to a boolean."""
        return _eval_condition(self.condition, project, neighbours)

    def evaluate(
        self, project: typing.Any, neighbours: list[typing.Any]
    ) -> float:
        """Map the condition result to ``true_score`` / ``false_score``."""
        result = self.matches(project, neighbours)
        return float(self.true_score if result else self.false_score)


def _validate_condition(
    cond: Condition,
    *,
    depth: int = 1,
    in_relationship: bool = False,
) -> None:
    """Enforce the depth cap and the one-hop (no nested relationship) rule."""
    if depth > _MAX_CONDITION_DEPTH:
        raise ValueError(
            f'condition nesting exceeds max depth {_MAX_CONDITION_DEPTH}'
        )
    if cond.relationship is not None:
        if in_relationship:
            raise ValueError(
                'a relationship condition may not be nested inside another '
                'relationship (transitive scoring is not supported)'
            )
        _validate_condition(
            cond.relationship.where, depth=depth + 1, in_relationship=True
        )
        return
    for child in (cond.all_ or []) + (cond.any_ or []):
        _validate_condition(
            child, depth=depth + 1, in_relationship=in_relationship
        )
    if cond.not_ is not None:
        _validate_condition(
            cond.not_, depth=depth + 1, in_relationship=in_relationship
        )


def _eval_condition(
    cond: Condition, project: typing.Any, neighbours: list[typing.Any]
) -> bool:
    if cond.all_ is not None:
        return all(_eval_condition(c, project, neighbours) for c in cond.all_)
    if cond.any_ is not None:
        return any(_eval_condition(c, project, neighbours) for c in cond.any_)
    if cond.not_ is not None:
        return not _eval_condition(cond.not_, project, neighbours)
    if cond.relationship is not None:
        spec = cond.relationship
        # No transitivity: a neighbour's own neighbours are never traversed.
        per = [_eval_condition(spec.where, n, []) for n in neighbours]
        if spec.quantifier == 'any':
            return any(per)
        if spec.quantifier == 'all':
            return all(per)
        return not any(per)  # 'none'
    return _eval_attribute(cond, project)


def collect_matched_neighbours(
    cond: Condition, neighbours: list[typing.Any]
) -> list[MatchedNeighbour]:
    """Return the neighbours that satisfy a relationship leaf's ``where``.

    Walks the condition tree and, for every relationship leaf, collects the
    outgoing dependencies for which the ``where`` predicate is true (e.g. the
    deprecated dependencies). Results are de-duplicated by project id in
    encounter order. These are the dependencies worth naming in the score
    breakdown regardless of the quantifier.
    """
    matched: dict[str, MatchedNeighbour] = {}

    def walk(node: Condition) -> None:
        if node.all_ is not None:
            for child in node.all_:
                walk(child)
        elif node.any_ is not None:
            for child in node.any_:
                walk(child)
        elif node.not_ is not None:
            walk(node.not_)
        elif node.relationship is not None:
            for neighbour in neighbours:
                if _eval_condition(node.relationship.where, neighbour, []):
                    ref = _neighbour_ref(neighbour)
                    if ref is not None:
                        matched.setdefault(ref.id, ref)

    walk(cond)
    return list(matched.values())


def _neighbour_ref(neighbour: typing.Any) -> MatchedNeighbour | None:
    raw_id = _get_attr(neighbour, 'id')
    if is_missing(raw_id) or raw_id == '':
        return None
    return MatchedNeighbour(
        id=str(raw_id),
        name=_get_attr(neighbour, 'name'),
        slug=_get_attr(neighbour, 'slug'),
    )


def _eval_attribute(cond: Condition, source: typing.Any) -> bool:
    raw = _get_attr(source, cond.attribute or '')
    if cond.op == 'present':
        return not is_missing(raw)
    if cond.op == 'absent':
        return is_missing(raw)
    if cond.op in _NUMERIC_OPS:
        try:
            left = float(raw)
            right = float(cond.value)
        except (TypeError, ValueError):
            return False
        if cond.op == 'gt':
            return left > right
        if cond.op == 'ge':
            return left >= right
        if cond.op == 'lt':
            return left < right
        return left <= right
    equal = _value_key(raw) == _value_key(cond.value)
    return equal if cond.op == 'eq' else not equal


def _get_attr(source: typing.Any, name: str) -> typing.Any:
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


ScoringPolicy = typing.Annotated[
    AttributePolicy
    | PresencePolicy
    | LinkPresencePolicy
    | AgePolicy
    | AnalysisResultPolicy
    | DeploymentStatusPolicy
    | ConditionPolicy,
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


class MatchedNeighbour(pydantic.BaseModel):
    """A dependency that satisfied a condition's relationship predicate.

    Surfaced on :class:`PolicyContribution` so the UI can name *which*
    outgoing dependency triggered a condition (e.g. the deprecated
    service a project depends on) rather than only reporting true/false.
    """

    id: str
    name: str | None = None
    slug: str | None = None


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
        'condition',
    ] = 'attribute'
    attribute_name: str | None = None
    link_slug: str | None = None
    result_slug: str | None = None
    environment_slug: str | None = None
    condition_result: bool | None = None
    matched_neighbours: list[MatchedNeighbour] = []
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
