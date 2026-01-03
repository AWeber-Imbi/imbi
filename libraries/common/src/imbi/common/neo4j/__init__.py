import contextlib
import logging
import re
import typing

import cypherantic
import neo4j
import pydantic
import pydantic_core

from . import client

LOGGER = logging.getLogger(__name__)


def convert_neo4j_types(data: typing.Any) -> typing.Any:
    """Convert Neo4j-specific types to Python native types.

    Args:
        data: Data to convert (can be dict, list, or primitive type)

    Returns:
        Data with Neo4j types converted to Python native types
    """
    if isinstance(data, dict):
        return {key: convert_neo4j_types(value) for key, value in data.items()}
    if isinstance(data, list):
        return [convert_neo4j_types(item) for item in data]
    # Duck-typing: check for to_native() (Neo4j types and mocks)
    if hasattr(data, 'to_native') and callable(data.to_native):
        return data.to_native()
    return data


def _prepare_node_data(
    model_cls: type[pydantic.BaseModel], node_data: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """Prepare node data for model validation by handling relationship fields.

    Relationship fields are not stored as node properties in Neo4j, so we need
    to provide default values for them to avoid validation errors.

    Args:
        model_cls: The Pydantic model class
        node_data: Dictionary of node properties from Neo4j

    Returns:
        Dictionary with relationship fields set to defaults
    """
    prepared_data = node_data.copy()

    # Check each field in the model
    for field_name, field_info in model_cls.model_fields.items():
        # Skip fields that already have data
        if field_name in prepared_data:
            continue

        # Check if this is a relationship field
        is_relationship = any(
            isinstance(md, cypherantic.Relationship)
            for md in field_info.metadata
        )

        if is_relationship:
            # Use the field's default if available, otherwise None
            if field_info.default is not pydantic_core.PydanticUndefined:
                prepared_data[field_name] = field_info.default
            elif field_info.default_factory is not None and callable(
                field_info.default_factory
            ):
                prepared_data[field_name] = field_info.default_factory()  # type: ignore[call-arg]
            else:
                # No default, set to None (will fail if field is required)
                prepared_data[field_name] = None

    return prepared_data


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
    async with instance.session() as sess:
        yield sess


async def create_node(model: ModelType) -> ModelType:
    """Create a node in the graph.

    This method uses cypherantic to create a node with:
    - Labels extracted from model's ``cypherantic_config`` or class name
    - Automatic unique constraints for fields marked with
      ``Field(unique=True)``
    - Properties from the model's fields (excluding relationship fields)

    :param model: Pydantic model instance to create as a node
    :returns: The created node as a Pydantic model with round-trip values

    """
    async with session() as sess:
        node = await cypherantic.create_node(sess, model)
        node_props = convert_neo4j_types(dict(node))
        # Use model_copy to preserve relationship fields from original model
        # while updating scalar properties with values from Neo4j
        return model.model_copy(update=node_props)


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

    - Matching nodes by their unique key fields
      (``Field(unique=True)`` metadata)
    - Using relationship type from ``rel_props.cypherantic_config``
      or ``rel_type`` parameter
    - Attaching properties from ``rel_props`` model if provided

    Either ``rel_props`` (a Pydantic model with relationship properties
    and config) or ``rel_type`` (a string relationship type) must be
    provided.

    :param from_node: Source node model instance
    :param to_node: Target node model instance
    :param rel_props: Optional Pydantic model containing relationship
        properties
    :param rel_type: Optional explicit relationship type name
    :returns: The created Neo4j relationship object

    """
    async with session() as sess:
        if rel_props is not None:
            return await cypherantic.create_relationship(
                sess, from_node, to_node, rel_props
            )
        elif rel_type is not None:
            return await cypherantic.create_relationship(
                sess, from_node, to_node, rel_type=rel_type
            )
        else:
            raise ValueError('Either rel_props or rel_type must be provided')


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

    The ``edge_cls`` must be a type (typically a NamedTuple or dataclass)
    with:
    - ``node`` attribute: The target node Pydantic model class
    - ``properties`` attribute: The relationship properties Pydantic
      model class

    :param model: Source node model instance to query from
    :param rel_name: Relationship type name to traverse
    :param direction: Direction to traverse (INCOMING, OUTGOING, or
        UNDIRECTED)
    :param edge_cls: Edge type class containing node and properties
    :returns: List of edge instances, each containing a node and its
        relationship properties

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
        return typing.cast(
            list[EdgeType],
            await cypherantic.retrieve_relationship_edges(
                sess, model, rel_name, direction, edge_cls
            ),
        )


@contextlib.asynccontextmanager
async def run(
    query: str, **parameters: typing.Any
) -> typing.AsyncGenerator[neo4j.AsyncResult, None]:
    """Run a Cypher query and return the result as an AsyncResult"""
    async with session() as sess:
        result = await sess.run(
            re.sub(r'\s+', ' ', query),
            **parameters,
        )
        yield result


def _cypher_property_params(value: dict[str, typing.Any]) -> str:
    """Turn a dict into a Cypher-friendly string of properties for querying"""
    return ', '.join(f'{key}: ${key}' for key in (value or {}).keys())


# Public alias for backward compatibility
cypher_property_params = _cypher_property_params


def _build_fetch_query(
    model: type[pydantic.BaseModel] | str,
    parameters: dict[str, typing.Any] | None = None,
    order_by: str | list[str] | None = None,
) -> str:
    """Build a query to fetch nodes from the graph by its unique key fields"""
    name = model.__name__ if isinstance(model, type) else model
    query = f'MATCH (node:{name}'
    if parameters:
        query += f' {{{_cypher_property_params(parameters)}}}'
    query += ') RETURN node'
    if order_by:
        if isinstance(order_by, list):
            order_by = ', '.join(f'node.{key}' for key in order_by)
        elif isinstance(order_by, str):
            order_by = f'node.{order_by}'
        query += f' ORDER BY {order_by}'
    return query


async def fetch_node(
    model: type[ModelType],
    parameters: dict[str, typing.Any],
) -> ModelType | None:
    """Fetch a single node from the graph by its unique key fields"""
    query = _build_fetch_query(model, parameters)
    LOGGER.debug('Running Query: %s', query)
    async with run(query, **parameters) as result:
        record = await result.single()
    if record:
        node_data = convert_neo4j_types(record.data()['node'])
        prepared_data = _prepare_node_data(model, node_data)
        return model.model_validate(prepared_data)
    return None


async def fetch_nodes(
    model: type[ModelType],
    parameters: dict[str, typing.Any] | None = None,
    order_by: str | list[str] | None = None,
) -> typing.AsyncGenerator[ModelType, None]:
    """Fetch nodes from the graph, optionally filtered by parameters"""
    query = _build_fetch_query(model, parameters, order_by)
    LOGGER.debug('Running Query: %s', query)
    async with run(query, **parameters or {}) as result:
        async for record in result:
            node_data = convert_neo4j_types(record.data()['node'])
            prepared_data = _prepare_node_data(model, node_data)
            yield model.model_validate(prepared_data)


async def upsert(
    node: pydantic.BaseModel, constraint: dict[str, typing.Any]
) -> str:
    """Save a node to the graph, returning the elementId"""
    properties = node.model_dump(by_alias=True)
    labels = node.__class__.__name__.lower()
    assignment = []
    for key in properties.keys():
        assignment.append(f'node.{key} = ${key}')

    parameters = {}
    parameters.update(constraint)
    parameters.update(properties)

    where_props = _cypher_property_params(constraint)

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
        record = await result.single()
        if record is None:
            raise ValueError('Upsert query returned no results')
        return str(record['nodeId'])


async def delete_node(
    model: type[pydantic.BaseModel],
    parameters: dict[str, typing.Any],
) -> bool:
    """Delete a node from the graph by matching parameters.

    This method deletes a node that matches the given parameters.
    The node label is extracted from the model class name (lowercase).

    :param model: Pydantic model class (label extracted from class name)
    :param parameters: Dict of properties to match
        (e.g., ``{'slug': 'my-slug', 'type': 'Project'}``)
    :returns: True if node was deleted, False if not found

    Example::

        from imbi_common import models, neo4j

        # Delete a blueprint by slug and type
        deleted = await neo4j.delete_node(
            models.Blueprint,
            {'slug': 'my-blueprint', 'type': 'Project'}
        )
        if deleted:
            print('Blueprint deleted successfully')
        else:
            print('Blueprint not found')

    """
    label = model.__name__.lower()
    where_clauses = [f'node.{key} = ${key}' for key in parameters]
    where_clause = ' AND '.join(where_clauses)

    query = f"""
     MATCH (node:{label})
     WHERE {where_clause}
    DETACH DELETE node
    RETURN count(node) as deleted
    """

    LOGGER.debug('Delete query: %s', query)
    LOGGER.debug('Delete parameters: %r', parameters)

    async with run(query, **parameters) as result:
        record = await result.single()
        return record is not None and record['deleted'] > 0
