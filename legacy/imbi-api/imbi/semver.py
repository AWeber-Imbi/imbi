from __future__ import annotations

from collections import abc

import semantic_version.base
from packaging import version


class VersionRange(abc.Container[semantic_version.Version]):
    spec: str
    parts: list[str]
    constraint: semantic_version.base.BaseSpec

    def __init__(self, spec: str) -> None:
        self.spec = spec
        self.constraint = semantic_version.NpmSpec(spec)

    def __contains__(self, item: object) -> bool:
        return self._coerce(item) in self.constraint

    @staticmethod
    def _coerce(item: object) -> semantic_version.Version | object:
        if isinstance(item, str):
            return semantic_version.Version.coerce(item)
        if isinstance(item, version.Version):
            return semantic_version.Version(str(item))
        return item

    def __str__(self):
        return f'VersionRange({self.constraint})'

    def __repr__(self) -> str:
        return f'VersionRange(spec={self.spec!r})'


class ExactRange(VersionRange):
    """Exact matches only"""
    def __init__(self, spec: str, /) -> None:
        super().__init__('=' + spec)
        self.version = semantic_version.Version.coerce(spec)
        self.constraint = semantic_version.SimpleSpec(self.spec)

    def __contains__(self, item: object) -> bool:
        item = self._coerce(item)
        if matches := super().__contains__(item):
            return item == self.version
        return matches


def parse_semver_range(spec: str) -> VersionRange:
    """Parse a semver range and return a matcher

    Valid "semver ranges" are defined by https://www.npmjs.com/package/semver.
    Imbi accepts only caret ranges and tilde ranges. Anything else is
    treated as an exact value match.

    """
    if spec.startswith(('~', '^')):
        return VersionRange(spec)
    return ExactRange(spec)
