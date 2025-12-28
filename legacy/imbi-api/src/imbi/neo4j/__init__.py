import contextlib
import logging
import re
import typing

import cypherantic
import neo4j
import pydantic

from . import client

LOGGER = logging.getLogger(__name__)

# TypeVars matching cypherantic's type system
ModelType = typing.TypeVar('ModelType', bound=pydantic.BaseModel)
SourceNode = typing.TypeVar('SourceNode', bound=pydantic.BaseModel)
TargetNode = typing.TypeVar('TargetNode', bound=pydantic.BaseModel)
RelationshipProperties = typing.TypeVar(
    'RelationshipProperties', bound=pydantic.BaseModel
)
EdgeType = typing.TypeVar('EdgeType')


async def aclose() -> None:
    """Close the Neo4j connection"""
    await client.Neo4j.get_instance().aclose()


async def initialize() -> None:
    """Initialize the Neo4j connection, setting up the indexes if necessary."""
    await client.Neo4j.get_instance().initialize()


@contextlib.asynccontextmanager
async def session() -> typing.AsyncGenerator[cypherantic.SessionType, None]:
    """Return a Neo4j AsyncSession for use in queries"""
    instance = client.Neo4j.get_instance()
    async with instance.session() as sess:  # type: ignore
        yield sess


def cypher_property_params(value: dict) -> str:
    """Turn a dict into a Cypher-friendly string of properties for querying"""
    return ', '.join(f'{key}: ${key}' for key in (value or {}).keys())


async def create_node(model: ModelType) -> neo4j.graph.Node:
    """Create a node in the graph.

    This method uses cypherantic to create a node with:
    - Labels extracted from model's ``cypherantic_config`` or class name
    - Automatic unique constraints for fields marked with ``Field(unique=True)``
    - Properties from the model's fields (excluding relationship fields)

    :param model: Pydantic model instance to create as a node
    :returns: The created Neo4j node object

    """
    async with session() as sess:
        return await cypherantic.create_node(sess, model)


@typing.overload
async def create_relationship(
    from_node: SourceNode,
    to_node: TargetNode,
    rel_props: RelationshipProperties,
) -> neo4j.graph.Relationship: ...


@typing.overload
async def create_relationship(
    from_node: SourceNode,
    to_node: TargetNode,
    *,
    rel_type: str,
) -> neo4j.graph.Relationship: ...


async def create_relationship(
    from_node: SourceNode,
    to_node: TargetNode,
    rel_props: RelationshipProperties | None = None,
    *,
    rel_type: str | None = None,
) -> neo4j.graph.Relationship:
    """Create a relationship between two nodes.

    This method creates a relationship by:

    - Matching nodes by their unique key fields (``Field(unique=True)`` metadata)
    - Using relationship type from ``rel_props.cypherantic_config`` or ``rel_type`` parameter
    - Attaching properties from ``rel_props`` model if provided

    Either ``rel_props`` (a Pydantic model with relationship properties and config)
    or ``rel_type`` (a string relationship type) must be provided.

    :param from_node: Source node model instance
    :param to_node: Target node model instance
    :param rel_props: Optional Pydantic model containing relationship properties
    :param rel_type: Optional explicit relationship type name
    :returns: The created Neo4j relationship object

    """
    async with session() as sess:
        return await cypherantic.create_relationship(
            sess, from_node, to_node, rel_props, rel_type=rel_type
        )


async def refresh_relationship(model: SourceNode, rel_property: str) -> None:
    """Lazy-load and populate a relationship property on a model instance.

    This is a lazy-loading mechanism that:

    - Fetches related nodes from the graph based on relationship metadata
    - Populates the specified relationship property on the model instance
    - Validates the property is a Sequence with ``Relationship`` metadata

    The relationship property must be annotated as a sequence type
    (e.g., ``list[EdgeType]``) and have ``Relationship`` metadata that
    specifies the relationship type and direction.

    Use this when you have a model instance and need to populate its
    relationship properties from the graph database.

    :param model: Model instance to populate
    :param rel_property: Name of the relationship property to refresh

    Example::

        from typing import Annotated
        from cypherantic import Relationship

        class Person(NodeModel):
            name: Annotated[str, Field(unique=True)]
            friends: Annotated[
                list[FriendEdge],
                Relationship(rel_type='FRIENDS_WITH', direction='OUTGOING')
            ] = []

        person = Person(name='Alice')
        await refresh_relationship(person, 'friends')
        # person.friends now contains list of FriendEdge instances

    """
    async with session() as sess:
        await cypherantic.refresh_relationship(sess, model, rel_property)


async def retrieve_relationship_edges(
    model: SourceNode,
    rel_name: str,
    direction: typing.Literal['INCOMING', 'OUTGOING', 'UNDIRECTED'],
    edge_cls: type[EdgeType],
) -> list[EdgeType]:
    """Retrieve relationship edges (nodes + properties) from the graph.

    This method fetches related nodes along with their relationship properties,
    returning them as "edge" instances that contain both the target node and
    the relationship properties.

    The ``edge_cls`` must be a type (typically a NamedTuple or dataclass) with:
    - ``node`` attribute: The target node Pydantic model class
    - ``properties`` attribute: The relationship properties Pydantic model class

    :param model: Source node model instance to query from
    :param rel_name: Relationship type name to traverse
    :param direction: Direction to traverse (INCOMING, OUTGOING, or UNDIRECTED)
    :param edge_cls: Edge type class containing node and properties
    :returns: List of edge instances, each containing a node and its relationship properties

    Example::

        from typing import NamedTuple

        class FriendEdge(NamedTuple):
            node: Person
            properties: FriendshipProperties

        person = Person(name='Alice')
        edges = await retrieve_relationship_edges(
            person, 'FRIENDS_WITH', 'OUTGOING', FriendEdge
        )
        for edge in edges:
            print(f"Friend: {edge.node.name}, since: {edge.properties.since}")

    """
    async with session() as sess:
        return await cypherantic.retrieve_relationship_edges(
            sess, model, rel_name, direction, edge_cls
        )


@contextlib.asynccontextmanager
async def run(
    query: str, **parameters: typing.Any
) -> typing.AsyncGenerator[neo4j.AsyncResult, None]:
    """Run a Cypher query and return the result as an AsyncResult"""
    async with session() as sess:
        result = await sess.run(
            typing.cast(typing.LiteralString, re.sub(r'\s+', ' ', query)),
            **parameters,
        )
        yield result


async def upsert(node: pydantic.BaseModel, constraint: dict) -> str:
    """Save a node to the graph, returning the elementId"""
    properties = node.model_dump(by_alias=True)
    labels = node.__class__.__name__.lower()
    assignment = []
    for key in properties.keys():
        assignment.append(f'node.{key} = ${key}')

    parameters = {}
    parameters.update(constraint)
    parameters.update(properties)

    where_props = cypher_property_params(constraint)

    query = (
        f'         MERGE (node:{":".join(labels)} {{{where_props}}})'
        f' ON CREATE SET {", ".join(assignment)}'
        f'  ON MATCH SET {", ".join(assignment)}'
        f'        RETURN elementId(node) AS nodeId'
    ).strip()
    LOGGER.debug('Upsert query: %s', query)
    LOGGER.debug('Upsert parameters: %r', parameters)
    # Upsert the node
    async with run(query, **parameters) as result:
        temp = await result.single()
        return temp['nodeId']
