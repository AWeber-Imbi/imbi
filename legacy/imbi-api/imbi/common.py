import decimal
import typing
from distutils import util


def coerce_project_fact_values(rows: typing.List[typing.Dict]) -> typing.List:
    """Shared method to coerce the values to the correct data types in the
    output for project facts

    """
    for row in rows:
        if row['data_type'] == 'boolean':
            row['value'] = bool(util.strtobool(row['value']))
        elif row['data_type'] == 'decimal':
            row['value'] = decimal.Decimal(row['value'])
        elif row['data_type'] == 'integer':
            row['value'] = int(row['value'])
        del row['data_type']
    return rows
