from __future__ import annotations

import operator
from collections import abc

import pydantic
import semantic_version.base
from pydantic_core import core_schema


def _coerce_to_version(item: object) -> semantic_version.Version | object:
    if isinstance(item, str):
        return semantic_version.Version.coerce(item)
    return item


class VersionRange(abc.Container[semantic_version.Version]):
    spec: str
    parts: list[str]
    constraint: semantic_version.base.BaseSpec

    def __init__(self,
                 spec: str,
                 *,
                 constraint_cls: type = semantic_version.NpmSpec) -> None:
        self.spec = spec
        self.constraint = constraint_cls(spec)

    def __contains__(self, item: object) -> bool:
        return _coerce_to_version(item) in self.constraint

    def __str__(self) -> str:
        return f'{self.__class__.__name__}({self.constraint})'

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(spec={self.spec!r})'

    def __eq__(self, other: object) -> bool:
        if isinstance(other, VersionRange):
            return (self.spec == other.spec
                    and self.constraint == other.constraint)
        return False

    def __hash__(self) -> int:
        return hash((self.spec, self.constraint))

    @staticmethod
    def _validate(obj: str | VersionRange) -> 'VersionRange':
        if isinstance(obj, str):
            return VersionRange(obj)
        if isinstance(obj, VersionRange):
            return obj
        raise TypeError('Invalid version range')

    @classmethod
    def __get_pydantic_core_schema__(
            cls, _source_type: type,
            _handler: pydantic.GetCoreSchemaHandler) -> core_schema.CoreSchema:
        validator = core_schema.no_info_plain_validator_function(cls._validate)
        return core_schema.json_or_python_schema(
            json_schema=validator,
            python_schema=validator,
            serialization=core_schema.plain_serializer_function_ser_schema(
                operator.attrgetter('spec')),
        )

    def __get_pydantic_json_schema__(self, *args) -> dict:
        return {
            'title': 'Range of acceptable versions',
            'type': 'string',
            'externalDocs': {
                'url': 'https://www.npmjs.com/package/semver'
            },
            'minLength': 1,
        }


class ExactRange(VersionRange):
    """Exact matches only"""
    def __init__(self, spec: str, /) -> None:
        super().__init__(spec, constraint_cls=semantic_version.SimpleSpec)
        self.version = semantic_version.Version.coerce(spec)

    def __contains__(self, item: object) -> bool:
        # NB -- Version('1.2.3.1') in SimpleSpec('1.2.3') is TRUE
        return _coerce_to_version(item) == self.version


def parse_semver_range(spec: str) -> VersionRange:
    """Parse a semver range and return a matcher

    Valid "semver ranges" are defined by https://www.npmjs.com/package/semver.
    Imbi accepts only caret ranges and tilde ranges. Anything else is
    treated as an exact value match.

    """
    if spec.startswith(('~', '^')):
        return VersionRange(spec)
    return ExactRange(spec)
