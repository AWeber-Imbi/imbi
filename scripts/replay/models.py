"""The data files of the tool, and the recording format.

Every configuration file is TOML. The models reject unknown keys, so a
typing error in a data file stops the run and does not drop a rule.
"""

import tomllib
import typing

import pydantic

if typing.TYPE_CHECKING:
    import pathlib

HttpMethod = typing.Literal['GET', 'POST', 'PUT', 'PATCH', 'DELETE']

#: The value that a path parameter gets when its source has no rows.
#: The request then shows how the route handles an id that does not
#: exist.
PLACEHOLDER = 'replay-missing'


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='forbid', frozen=True)


# -- routes.toml -------------------------------------------------------


class Source(_Model):
    """A query that gives the values of path or query parameters.

    ``cypher`` runs against the AGE graph, and ``columns`` names its
    return columns in order. ``sql`` runs as plain SQL, and its column
    names are the parameter names. ``$name`` in either query is
    replaced with a quoted global value, for example ``$org_slug``.
    ``rows`` gives fixed rows, for values that are not in the database
    (plugin slugs, for example). An empty ``rows`` list makes the
    recorder send one request with :data:`PLACEHOLDER`.
    """

    cypher: str | None = None
    columns: list[str] = pydantic.Field(default_factory=list[str])
    sql: str | None = None
    rows: list[dict[str, str]] | None = None

    @pydantic.model_validator(mode='after')
    def _one_query(self) -> typing.Self:
        given = [
            value
            for value in (self.cypher, self.sql, self.rows)
            if value is not None
        ]
        if len(given) != 1:
            raise ValueError(
                'a source needs one of "cypher", "sql", or "rows"'
            )
        if self.cypher is not None and not self.columns:
            raise ValueError('a cypher source needs "columns"')
        return self


class RouteBinding(_Model):
    """How the recorder builds the requests of one ``GET`` route."""

    path: str
    source: str | None = None
    query: dict[str, str] = pydantic.Field(default_factory=dict[str, str])
    cap: int | None = None
    skip: str | None = None


class Globals(_Model):
    """Sources whose first row gives the global variables."""

    sources: list[str] = pydantic.Field(default_factory=list[str])


class RoutesConfig(_Model):
    graph: str = 'imbi'
    globals: Globals = Globals()
    sources: dict[str, Source] = pydantic.Field(
        default_factory=dict[str, Source]
    )
    route: list[RouteBinding] = pydantic.Field(
        default_factory=list[RouteBinding]
    )

    @pydantic.model_validator(mode='after')
    def _known_sources(self) -> typing.Self:
        names = set(self.sources)
        for name in self.globals.sources:
            if name not in names:
                raise ValueError(f'unknown global source {name!r}')
        seen: set[str] = set()
        for binding in self.route:
            if binding.source is not None and binding.source not in names:
                raise ValueError(
                    f'route {binding.path!r}: unknown source '
                    f'{binding.source!r}'
                )
            if binding.path in seen:
                raise ValueError(f'route {binding.path!r} is listed twice')
            seen.add(binding.path)
        return self


# -- normalize.toml ----------------------------------------------------


class NormalizeRule(_Model):
    """One field that the diff masks before it compares.

    ``route`` is a glob on the route (``GET /api/...``) or on the
    exchange key. ``pointer`` is a pointer pattern (see ``pointer.py``).
    """

    route: str = '*'
    pointer: str
    reason: str


class NormalizeConfig(_Model):
    rule: list[NormalizeRule] = pydantic.Field(
        default_factory=list[NormalizeRule]
    )


# -- owners.toml -------------------------------------------------------


class OwnersConfig(_Model):
    """The agent letter that owns each route.

    ``routes`` maps ``METHOD template`` to a letter. Each route that it
    does not name belongs to ``default``.
    """

    default: str = 'orchestrator'
    agents: dict[str, str] = pydantic.Field(default_factory=dict[str, str])
    routes: dict[str, str] = pydantic.Field(default_factory=dict[str, str])


# -- path-map.toml -----------------------------------------------------


class Move(_Model):
    """A route that moved (D17): the old path prefix and the new one.

    ``old`` and ``new`` are path templates. ``old`` matches the start of
    a request path, at a segment boundary. ``new`` can use the
    parameters of ``old`` and the global variables. An empty
    ``methods`` list moves every method.
    """

    old: str
    new: str
    methods: list[HttpMethod] = pydantic.Field(
        default_factory=list[HttpMethod]
    )
    exact: bool = False
    owner: str
    note: str = ''


