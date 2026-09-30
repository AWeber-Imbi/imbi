"""Build the ``GET`` requests of a recording from the OpenAPI document.

Each ``GET`` route gets requests in one of these ways:

1. The route has no path parameter that the global variables do not
   give: one request.
2. ``routes.toml`` names a source for the route: one request for each
   source row, up to the cap. When the source has no rows, one request
   with :data:`models.PLACEHOLDER` for the parameters that no global
   gives, so the recording still shows how the route handles an
   unknown id.
3. ``routes.toml`` skips the route, with a reason.

Any other route is *uncovered*, and the recorder stops unless it is
told to continue.
"""

import dataclasses
import typing
from collections import abc

from scripts.replay import models, templates

Fetch = abc.Callable[[str, int], list[dict[str, str]]]


@dataclasses.dataclass(frozen=True)
class Operation:
    """A ``GET`` operation of the OpenAPI document."""

    path: str
    path_parameters: tuple[str, ...]
    required_query: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Request:
    route: str
    path: str
    query: dict[str, str]
    placeholder: bool = False

    @property
    def key(self) -> str:
        if not self.query:
            return f'GET {self.path}'
        pairs = '&'.join(
            f'{name}={value}' for name, value in sorted(self.query.items())
        )
        return f'GET {self.path}?{pairs}'


@dataclasses.dataclass
class Plan:
    requests: list[Request] = dataclasses.field(default_factory=list[Request])
    skipped: dict[str, str] = dataclasses.field(default_factory=dict[str, str])
    uncovered: dict[str, str] = dataclasses.field(
        default_factory=dict[str, str]
    )


def operations(document: dict[str, typing.Any]) -> list[Operation]:
    """Return the ``GET`` operations of an OpenAPI document."""
    result: list[Operation] = []
    paths = typing.cast('dict[str, dict[str, typing.Any]]', document['paths'])
    for path, item in paths.items():
        operation = item.get('get')
        if operation is None:
            continue
        parameters = typing.cast(
            'list[dict[str, typing.Any]]',
            list(item.get('parameters', []))
            + list(operation.get('parameters', [])),
        )
        required = tuple(
            str(parameter['name'])
            for parameter in parameters
            if parameter.get('in') == 'query' and parameter.get('required')
        )
        result.append(
            Operation(
                path=path,
                path_parameters=tuple(templates.parameters(path)),
                required_query=required,
            )
        )
    return result


class _Placeholders(dict[str, str]):
    """Variables where each missing name is the placeholder."""

    def __missing__(self, key: str) -> str:
        return models.PLACEHOLDER


def _render(value: str, variables: dict[str, str]) -> str:
    try:
        return value.format_map(variables)
    except KeyError as error:
        raise KeyError(
            f'{value!r} uses {error}, which has no value'
        ) from error


def build(
    document: dict[str, typing.Any],
    config: models.RoutesConfig,
    fetch: Fetch,
    variables: dict[str, str],
    cap: int,
) -> Plan:
    """Return the requests for every ``GET`` route of ``document``."""
    bindings = {binding.path: binding for binding in config.route}
    plan = Plan()
    for operation in operations(document):
        route = f'GET {operation.path}'
        binding = bindings.pop(operation.path, None)
        if binding is not None and binding.skip is not None:
            plan.skipped[route] = binding.skip
            continue
        query_values = {} if binding is None else dict(binding.query)
        missing_query = [
            name
            for name in operation.required_query
            if name not in query_values
        ]
        if missing_query:
            plan.uncovered[route] = (
                'required query parameters without a value: '
                + ', '.join(missing_query)
            )
            continue
        unbound = [
            name for name in operation.path_parameters if name not in variables
        ]
        if unbound and (binding is None or binding.source is None):
            plan.uncovered[route] = (
                'path parameters without a source: ' + ', '.join(unbound)
            )
            continue
        rows: list[dict[str, str]] = [{}]
        placeholder = False
        if binding is not None and binding.source is not None:
            limit = binding.cap if binding.cap is not None else cap
            rows = fetch(binding.source, limit)
            if not rows:
                rows = [dict.fromkeys(unbound, models.PLACEHOLDER)]
                placeholder = True
        seen: set[str] = set()
        for row in rows:
            values = {**variables, **row}
            if placeholder:
                values = _Placeholders(values)
            try:
                path = templates.fill(operation.path, values)
                query = {
                    name: _render(value, values)
                    for name, value in query_values.items()
                }
            except KeyError as error:
                plan.uncovered[route] = f'no value: {error}'
                break
            request = Request(
                route=route, path=path, query=query, placeholder=placeholder
            )
            if request.key in seen:
                continue
            seen.add(request.key)
            plan.requests.append(request)
    for path in bindings:
        plan.uncovered[f'GET {path}'] = (
            'routes.toml names a route that the OpenAPI document does not have'
        )
    return plan
