"""Render prompt CMS templates in a Jinja2 sandbox.

A template sees only the caller's variables and the registered
providers, such as ``project(project_id)``. The sandbox blocks access
to private attributes and to Python internals, and the environment is
immutable, so a template cannot change the values it receives.

Resource limits. An ``asyncio`` timeout acts only at an ``await``, so
it cannot stop a CPU-bound template. The limits are applied where the
work happens instead:

- Size: ``*``, ``+``, ``**``, and ``%`` are checked before they run;
  padding and joining operations are capped or removed; the output is
  streamed and stops at :data:`MAX_OUTPUT`.
- Time: ``range()`` is capped at :data:`MAX_RANGE`, loops may nest
  :data:`MAX_LOOP_DEPTH` deep, and macros are not allowed, so a
  template cannot recurse. These are checked when a version is saved
  and again before it renders.
- Only principals with ``prompt:update`` can save a template.
"""

import asyncio
import collections.abc
import re
import typing

import jinja2
import jinja2.exceptions
import jinja2.filters
import jinja2.nodes
import jinja2.runtime
import jinja2.sandbox

from imbi.common import models

#: Highest ``range()`` length a template may ask for.
MAX_RANGE = 1000

#: Highest total size, in characters, of one rendered prompt. Also the
#: highest size of any one value a template builds.
MAX_OUTPUT = 256 * 1024

#: Deepest loop nesting a template may use.
MAX_LOOP_DEPTH = 2

#: Highest exponent ``**`` accepts.
MAX_EXPONENT = 64

#: Highest width the ``indent`` filter accepts.
MAX_INDENT = 64

#: Seconds a render may wait, including provider calls.
RENDER_TIMEOUT = 2.0

#: Variable names must be usable as Jinja identifiers.
_VARIABLE_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

#: ``str`` methods that pad to a caller-given width or format with
#: caller-given widths, so their output size is not bounded by input.
_UNSAFE_STR_METHODS = frozenset(
    {
        'center',
        'expandtabs',
        'format',
        'format_map',
        'join',
        'ljust',
        'rjust',
        'zfill',
    }
)

#: ``namespace`` lets a loop carry a value across iterations, and
#: ``lipsum`` produces text of a caller-given size.
_REMOVED_GLOBALS = ('lipsum', 'namespace')

#: Filters that pad or format to caller-given widths.
_REMOVED_FILTERS = ('center', 'format')

Provider = collections.abc.Callable[..., collections.abc.Awaitable[object]]


class RenderError(ValueError):
    """The template or the variables cannot produce a prompt."""


def _too_large(size: int) -> RenderError:
    return RenderError(
        f'A value of {size} items is larger than the limit of {MAX_OUTPUT}'
    )


def _sized(value: object) -> bool:
    return isinstance(value, (str, list, tuple))


def _safe_range(*args: int) -> range:
    rng = range(*args)
    if len(rng) > MAX_RANGE:
        raise RenderError(
            f'range() is limited to {MAX_RANGE} items, got {len(rng)}'
        )
    return rng


def _safe_indent(value: str, width: int | str = 4, *args: bool) -> str:
    if isinstance(width, int) and width > MAX_INDENT:
        raise RenderError(f'indent() width is limited to {MAX_INDENT}')
    if isinstance(width, str) and len(width) > MAX_INDENT:
        raise RenderError(f'indent() width is limited to {MAX_INDENT}')
    return jinja2.filters.do_indent(value, width, *args)


async def _safe_join(
    eval_ctx: jinja2.nodes.EvalContext,
    value: object,
    d: str = '',
    attribute: str | int | None = None,
) -> str:
    # In async mode a filter can receive an async iterable.
    if isinstance(value, collections.abc.AsyncIterable):
        items: list[object] = [
            item
            async for item in typing.cast(
                'collections.abc.AsyncIterable[object]', value
            )
        ]
    else:
        items = list(typing.cast('collections.abc.Iterable[object]', value))
    if len(d) * len(items) > MAX_OUTPUT:
        raise _too_large(len(d) * len(items))
    return jinja2.filters.sync_do_join(eval_ctx, items, d, attribute)


_safe_join_filter = jinja2.pass_eval_context(_safe_join)


class _Sandbox(jinja2.sandbox.ImmutableSandboxedEnvironment):
    """Sandbox that checks the size of values before it builds them."""

    intercepted_binops = frozenset({'*', '+', '**', '%'})

    def call_binop(
        self,
        context: jinja2.runtime.Context,
        operator: str,
        left: typing.Any,
        right: typing.Any,
    ) -> typing.Any:
        if operator == '*':
            for seq, times in ((left, right), (right, left)):
                if _sized(seq) and isinstance(times, int):
                    if len(seq) * times > MAX_OUTPUT:
                        raise _too_large(len(seq) * times)
        elif operator == '+':
            if _sized(left) and _sized(right):
                if len(left) + len(right) > MAX_OUTPUT:
                    raise _too_large(len(left) + len(right))
        elif operator == '**':
            if isinstance(right, (int, float)) and abs(right) > MAX_EXPONENT:
                raise RenderError(f'Exponents are limited to {MAX_EXPONENT}')
        elif operator == '%' and isinstance(left, str):
            raise RenderError('String formatting with % is not allowed')
        return super().call_binop(context, operator, left, right)

    def is_safe_attribute(self, obj: object, attr: str, value: object) -> bool:
        if isinstance(obj, str) and attr in _UNSAFE_STR_METHODS:
            return False
        return super().is_safe_attribute(obj, attr, value)


