"""Utilities for building hypermedia-style relationship links."""

import dataclasses

from imbi.common.models import RelationshipLink


@dataclasses.dataclass(frozen=True, slots=True)
class RelationshipSpec:
    """Suffix + count pair consumed by :func:`build_relationships`.

    A typed wrapper instead of a bare ``tuple[str, int]`` so call sites
    can't accidentally swap the positional arguments and pass an int
    where a str was expected. Frozen so it can live in dict literals
    without surprise mutation.
    """

    suffix: str
    count: int


def relationship_link(href: str, count: int) -> RelationshipLink:
    """Build a hypermedia-style relationship link with count."""
    return RelationshipLink(href=href, count=count)


def build_relationships(
    base_url: str,
    links: dict[str, RelationshipSpec],
) -> dict[str, RelationshipLink]:
    """Build a relationships dict from name -> RelationshipSpec.

    `base_url` is typically computed via `request.url_path_for(...)` so
    the configured API prefix is included automatically.
    """
    return {
        name: RelationshipLink(
            href=f'{base_url}{spec.suffix}', count=spec.count
        )
        for name, spec in links.items()
    }
