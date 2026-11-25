"""Read and write the Home tab preferences through imbi-api.

The preferences are in the ``slack_home`` namespace of
``/users/me/preferences``. Each write sends the version that the bot
read. On a 409 (someone else wrote first), the bot reads again and
applies its one change again, one time.

"""

from __future__ import annotations

import dataclasses
import typing

import httpx

SectionKey = typing.Literal[
    'needs_attention',
    'my_tickets',
    'pull_requests',
    'merged_not_deployed',
    'release_drift',
    'my_projects',
    'agent_activity',
    'document_comments',
]
Display = typing.Literal['expanded', 'collapsed', 'hidden']

DISPLAYS: tuple[Display, ...] = typing.get_args(Display)
DEFAULT_ORDER: tuple[SectionKey, ...] = typing.get_args(SectionKey)
TITLES: dict[SectionKey, str] = {
    'needs_attention': 'Needs attention',
    'my_tickets': 'My tickets',
    'pull_requests': 'Pull requests',
    'merged_not_deployed': 'Merged, not deployed',
    'release_drift': 'Release drift',
    'my_projects': 'My projects',
    'agent_activity': 'Agent activity',
    'document_comments': 'Document comments',
}
#: The section that a user can collapse but not hide.
PINNED: SectionKey = 'needs_attention'
PATH = '/users/me/preferences/slack_home'


@dataclasses.dataclass
class Prefs:
    """The Home tab preferences of a user, with ``version`` 0 when the
    API has none stored."""

    org_slug: str | None = None
    order: list[SectionKey] = dataclasses.field(
        default_factory=lambda: list(DEFAULT_ORDER)
    )
    sections: dict[str, Display] = dataclasses.field(default_factory=dict)
    hide_empty: bool = True
    max_items: int = 5
    count_expanded_only: bool = False
    version: int = 0

    def display(self, key: SectionKey) -> Display:
        return self.sections.get(key, 'expanded')

    def value(self) -> dict[str, typing.Any]:
        """Return the ``value`` body of a write."""
        return {
            'org_slug': self.org_slug,
            'order': self.order,
            'sections': {k: {'display': v} for k, v in self.sections.items()},
            'hide_empty': self.hide_empty,
            'max_items': self.max_items,
            'count_expanded_only': self.count_expanded_only,
        }


def parse(body: dict[str, typing.Any]) -> Prefs:
    """Return the preferences of a GET or PUT response body."""
    value: dict[str, typing.Any] = body.get('value') or {}
    stored: list[str] = value.get('order') or []
    # The stored order first, then the keys that it does not have.
    order = sorted(
        DEFAULT_ORDER,
        key=lambda k: stored.index(k) if k in stored else len(stored),
    )
    sections: dict[str, dict[str, Display]] = value.get('sections') or {}
    return Prefs(
        org_slug=value.get('org_slug'),
        order=order,
        sections={
            k: v['display']
            for k, v in sections.items()
            if k in DEFAULT_ORDER and v.get('display') in DISPLAYS
        },
        hide_empty=bool(value.get('hide_empty', True)),
        max_items=10 if value.get('max_items') == 10 else 5,
        count_expanded_only=bool(value.get('count_expanded_only', False)),
        version=int(body.get('version') or 0),
    )


async def read(client: httpx.AsyncClient) -> Prefs:
    """Return the stored preferences, or the defaults on a 404."""
    response = await client.get(PATH)
    if response.status_code == 404:
        return Prefs()
    response.raise_for_status()
    return parse(response.json())


async def change(
    client: httpx.AsyncClient, apply: typing.Callable[[Prefs], None]
) -> Prefs:
    """Apply ``apply`` to the stored preferences and write them.

    Raises :class:`httpx.HTTPStatusError` when the API refuses the
    write, also after the one retry on a 409.

    """
    for attempt in range(2):
        current = await read(client)
        apply(current)
        response = await client.put(
            PATH, json={'value': current.value(), 'version': current.version}
        )
        if response.status_code == 409 and attempt == 0:
            continue
        response.raise_for_status()
        return parse(response.json())
    raise AssertionError('unreachable')  # pragma: no cover


def move(prefs: Prefs, key: SectionKey, step: int) -> None:
    """Move ``key`` past the next section that is not hidden, up for
    ``step`` -1 and down for 1."""
    order = prefs.order
    i = order.index(key)
    j = i + step
    while 0 <= j < len(order) and prefs.display(order[j]) == 'hidden':
        j += step
    if 0 <= j < len(order):
        order.insert(j, order.pop(i))


def set_display(prefs: Prefs, key: SectionKey, display: Display) -> None:
    if key == PINNED and display == 'hidden':
        return
    prefs.sections[key] = display
