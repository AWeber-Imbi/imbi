import datetime
import logging
import typing

import orjson
import pydantic

from . import client
from .client import SchemataQuery

LOGGER = logging.getLogger(__name__)

__all__ = [
    'PARAM_BYTE_BUDGET',
    'SchemataQuery',
    'aclose',
    'as_utc',
    'as_utc_or_none',
    'command',
    'initialize',
    'iso_utc',
    'param_entry_cost',
    'project_id_batches',
    'project_ids_param',
    'query',
    'query_batched',
    'query_project_batches',
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


#: Byte budget for a single ``Array(String)`` query parameter.
#:
#: ``clickhouse.query()`` binds parameters through clickhouse-connect,
#: which sends each one as an HTTP *form field*.  ClickHouse caps a field
#: value at ``http_max_field_value_size`` -- 131072 bytes by default --
#: and rejects anything longer with ``HTML Form Exception: Field value
#: too long``.  Note this is *half* of ``max_query_size``, so a payload
#: that looks safe against the query limit still fails here: measured
#: against production, 2978 forty-character shas (~131032 bytes) pass and
#: 2979 fail.  The budget is set to half the server default so a cluster
#: configured below the default, or one org's tag count growing between
#: releases, still leaves headroom.
PARAM_BYTE_BUDGET = 65536


def param_entry_cost(value: str) -> int:
    """Bytes one array entry adds to a bound query parameter.

    clickhouse-connect serializes an array as ``['a', 'b']``, so an
    entry costs its own bytes plus two quotes and the ``", "``
    separator.  Measured in UTF-8 bytes because the server counts the
    *decoded* field value: the observed failure threshold was 2979
    forty-character shas (2979 * 44 = 131076 > 131072), which matches
    the decoded length and rules out percent-encoding counting toward
    the limit.  Counting the separator for the final entry too, and
    ignoring the enclosing brackets, keeps the estimate on the safe side
    of the encoder.
    """
    return len(value.encode()) + 4


def project_id_batches(project_ids: list[str]) -> list[list[str]]:
    """Split project IDs into batches within :data:`PARAM_BYTE_BUDGET`."""
    if not project_ids:
        return []
    batches: list[list[str]] = [[]]
    size = 0
    for pid in project_ids:
        if batches[-1] and size + param_entry_cost(pid) > PARAM_BYTE_BUDGET:
            batches.append([])
            size = 0
        batches[-1].append(pid)
        size += param_entry_cost(pid)
    return batches


def project_ids_param(batch: list[str]) -> dict[str, typing.Any]:
    return {'project_ids': batch}


async def query_project_batches(
    sql: str,
    project_ids: list[str],
    what: str,
    params: typing.Callable[[list[str]], dict[str, typing.Any]] = (
        project_ids_param
    ),
    failed: set[str] | None = None,
) -> list[dict[str, typing.Any]]:
    """Run ``sql`` once per project-ID batch and return all rows.

    One query that carries every project ID in the organization exceeds
    the ClickHouse form-field limit (see :data:`PARAM_BYTE_BUDGET`).
    ``params`` builds the bound parameters for one batch.  A failed
    batch logs a warning and drops only its own projects.  When you
    give ``failed``, it gets the IDs of the failed batches.
    """
    rows: list[dict[str, typing.Any]] = []
    for batch in project_id_batches(project_ids):
        try:
            rows.extend(await query(sql, params(batch)))
        except Exception:  # noqa: BLE001 -- best-effort enrichment
            if failed is not None:
                failed.update(batch)
            LOGGER.warning(
                'Failed to fetch %s for %d projects',
                what,
                len(batch),
                exc_info=True,
            )
    return rows


async def query_batched(
    sql: str,
    project_ids: list[str],
    parameters: dict[str, typing.Any] | None = None,
) -> list[dict[str, typing.Any]]:
    """Run ``sql`` once per project-ID batch and return all rows.

    Binds each batch as ``project_ids``; ``parameters`` holds the other
    bound values.  Unlike :func:`query_project_batches`, an error is
    not caught.  Rows that aggregate across projects (sums, distinct
    counts, ``LIMIT``) come back once per batch, so the caller must
    merge them.
    """
    rows: list[dict[str, typing.Any]] = []
    for batch in project_id_batches(project_ids):
        rows.extend(
            await query(sql, {**(parameters or {}), 'project_ids': batch})
        )
    return rows
