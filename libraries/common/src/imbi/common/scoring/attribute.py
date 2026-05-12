"""Base score: weighted average across all policy categories."""

from __future__ import annotations

import typing

from imbi_common.scoring.models import (
    AgePolicy,
    AttributePolicy,
    LinkPresencePolicy,
    PolicyContribution,
    PresencePolicy,
)

Policy = AttributePolicy | PresencePolicy | LinkPresencePolicy | AgePolicy


def compute_base_score(
    project: typing.Any,
    policies: list[Policy],
) -> tuple[float, list[PolicyContribution]]:
    """Compute base score and per-policy contributions.

    No applicable policies → score is 100. Missing or unmapped values
    contribute a mapped score of 0 to the weighted average.
    """
    if not policies:
        return 100.0, []

    total_weight = sum(p.weight for p in policies)
    contributions: list[PolicyContribution] = []
    weighted_sum = 0.0
    for policy in policies:
        value, mapped = _evaluate(project, policy)
        score = 0.0 if mapped is None else mapped
        weighted_sum += score * policy.weight
        if total_weight > 0:
            weighted_contribution = score * policy.weight / total_weight
        else:
            weighted_contribution = 0.0
        contributions.append(
            PolicyContribution(
                policy_slug=policy.slug,
                category=policy.category,
                attribute_name=getattr(policy, 'attribute_name', None),
                link_slug=getattr(policy, 'link_slug', None),
                value=value,
                mapped_score=score,
                weight=policy.weight,
                weighted_contribution=weighted_contribution,
            )
        )
    if total_weight == 0:
        return 0.0, contributions
    return weighted_sum / total_weight, contributions


def _evaluate(
    project: typing.Any, policy: Policy
) -> tuple[typing.Any, float | None]:
    if isinstance(policy, LinkPresencePolicy):
        links = _get_value(project, 'links') or {}
        if isinstance(links, dict):
            sample = links.get(policy.link_slug)
        else:
            sample = None
        return sample, policy.evaluate(links)
    value = _get_value(project, policy.attribute_name)
    if isinstance(policy, PresencePolicy):
        return value, policy.evaluate(value)
    if isinstance(policy, AgePolicy):
        return value, policy.evaluate(value)
    return value, policy.evaluate(value)


def _get_value(project: typing.Any, name: str) -> typing.Any:
    if isinstance(project, dict):
        return project.get(name)
    return getattr(project, name, None)
