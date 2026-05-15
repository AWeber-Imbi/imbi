# JSON Pointer

A Pydantic-compatible annotated type that wraps
[`jsonpointer.JsonPointer`](https://python-json-pointer.readthedocs.io/)
so :rfc:`6901` pointers can be used directly as model fields or in a
`TypeAdapter`.

## Overview

`imbi_common.json_pointer.JsonPointer` is a `typing.Annotated` alias for
`jsonpointer.JsonPointer`. Validation accepts either an existing
`JsonPointer` instance or a string form (e.g. `/foo/0/bar`); invalid
input raises `ValueError`. Serialization emits the canonical string form,
and the generated JSON schema reports
`{"type": "string", "format": "json-pointer"}`.

## Basic Usage

```python
import jsonpointer
import pydantic

from imbi_common.json_pointer import JsonPointer


class Rule(pydantic.BaseModel):
    path: JsonPointer


rule = Rule.model_validate({'path': '/target'})
assert isinstance(rule.path, jsonpointer.JsonPointer)
assert rule.model_dump_json() == '{"path":"/target"}'
```

A `TypeAdapter` works the same way:

```python
adapter = pydantic.TypeAdapter[JsonPointer](JsonPointer)
ptr = adapter.validate_python('/items/0')
```

## API Reference

::: imbi_common.json_pointer.JsonPointer
