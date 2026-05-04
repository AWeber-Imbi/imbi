"""Plugin assignment validation and shared response helpers."""

import typing

from imbi_api.domain import models
from imbi_api.plugins import parse_options


class PluginAssignmentRow(typing.TypedDict):
    plugin_id: str
    tab: typing.Literal['configuration', 'logs']
    default: bool
    options: dict[str, typing.Any]


def validate_one_default_per_tab(
    assignments: list[PluginAssignmentRow],
) -> None:
    """Ensure exactly one default per tab in the assignment list.

    Raises:
        ValueError: If a tab has 0 or >1 defaults.
    """
    by_tab: dict[str, list[bool]] = {}
    for row in assignments:
        by_tab.setdefault(row['tab'], []).append(row['default'])

    for tab, defaults in by_tab.items():
        count = sum(1 for d in defaults if d)
        if count == 0:
            raise ValueError(f'Tab {tab!r} has no default plugin assignment')
        if count > 1:
            raise ValueError(
                f'Tab {tab!r} has {count} default plugin assignments;'
                f' exactly one is required'
            )


def build_assignment_response(
    plugin: dict[str, typing.Any],
    edge: dict[str, typing.Any],
    source: typing.Literal['project', 'project_type', 'merged'],
) -> models.PluginAssignmentResponse:
    """Build a PluginAssignmentResponse from parsed plugin/edge dicts."""
    return models.PluginAssignmentResponse(
        plugin_id=plugin['id'],
        plugin_slug=plugin['plugin_slug'],
        label=plugin['label'],
        tab=edge.get('tab', 'configuration'),
        default=bool(edge.get('default', False)),
        options=parse_options(edge.get('options')),
        source=source,
    )
