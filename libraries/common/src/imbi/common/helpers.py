import types
import typing


def unwrap_as[T](typ: type[T], value: object | None) -> T:
    origin = typing.get_origin(typ) or typ
    if origin is not None and origin not in (typing.Union, types.UnionType):
        typ = origin
    if value is None:
        raise ValueError('Value is unexpectedly None')
    if isinstance(value, typ):
        return value
    raise ValueError('Value is not of expected type')
