"""Row to Pydantic model mapping."""

import typing
from collections import abc

import pydantic


def row_to_model[ModelT: pydantic.BaseModel](
    model_cls: type[ModelT], row: abc.Mapping[str, typing.Any]
) -> ModelT:
    """Validate a ``dict_row`` row into *model_cls*.

    The pools use ``psycopg.rows.dict_row``, so a row is a dict keyed
    by column name. ``jsonb`` columns arrive as Python objects and
    ``timestamptz`` columns as aware datetimes, so ``model_validate``
    reads them without conversion. There is no ``model_construct``
    fallback: a row that does not validate is a defect, and the error
    shows it.

    """
    return model_cls.model_validate(row)
