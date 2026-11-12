import datetime
import typing
from collections import abc

import orjson
import pydantic

from . import client
from .client import SchemataQuery

__all__ = [
    'SchemataQuery',
    'aclose',
    'as_utc',
    'as_utc_or_none',
    'command',
    'initialize',
    'iso_utc',
    'query',
    'setup_schema',
]


def as_utc(value: datetime.datetime) -> datetime.datetime:
    """Attach UTC to a naive timestamp read back from ClickHouse.

    ``DateTime``/``DateTime64`` columns store UTC but the driver hands
    back naive ``datetime`` objects. Serialized without an offset, a
    client parses them in its *own* zone and the value shifts by that
    zone's offset, so tag the tzinfo on before the value leaves the API.
    Already-aware values pass through untouched.
    """
    return (
        value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value
    )


def as_utc_or_none(value: typing.Any) -> datetime.datetime | None:
    """``as_utc`` for optional row values; ``None`` when absent.

    Row dicts are loosely typed, so callers reading a nullable timestamp
    column would otherwise repeat the ``isinstance`` narrowing.
    """
    return as_utc(value) if isinstance(value, datetime.datetime) else None


def iso_utc(value: datetime.datetime | None) -> str | None:
    """Render a ClickHouse timestamp as an offset-bearing ISO string.

    Returns ``None`` for a missing value. Use in place of ``str(value)``,
    which drops the offset *and* emits a space separator rather than
    ``T`` — a form ``Date.parse`` is not required to accept.
    """
    return as_utc(value).isoformat() if value is not None else None


def _dump(
    model: pydantic.BaseModel, by_alias: bool = True
) -> dict[str, typing.Any]:
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
    model_dict = model.model_dump(by_alias=by_alias)

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


async def command(
    sql: str, parameters: dict[str, typing.Any] | None = None
) -> None:
    """Execute a DDL or DML statement against the Clickhouse database.

    Use this rather than :func:`query` for DDL and DML such as a
    lightweight ``DELETE``: the response body is ignored, so a statement
    that returns no rows (or a per-host status row) does not break the
    row mapping :func:`query` applies.

    Args:
       sql: SQL statement string, possibly with parameter placeholders
       parameters: Optional dictionary of parameter values

    Raises:
       DatabaseError: If there's an error executing the statement
    """
    clickhouse = client.Clickhouse.get_instance()
    await clickhouse.command(sql, parameters=parameters)


async def query(
    sql: str,
    parameters: dict[str, typing.Any] | None = None,
    project_ids: client.ProjectRows | None = None,
    columns: abc.Sequence[str] = ('project_id String',),
    tables: abc.Mapping[str, abc.Sequence[str]] | None = None,
) -> list[dict[str, typing.Any]]:
    """Query the Clickhouse database and return results as a list of dicts.

    Give a list of project IDs as ``project_ids``, not as a bound
    ``Array(String)`` parameter: ClickHouse rejects a bound parameter
    longer than 131072 bytes.  The IDs go as the ``project_ids``
    external table; read them with
    ``project_id IN (SELECT project_id FROM project_ids)``.  Give
    other ID lists as ``tables``, by table name; each is read as
    ``x IN (SELECT id FROM <name>)``.

    Args:
       sql: SQL query string, possibly with parameter placeholders
       parameters: Optional dictionary of parameter values
       project_ids: Optional rows for the ``project_ids`` external table
       columns: The ``name Type`` of each external table column
       tables: More external tables of IDs, by table name

    Returns:
       List of dictionaries mapping column names to values

    Raises:
       DatabaseError: If there's an error executing the query
    """
    clickhouse = client.Clickhouse.get_instance()
    if project_ids is None and not tables:
        return await clickhouse.query(sql, parameters=parameters)
    return await clickhouse.query(
        sql,
        parameters=parameters,
        project_ids=project_ids,
        columns=columns,
        tables=tables,
    )
