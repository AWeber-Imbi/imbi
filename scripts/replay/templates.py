"""Path templates: find the route of a path, and move a path (D17)."""

import dataclasses
import functools
import re
import typing
import urllib.parse

if typing.TYPE_CHECKING:
    from scripts.replay import models

_PARAMETER = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')


def parameters(template: str) -> list[str]:
    """Return the parameter names of ``template``, in order."""
    return _PARAMETER.findall(template)


@functools.cache
def _pattern(template: str, *, prefix: bool) -> re.Pattern[str]:
    parts: list[str] = []
    position = 0
    for match in _PARAMETER.finditer(template):
        parts.append(re.escape(template[position : match.start()]))
        parts.append(f'(?P<{match.group(1)}>[^/]+)')
        position = match.end()
    parts.append(re.escape(template[position:]))
    tail = '(?=/|$)' if prefix else '$'
    return re.compile('^' + ''.join(parts) + tail)


def match(template: str, path: str) -> dict[str, str] | None:
    """Return the parameters when ``path`` fits ``template``."""
    found = _pattern(template, prefix=False).match(path)
    if found is None:
        return None
    return {
        name: urllib.parse.unquote(value)
        for name, value in found.groupdict().items()
    }


def fill(template: str, values: dict[str, str]) -> str:
    """Put ``values`` into ``template``, quoted for a URL path.

    Raises ``KeyError`` when a parameter has no value.
    """

    def replace(found: re.Match[str]) -> str:
        return urllib.parse.quote(values[found.group(1)], safe='')

    return _PARAMETER.sub(replace, template)


@dataclasses.dataclass(frozen=True)
class RouteTable:
    """The known routes, as ``METHOD template`` strings."""

    routes: tuple[str, ...]

    def resolve(self, method: str, path: str) -> str | None:
        """Return the route of a concrete path.

        When two templates fit, the one with more literal segments wins,
        so ``/releases/current`` wins over ``/releases/{release_id}``.
        """
        best: tuple[int, str] | None = None
        for route in self.routes:
            route_method, _, template = route.partition(' ')
            if route_method != method or match(template, path) is None:
                continue
            literal = sum(
                1
                for segment in template.split('/')
                if not _PARAMETER.search(segment)
            )
            if best is None or literal > best[0]:
                best = (literal, route)
        return None if best is None else best[1]


def owner_of(owners: models.OwnersConfig, route: str) -> str:
    """Return the agent letter that owns ``route``."""
    return owners.routes.get(route, owners.default)


def move(
    moves: list[models.Move],
    method: str,
    path: str,
    variables: dict[str, str],
) -> str:
    """Return the path on the new API for a path of the old API."""
    for entry in moves:
        if entry.methods and method not in entry.methods:
            continue
        found = _pattern(entry.old, prefix=not entry.exact).match(path)
        if found is None:
            continue
        captured = {
            name: urllib.parse.unquote(value)
            for name, value in found.groupdict().items()
        }
        values = {**variables, **captured}
        return fill(entry.new, values) + path[found.end() :]
    return path
