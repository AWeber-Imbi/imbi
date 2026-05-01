"""Phase-1 base score: weighted average of attribute policies."""

from __future__ import annotations

import typing

from imbi_common.scoring.models import (
    AttributeContribution,
    AttributePolicy,
)


def compute_base_score(
    project: typing.Any,
    policies: list[AttributePolicy],
) -> tuple[float, list[AttributeContribution]]:
    """Compute base score and per-policy contributions.

    No applicable policies → score is 100. Missing or unmapped
    values contribute a mapped score of 0 to the weighted average.
    """
    if not policies:
        return 100.0, []

    total_weight = sum(p.weight for p in policies)
    contributions: list[AttributeContribution] = []
    weighted_sum = 0.0
    for policy in policies:
        value = _get_value(project, policy.attribute_name)
        mapped = policy.evaluate(value)
        score = 0.0 if mapped is None else mapped
        weighted_sum += score * policy.weight
        if total_weight > 0:
            weighted_contribution = score * policy.weight / total_weight
        else:
            weighted_contribution = 0.0
        contributions.append(
            AttributeContribution(
                policy_slug=policy.slug,
                attribute_name=policy.attribute_name,
                value=value,
                mapped_score=score,
                weight=policy.weight,
                weighted_contribution=weighted_contribution,
            )
        )
    if total_weight == 0:
        return 0.0, contributions
    return weighted_sum / total_weight, contributions


def _get_value(project: typing.Any, name: str) -> typing.Any:
    if isinstance(project, dict):
        return project.get(name)
    return getattr(project, name, None)