def _environment() -> _Sandbox:
    env = _Sandbox(
        enable_async=True,
        undefined=jinja2.StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    # The stubs type these mappings by their default values only.
    env_globals = typing.cast('dict[str, object]', env.globals)  # type: ignore[redundant-cast]
    env_filters = typing.cast('dict[str, object]', env.filters)  # type: ignore[redundant-cast]
    for name in _REMOVED_GLOBALS:
        del env_globals[name]
    for name in _REMOVED_FILTERS:
        del env_filters[name]
    env_globals['range'] = _safe_range
    env_filters['indent'] = _safe_indent
    env_filters['join'] = _safe_join_filter
    return env


_ENV = _environment()

_TYPES: dict[str, tuple[type, ...]] = {
    'str': (str,),
    'int': (int,),
    'float': (int, float),
    'bool': (bool,),
    'list': (list,),
    'object': (dict,),
}


def _check_structure(node: jinja2.nodes.Node, depth: int = 0) -> None:
    """Reject macros and loops nested deeper than allowed."""
    if isinstance(node, (jinja2.nodes.Macro, jinja2.nodes.CallBlock)):
        raise RenderError('Macros are not allowed')
    if isinstance(node, jinja2.nodes.For):
        depth += 1
        if depth > MAX_LOOP_DEPTH:
            raise RenderError(f'Loops may nest at most {MAX_LOOP_DEPTH} deep')
    for child in node.iter_child_nodes():
        _check_structure(child, depth)


def _parse(source: str) -> jinja2.nodes.Template:
    tree = _ENV.parse(source)
    _check_structure(tree)
    return tree


def check_syntax(
    version_fields: collections.abc.Mapping[str, str],
) -> None:
    """Parse each template so a broken version cannot be saved.

    Parameters:
        version_fields: Field label (``system``, ``messages[0]``) to
            template source.

    Raises:
        RenderError: A template does not parse, uses a macro, or nests
            loops too deep.

    """
    for label, source in version_fields.items():
        try:
            _parse(source)
        except jinja2.TemplateSyntaxError as e:
            raise RenderError(f'{label}: line {e.lineno}: {e.message}') from e
        except RenderError as e:
            raise RenderError(f'{label}: {e}') from e


def check_variable_schema(
    schema: collections.abc.Mapping[str, models.PromptVariable],
    provider_names: collections.abc.Collection[str],
) -> None:
    """Reject variable names a template could not use.

    Raises:
        RenderError: A name is not an identifier or hides a provider.

    """
    for name in schema:
        if not _VARIABLE_NAME.match(name):
            raise RenderError(f'Variable {name!r} is not a valid name')
        if name in provider_names:
            raise RenderError(
                f'Variable {name!r} has the same name as a provider'
            )


def validate_variables(
    schema: collections.abc.Mapping[str, models.PromptVariable],
    variables: collections.abc.Mapping[str, object],
) -> None:
    """Check the caller's variables against the version's schema.

    Raises:
        RenderError: A variable is unknown, missing, or the wrong type.

    """
    unknown = sorted(set(variables) - set(schema))
    if unknown:
        raise RenderError(f'Unknown variables: {", ".join(unknown)}')
    for name, spec in schema.items():
        if name not in variables:
            if spec.required:
                raise RenderError(f'Missing required variable {name!r}')
            continue
        value = variables[name]
        allowed = _TYPES[spec.type]
        # ``bool`` is an ``int`` in Python; do not accept it as a number.
        is_bool = isinstance(value, bool)
        if not isinstance(value, allowed) or (is_bool and spec.type != 'bool'):
            raise RenderError(f'Variable {name!r} must be of type {spec.type}')


def memoize(provider: Provider) -> Provider:
    """Return ``provider`` with results cached for one render."""
    cache: dict[tuple[object, ...], object] = {}

    async def wrapper(*args: object) -> object:
        try:
            hash(args)
        except TypeError:
            return await provider(*args)
        if args not in cache:
            cache[args] = await provider(*args)
        return cache[args]

    return wrapper


class RenderedPrompt(typing.NamedTuple):
    system: str
    messages: list[models.PromptMessage]


async def render(
    version: models.PromptVersion,
    variables: collections.abc.Mapping[str, object],
    providers: collections.abc.Mapping[str, Provider],
) -> RenderedPrompt:
    """Render the system prompt and each message of ``version``.

    Raises:
        RenderError: The variables are not valid, the template fails or
            breaks a limit, the render takes too long, or the output is
            too large.

    """
    validate_variables(version.variable_schema, variables)
    context: dict[str, object] = {
        **{name: memoize(fn) for name, fn in providers.items()},
        **variables,
    }
    budget = MAX_OUTPUT

    async def one(source: str) -> str:
        nonlocal budget
        parts: list[str] = []
        try:
            template = _ENV.from_string(_parse(source))
            async for chunk in template.generate_async(context):
                budget -= len(chunk)
                if budget < 0:
                    raise RenderError(
                        f'The rendered prompt is larger than the limit of '
                        f'{MAX_OUTPUT} characters'
                    )
                parts.append(chunk)
        except jinja2.UndefinedError as e:
            raise RenderError(f'Undefined value: {e.message}') from e
        except jinja2.exceptions.SecurityError as e:
            raise RenderError(f'Not allowed: {e}') from e
        except jinja2.TemplateError as e:
            raise RenderError(str(e)) from e
        except ArithmeticError as e:
            raise RenderError(f'Arithmetic error: {e}') from e
        return ''.join(parts)

    try:
        async with asyncio.timeout(RENDER_TIMEOUT):
            system = await one(version.system)
            messages = [
                models.PromptMessage(role=m.role, content=await one(m.content))
                for m in version.messages
            ]
    except TimeoutError as e:
        raise RenderError(
            f'Render took longer than {RENDER_TIMEOUT} seconds'
        ) from e
    return RenderedPrompt(system=system, messages=messages)
