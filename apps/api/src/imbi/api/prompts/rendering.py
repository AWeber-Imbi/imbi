"""Render prompt CMS templates in a Jinja2 sandbox.

A template sees only the caller's variables and the registered
providers, such as ``project(project_id)``. The sandbox blocks access
to private attributes and to Python internals, and the environment is
immutable, so a template cannot change the values it receives.

Limits: the sandbox cannot interrupt a CPU-bound loop, because an
``asyncio`` timeout only acts at an ``await``. So ``range()`` is capped
at :data:`MAX_RANGE`, the output is capped at :data:`MAX_OUTPUT`, and
only principals with ``prompt:update`` can save a template. The
timeout bounds the time spent waiting on providers.
"""

import asyncio
import collections.abc
import re
import typing

import jinja2
import jinja2.exceptions
import jinja2.sandbox

from imbi.common import models

#: Highest ``range()`` length a template may ask for.
MAX_RANGE = 1000

#: Highest total size, in characters, of one rendered prompt.
MAX_OUTPUT = 256 * 1024

#: Seconds a render may wait, including provider calls.
RENDER_TIMEOUT = 2.0

#: Variable names must be usable as Jinja identifiers.
_VARIABLE_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

Provider = collections.abc.Callable[..., collections.abc.Awaitable[object]]


class RenderError(ValueError):
    """The template or the variables cannot produce a prompt."""


def _safe_range(*args: int) -> range:
    rng = range(*args)
    if len(rng) > MAX_RANGE:
        raise RenderError(
            f'range() is limited to {MAX_RANGE} items, got {len(rng)}'
        )
    return rng


def _environment() -> jinja2.sandbox.ImmutableSandboxedEnvironment:
    env = jinja2.sandbox.ImmutableSandboxedEnvironment(
        enable_async=True,
        undefined=jinja2.StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    # The stubs type ``globals`` by its default values only.
    typing.cast('dict[str, object]', env.globals)['range'] = (  # type: ignore[redundant-cast]
        _safe_range
    )
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


def check_syntax(
    version_fields: collections.abc.Mapping[str, str],
) -> None:
    """Parse each template so a broken version cannot be saved.

    Parameters:
        version_fields: Field label (``system``, ``messages[0]``) to
            template source.

    Raises:
        RenderError: A template does not parse.

    """
    for label, source in version_fields.items():
        try:
            _ENV.parse(source)
        except jinja2.TemplateSyntaxError as e:
            raise RenderError(f'{label}: line {e.lineno}: {e.message}') from e


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
        RenderError: The variables are not valid, the template fails,
            the render takes too long, or the output is too large.

    """
    validate_variables(version.variable_schema, variables)
    context: dict[str, object] = {
        **{name: memoize(fn) for name, fn in providers.items()},
        **variables,
    }

    async def one(source: str) -> str:
        try:
            return await _ENV.from_string(source).render_async(context)
        except jinja2.UndefinedError as e:
            raise RenderError(f'Undefined value: {e.message}') from e
        except jinja2.exceptions.SecurityError as e:
            raise RenderError(f'Not allowed: {e}') from e
        except jinja2.TemplateError as e:
            raise RenderError(str(e)) from e

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

    size = len(system) + sum(len(m.content) for m in messages)
    if size > MAX_OUTPUT:
        raise RenderError(
            f'Rendered prompt is {size} characters; the limit is {MAX_OUTPUT}'
        )
    return RenderedPrompt(system=system, messages=messages)
