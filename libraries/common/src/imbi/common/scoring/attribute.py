"""Base score: weighted average across all policy categories."""

from __future__ import annotations

import json
import typing

from imbi.common.scoring.models import (
    AgePolicy,
    AnalysisResultPolicy,
    AttributePolicy,
    ConditionPolicy,
    DeploymentStatusPolicy,
    LinkPresencePolicy,
    PolicyContribution,
    PresencePolicy,
    collect_matched_neighbours,
)

Policy = (
    AttributePolicy
    | PresencePolicy
    | LinkPresencePolicy
    | AgePolicy
    | AnalysisResultPolicy
    | DeploymentStatusPolicy
    | ConditionPolicy
)


def compute_base_score(
    project: typing.Any,
    policies: list[Policy],
    analysis_results: dict[str, str] | None = None,
    deployment_statuses: dict[str, str] | None = None,
    neighbours: list[typing.Any] | None = None,
) -> tuple[float, list[PolicyContribution]]:
    """Compute base score and per-policy contributions.

    No applicable policies → score is 100. Missing or unmapped values
    contribute a mapped score of 0 to the weighted average.

    ``analysis_results`` is a ``{result_slug: status}`` mapping
    pre-loaded from the project's latest analysis report. Required for
    ``AnalysisResultPolicy`` evaluation; unused by the other categories.

    ``deployment_statuses`` is a ``{environment_slug: status}`` mapping
    of the project's latest deployment status per environment. Required
    for ``DeploymentStatusPolicy`` evaluation; an environment absent from
    the mapping is scored through the policy's ``'missing'`` key.

    ``neighbours`` is the list of outgoing ``DEPENDS_ON`` neighbour
    property maps. Required for ``ConditionPolicy`` evaluation; an empty
    list is resolved through the relationship quantifier semantics.
    """
    if not policies:
        return 100.0, []

    results = analysis_results or {}
    deployments = deployment_statuses or {}
    deps = neighbours or []
    total_weight = sum(p.weight for p in policies)
    contributions: list[PolicyContribution] = []
    weighted_sum = 0.0
    for policy in policies:
        value, mapped = _evaluate(project, policy, results, deployments, deps)
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
                result_slug=getattr(policy, 'result_slug', None),
                environment_slug=getattr(policy, 'environment_slug', None),
                condition_result=value
                if isinstance(policy, ConditionPolicy)
                else None,
                matched_neighbours=collect_matched_neighbours(
                    policy.condition, deps
                )
                if isinstance(policy, ConditionPolicy)
                else [],
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
    project: typing.Any,
    policy: Policy,
    analysis_results: dict[str, str],
    deployment_statuses: dict[str, str],
    neighbours: list[typing.Any],
) -> tuple[typing.Any, float | None]:
    if isinstance(policy, ConditionPolicy):
        result = policy.matches(project, neighbours)
        return result, float(
            policy.true_score if result else policy.false_score
        )
    if isinstance(policy, LinkPresencePolicy):
        raw = _get_value(project, 'links')
        # AGE stores dict properties as JSON strings. model_validate normally
        # decodes them via the field validator on Project, but if
        # model_construct was used as a fallback (due to any other field
        # failing validation), the value arrives here as a raw string.
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = {}
        links: dict[str, typing.Any] = raw or {}
        sample = (
            links.get(policy.link_slug) if isinstance(links, dict) else None
        )
        return sample, policy.evaluate(links)
    if isinstance(policy, AnalysisResultPolicy):
        status = analysis_results.get(policy.result_slug)
        return status, policy.evaluate(status)
    if isinstance(policy, DeploymentStatusPolicy):
        status = deployment_statuses.get(policy.environment_slug)
        return status, policy.evaluate(status)
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
