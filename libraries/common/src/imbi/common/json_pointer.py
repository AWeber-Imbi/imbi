"""Pydantic-compatible :rfc:`6901` JSON Pointer annotated type.

The :data:`JsonPointer` alias wraps :class:`jsonpointer.JsonPointer` with
a pydantic core schema so it can be used directly in ``BaseModel`` fields
and ``TypeAdapter`` instances. Validation accepts either an existing
``JsonPointer`` instance or a string; serialization emits the pointer's
string form and the generated JSON schema reports
``{"type": "string", "format": "json-pointer"}``.

Example::

    import pydantic
    from imbi_common.json_pointer import JsonPointer


    class Rule(pydantic.BaseModel):
        path: JsonPointer

"""

import typing

import jsonpointer
import pydantic
import pydantic_core
from pydantic import json_schema
from pydantic_core import core_schema

__all__ = ['JsonPointer']


class _JsonPointerImplementation:
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: typing.Any,
        _handler: pydantic.GetCoreSchemaHandler,
    ) -> pydantic_core.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            cls._validate, serialization=core_schema.to_string_ser_schema()
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        _schema: pydantic_core.CoreSchema,
        _handler: pydantic.GetJsonSchemaHandler,
    ) -> json_schema.JsonSchemaValue:
        return {'type': 'string', 'format': 'json-pointer'}

    @staticmethod
    def _validate(value: object) -> jsonpointer.JsonPointer:
        if isinstance(value, jsonpointer.JsonPointer):
            return value
        if isinstance(value, str):
            try:
                return jsonpointer.JsonPointer(value)
            except jsonpointer.JsonPointerException as e:
                raise ValueError(str(e)) from e
        raise ValueError(
            f'Expected a string or JsonPointer, got {type(value)}'
        )


JsonPointer = typing.Annotated[
    jsonpointer.JsonPointer, _JsonPointerImplementation
]
