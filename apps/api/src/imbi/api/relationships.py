"""Utilities for building hypermedia-style relationship links."""

from imbi_common.models import RelationshipLink


def relationship_link(href: str, count: int) -> RelationshipLink:
    """Build a hypermedia-style relationship link with count."""
    return RelationshipLink(href=href, count=count)
