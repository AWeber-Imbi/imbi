from __future__ import annotations

import collections
import typing

from imbi.endpoints.project_sbom import models


class DependencyGraph:
    _table: dict[models.BOMRef, set[models.BOMRef]]

    def __init__(self,
                 dependencies: typing.Iterable[models.Dependency]) -> None:
        self._table = collections.defaultdict(set)
        for dependency in dependencies:
            self._table[dependency.ref].update(dependency.depends_on)

    def all_dependencies(
            self, from_node: models.BOMRef) -> typing.Iterable[models.BOMRef]:
        visited: set[models.BOMRef] = set()
        queue = list(self._table[from_node])
        while queue:
            elm = queue.pop()
            if elm not in visited:
                yield elm
                visited.add(elm)
                queue.extend(r for r in self._table[elm] if r not in visited)
