"""Utilities for building hypermedia-style relationship links."""

from imbi_common.models import RelationshipLink


def relationship_link(href: str, count: int) -> RelationshipLink:
    """Build a hypermedia-style relationship link with count."""
    return RelationshipLink(href=href, count=count)


def build_relationships(
    base_url: str,
    links: dict[str, tuple[str, int]],
) -> dict[str, RelationshipLink]:
    """Build a relationships dict from name -> (path_suffix, count).

    `base_url` is typically computed via `request.url_path_for(...)` so
    the configured API prefix is included automatically.
    """
    return {
        name: RelationshipLink(href=f'{base_url}{suffix}', count=count)
        for name, (suffix, count) in links.items()
    }
