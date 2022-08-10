import datetime
import decimal
import typing
from distutils import util

import dateutil.parser


def coerce_project_fact_values(rows: typing.List[typing.Dict]) -> typing.List:
    """Shared method to coerce the values to the correct data types in the
    output for project facts

    """
    for row in rows:
        if not row['value'] and row['value'] != 0:
            row['value'] = None
            continue

        if row['data_type'] == 'boolean':
            if row['value'] is None:
                row['value'] = False
            else:
                row['value'] = bool(util.strtobool(str(row['value'])))
        elif row['data_type'] == 'decimal':
            try:
                row['value'] = decimal.Decimal(row['value'])
            except decimal.InvalidOperation as error:
                raise ValueError(
                    f'{row["value"]!r} is not a valid decimal: {error}')
        elif row['data_type'] == 'integer':
            try:
                row['value'] = int(row['value'])
            except TypeError as error:
                raise ValueError(
                    f'{row["value"]!r} is not a valid integer: {error}')
        elif row['data_type'] == 'date':
            value = dateutil.parser.parse(str(row['value']))
            row['value'] = value.date().isoformat()
        elif row['data_type'] == 'timestamp':
            value = dateutil.parser.parse(str(row['value']))
            if value.tzinfo is None:
                value = value.replace(tzinfo=datetime.timezone.utc)
            row['value'] = value.isoformat()
        else:
            raise ValueError(f'{row["data_type"]!r} is not a known fact type')

        del row['data_type']

    return rows
