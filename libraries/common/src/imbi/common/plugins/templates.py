"""Search template expansion with variable whitelisting."""

import re

_ALLOWED_VARS: frozenset[str] = frozenset(
    {'project_slug', 'org_slug', 'environment', 'project_id'}
)

_VAR_PATTERN = re.compile(r'\$\{([^}]+)\}')


def validate_template(template: str) -> None:
    """Validate a search template string, rejecting unknown variables.

    Raises:
        ValueError: If the template references variables not in the whitelist.
    """
    for match in _VAR_PATTERN.finditer(template):
        var = match.group(1)
        if var not in _ALLOWED_VARS:
            raise ValueError(
                f'Unknown template variable ${{{var}}};'
                f' allowed: {sorted(_ALLOWED_VARS)}'
            )


def expand_template(
    template: str,
    variables: dict[str, str | None],
) -> str:
    """Expand a search template substituting whitelisted variables.

    Absent variable values are replaced with empty strings. The template is
    validated first to reject unknown placeholders, preserving the whitelist
    guarantee from :func:`validate_template`.
    """
    validate_template(template)

    def _sub(match: re.Match[str]) -> str:
        var = match.group(1)
        val = variables.get(var)
        return val if val is not None else ''

    return _VAR_PATTERN.sub(_sub, template)