class PathMapConfig(_Model):
    move: list[Move] = pydantic.Field(default_factory=list[Move])


# -- expected/<domain>.toml --------------------------------------------

Field = typing.Literal['status', 'body', 'exchange']


class ExpectedDifference(_Model):
    """A difference that the migration causes on purpose.

    ``route`` and ``key`` are globs. ``pointer`` is a pointer pattern
    for a ``body`` difference. ``old`` and ``new`` are optional; when
    set, they must equal the old and new values. Use ``'<missing>'``
    for a field that is not present and ``'<null>'`` for ``null``.
    ``old_status`` and ``new_status`` are optional; when set, the
    statuses of the exchange must be equal. Use them to limit a body
    difference to the status change that causes it.
    """

    route: str = '*'
    key: str = '*'
    field: Field
    pointer: str = '/**'
    old: typing.Any = None
    new: typing.Any = None
    old_status: int | None = None
    new_status: int | None = None
    reason: str


class ExpectedConfig(_Model):
    domain: str
    owner: str
    difference: list[ExpectedDifference] = pydantic.Field(
        default_factory=list[ExpectedDifference]
    )


# -- scenarios/<domain>.toml -------------------------------------------


class WaitFor(_Model):
    """Send a step again until a value of the response is correct.

    Use it for work that the API does after the response, such as the
    search index. ``equals`` or ``not_equals`` can use variables. The
    step fails when the value is not correct after ``timeout``
    seconds.
    """

    pointer: str
    equals: str | None = None
    not_equals: str | None = None
    timeout: float = 60.0
    interval: float = 1.0

    @pydantic.model_validator(mode='after')
    def _one_condition(self) -> typing.Self:
        if (self.equals is None) == (self.not_equals is None):
            raise ValueError('wait_for needs one of "equals" or "not_equals"')
        return self


class Step(_Model):
    """One request of a scenario.

    ``{name}`` in ``path``, ``query`` values, and ``body`` strings is
    replaced with a variable. ``save`` maps a variable name to a pointer
    in the response body. ``expect`` is the status (or the statuses)
    that the AGE-era API returns; the runner reports a step that
    returns another status. ``always`` steps run also after an earlier
    step failed, so a scenario can clean up. ``normalize`` lists pointer
    patterns in the response that are different on each run, such as a
    generated id. ``wait_for`` sends the step again until a value of the
    response is correct.
    """

    name: str = ''
    method: HttpMethod
    path: str
    query: dict[str, str] = pydantic.Field(default_factory=dict[str, str])
    body: typing.Any = None
    expect: int | list[int] | None = None
    save: dict[str, str] = pydantic.Field(default_factory=dict[str, str])
    normalize: list[str] = pydantic.Field(default_factory=list[str])
    always: bool = False
    wait_for: WaitFor | None = None

    @property
    def expected_statuses(self) -> list[int]:
        if self.expect is None:
            return []
        if isinstance(self.expect, int):
            return [self.expect]
        return self.expect


class Scenario(_Model):
    name: str
    description: str = ''
    step: list[Step]


class ScenarioFile(_Model):
    domain: str
    owner: str
    scenario: list[Scenario]


# -- the recording -----------------------------------------------------

ExchangeKind = typing.Literal['get', 'scenario']


class Exchange(pydantic.BaseModel):
    """One request and its response.

    ``body`` is the parsed JSON body. A body that is not JSON is
    ``{"$text": ...}`` when it is short text, or ``{"$sha256": ...,
    "$length": ...}``. The recorder does not normalize: the diff
    applies the rules, so a new rule does not need a new recording.
    """

    model_config = pydantic.ConfigDict(extra='forbid')

    key: str
    kind: ExchangeKind
    route: str
    method: HttpMethod
    path: str
    query: dict[str, str] = pydantic.Field(default_factory=dict[str, str])
    request_body: typing.Any = None
    status: int
    content_type: str | None = None
    body: typing.Any = None
    elapsed_ms: list[float] = pydantic.Field(default_factory=list[float])
    placeholder: bool = False
    unstable: list[str] = pydantic.Field(default_factory=list[str])
    error: str | None = None
    normalize: list[str] = pydantic.Field(default_factory=list[str])


def load_toml[T: pydantic.BaseModel](model: type[T], path: pathlib.Path) -> T:
    """Read ``path`` and validate it as ``model``."""
    with path.open('rb') as handle:
        data = tomllib.load(handle)
    try:
        return model.model_validate(data)
    except pydantic.ValidationError as error:
        raise ValueError(f'{path}: {error}') from error
