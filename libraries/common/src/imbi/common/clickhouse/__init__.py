import typing

import orjson
import pydantic
from clickhouse_connect.driver import summary

from . import client
from .client import SchemataQuery

__all__ = [
    'SchemataQuery',
    'aclose',
    'initialize',
    'insert',
    'query',
    'setup_schema',
]


def _dump(model: pydantic.BaseModel) -> dict[str, typing.Any]:
    """
    Dump a Pydantic model to a format compatible with ClickHouse Nested types.

    For fields that contain lists of Pydantic models, this function flattens
    them into separate arrays for each field of the nested model, prefixed
    with the field name.

    Example:
        If model has evidence=[Evidence(type='text', snippet='hello'),
                              Evidence(type='link', snippet='world')]
        Returns: {
            'evidence.type': ['text', 'link'],
            'evidence.snippet': ['hello', 'world'],
            'evidence.translation': ['', ''],
            'evidence.reason': ['', '']
        }
    """
    result: dict[str, typing.Any] = {}
    model_dict = model.model_dump(by_alias=True)

    for field_name, field_value in model_dict.items():
        if isinstance(field_value, list) and field_value:
            if isinstance(field_value[0], dict):
                _process_nested_dicts(result, field_name, field_value)
            else:
                result[field_name] = field_value
        else:
            if hasattr(field_value, 'value'):
                field_value = field_value.value
            result[field_name] = field_value
    return result


def _dumps(model: pydantic.BaseModel) -> str:
    """
    Dump a Pydantic model to a JSON format compatible with ClickHouse
    Nested types.

    For fields that contain lists of Pydantic models, this function flattens
    them into separate arrays for each field of the nested model, prefixed
    with the field name.

    Example:
        If model has evidence=[Evidence(type='text', snippet='hello'),
                              Evidence(type='link', snippet='world')]
        Returns: {
            'evidence.type': ['text', 'link'],
            'evidence.snippet': ['hello', 'world'],
            'evidence.translation': ['', ''],
            'evidence.reason': ['', '']
        }
    """
    json_bytes: bytes = orjson.dumps(_dump(model))
    return json_bytes.decode('utf-8')


def _process_nested_dicts(
    result: dict[str, typing.Any],
    field_name: str,
    field_value: list[dict[str, typing.Any]],
) -> None:
    """Process nested dictionaries for ClickHouse compatibility."""
    all_keys: set[str] = set()
    for item in field_value:
        all_keys.update(item.keys())

    for key in all_keys:
        nested_field_name = f'{field_name}.{key}'
        result[nested_field_name] = []
        for item in field_value:
            value = item.get(key, '')
            if hasattr(value, 'value'):
                value = value.value
            result[nested_field_name].append(value)


async def initialize() -> bool:
    """Create a new async client and test the connection."""
    return await client.Clickhouse.get_instance().initialize()


async def setup_schema() -> None:
    """Execute DDL queries from schemata.toml to set up database schema."""
    await client.Clickhouse.get_instance().setup_schema()


async def aclose() -> None:
    """Close any open connections to Clickhouse."""
    await client.Clickhouse.get_instance().aclose()


async def insert(
    table: str, data: list[pydantic.BaseModel]
) -> summary.QuerySummary:
    """Insert data into Clickhouse.

    Args:
        table: The name of the table to insert into
        data: List of Pydantic models to insert (all must be the same type)

    Returns:
        QuerySummary containing information about the insert operation

    Raises:
        ValueError: If data list is empty or models are not all the same type
    """
    if not data:
        raise ValueError('Data list cannot be empty')

    # Validate all models are of the same type
    first_type = type(data[0])
    if not all(type(model) is first_type for model in data):
        raise ValueError(
            f'All models must be of the same type. '
            f'Expected {first_type.__name__}, but found mixed types.'
        )

    column_names = list(data[0].model_dump().keys())
    clickhouse = client.Clickhouse.get_instance()
    return await clickhouse.insert(
        table,
        [list(model.model_dump().values()) for model in data],
        column_names,
    )


async def query(
    sql: str, parameters: dict[str, typing.Any] | None = None
) -> list[dict[str, typing.Any]]:
    """Query the Clickhouse database and return results as a list of dicts.

    Args:
       sql: SQL query string, possibly with parameter placeholders
       parameters: Optional dictionary of parameter values

    Returns:
       List of dictionaries mapping column names to values

    Raises:
       DatabaseError: If there's an error executing the query
    """
    clickhouse = client.Clickhouse.get_instance()
    return await clickhouse.query(sql, parameters=parameters)
