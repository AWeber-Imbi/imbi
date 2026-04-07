"""Relationship metadata for graph models.

Replaces ``cypherantic.Relationship`` and ``cypherantic.RelationshipConfig``
with lightweight dataclasses used only as ``typing.Annotated`` metadata
markers.  The graph query functions in this package inspect these markers
to determine how to traverse and populate relationship fields.
"""

import dataclasses
import typing


@dataclasses.dataclass(frozen=True)
class Relationship:
    """Metadata marker for a graph relationship on a Pydantic model field.

    Used with ``typing.Annotated`` to declare that a field represents
    a graph relationship rather than a node property::

        organization: typing.Annotated[
            Organization,
            Relationship(rel_type='BELONGS_TO', direction='OUTGOING'),
        ]

    """

    rel_type: str
    direction: typing.Literal['INCOMING', 'OUTGOING', 'UNDIRECTED']


@dataclasses.dataclass(frozen=True)
class RelationshipConfig:
    """Class-level config for relationship property models.

    Applied as a ``ClassVar`` on Pydantic models that represent
    relationship properties (edge data)::

        class MembershipProperties(pydantic.BaseModel):
            cypherantic_config: ClassVar[RelationshipConfig] = (
                RelationshipConfig(rel_type='MEMBER_OF')
            )
            role: str

    """

    rel_type: str
