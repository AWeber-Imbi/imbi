from __future__ import annotations

import datetime
import decimal
import typing

import dateutil.parser


def coerce_project_fact_values(
        rows: list[dict[str, typing.Any]]
) -> list[dict[str, None | bool | decimal.Decimal | int | str]]:
    """Shared method to coerce the values to the correct data types in the
    output for project facts

    """
    for row in rows:
        row['value'] = coerce_project_fact(row['data_type'], row['value'])
        del row['data_type']

    return rows


def coerce_project_fact(
        data_type: str, value: typing.Any
) -> None | bool | decimal.Decimal | int | str:
    """Coerce a single fact based on its data type."""
    if not value and value != 0:
        value = None
    elif data_type == 'boolean':
        value = 'false' if value is None else str(value).lower()
        if value in ('y', 'yes', 't', 'true', 'on', '1'):
            value = True
        elif value in ('n', 'no', 'f', 'false', 'off', '0'):
            value = False
        else:
            raise ValueError(f'{value!r} is not a valid Boolean')
    elif data_type == 'decimal':
        try:
            value = decimal.Decimal(value)
        except decimal.InvalidOperation as error:
            raise ValueError(f'{value!r} is not a valid decimal: {error}')
    elif data_type == 'integer':
        try:
            value = int(value)
        except TypeError as error:
            raise ValueError(f'{value!r} is not a valid integer: {error}')
    elif data_type == 'date':
        value = dateutil.parser.parse(str(value))
        value = value.date().isoformat()
    elif data_type == 'timestamp':
        value = dateutil.parser.parse(str(value))
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        value = value.isoformat()
    elif data_type == 'string':
        value = str(value)
    else:
        raise ValueError(f'{data_type!r} is not a known fact type')

    return value
