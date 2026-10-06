"""Render prompt CMS templates in a Jinja2 sandbox.

A template sees only the caller's variables and the registered
providers, such as ``project(project_id)``. The sandbox blocks access
to private attributes and to Python internals, and the environment is
immutable, so a template cannot change the values it receives.

Resource limits. An ``asyncio`` timeout acts only at an ``await``, so
it cannot stop a CPU-bound template. The limits are applied where the
work happens instead, and use allowlists, not denylists:

- Size: one measure, :func:`_measure`, is applied before ``~``, ``+``,
  ``*``, ``join``, ``replace``, ``indent``, ``string``, and ``tojson``
  build a value, and to each ``{{ }}`` value before it becomes text.
  ``tojson`` does not accept ``indent``. Integer ``*`` and ``**`` are
  limited by bit length. Only the ``str`` methods in
  :data:`_STR_METHODS` and the filters in :data:`_FILTERS` are
  available. The output streams and stops at :data:`MAX_OUTPUT`.
- Time: one render may spend at most :data:`MAX_WORK` units of work.
  Each loop iteration costs :data:`ITERATION_COST`. Each call, filter,
  and operator costs 1, plus the length of the value it works on: the
  string a ``str`` method is called on, the value a filter receives
  (one unit for each item of an iterator), and the value that ``~``,
  ``+``, ``*``, or ``%`` builds. ``range()`` is capped at
  :data:`MAX_RANGE`, loops may nest :data:`MAX_LOOP_DEPTH` deep, and
  macros and recursive loops are not allowed. The structure is checked
  when a version is saved and again before it renders.
- Only principals with ``prompt:update`` can save a template.
"""

import asyncio
import collections.abc
import contextvars
import functools
import json
import re
import typing

import jinja2
import jinja2.compiler
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

#: Highest bit length of an integer that ``*`` or ``**`` produces.
MAX_INT_BITS = 4096

#: Seconds a render may wait, including provider calls.
RENDER_TIMEOUT = 2.0

#: Highest number of work units one render may spend. An ``asyncio``
#: timeout cannot stop a template that never awaits, so this budget
#: is what limits CPU time.
MAX_WORK = 4 * 1024 * 1024

#: Work units one loop iteration costs. Comparisons and tests are not
#: counted one by one, so an iteration costs enough to cover them.
ITERATION_COST = 256

#: Work units left in the current render. :func:`render` sets it.
_work: contextvars.ContextVar[list[int]] = contextvars.ContextVar(
    'prompt_render_work'
)

#: Variable names must be usable as Jinja identifiers.
_VARIABLE_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

#: ``str`` methods a template may call. None of them returns a value
#: larger than the string it is called on.
_STR_METHODS = frozenset(
    {
        'capitalize',
        'casefold',
        'count',
        'endswith',
        'find',
        'index',
        'isalnum',
        'isalpha',
        'isdigit',
        'islower',
        'isspace',
        'istitle',
        'isupper',
        'lower',
        'lstrip',
        'partition',
        'rfind',
        'rindex',
        'rpartition',
        'rsplit',
        'rstrip',
        'split',
        'splitlines',
        'startswith',
        'strip',
        'swapcase',
        'title',
        'upper',
    }
)

#: Built-in filters a template may use, besides the wrapped ones that
#: :func:`_environment` installs. None of them produces output much
#: larger than its input.
_FILTERS = frozenset(
    {
        'abs',
        'capitalize',
        'count',
        'd',
        'default',
        'dictsort',
        'first',
        'float',
        'groupby',
        'int',
        'items',
        'last',
        'length',
        'list',
        'lower',
        'map',
        'max',
        'min',
        'reject',
        'rejectattr',
        'reverse',
        'round',
        'select',
        'selectattr',
        'sort',
        'striptags',
        'sum',
        'title',
        'trim',
        'truncate',
        'unique',
        'upper',
        'urlencode',
        'wordcount',
    }
)

#: ``dict`` methods a template may call; each pays for the dict size.
_DICT_METHODS = frozenset({'get', 'items', 'keys', 'values'})

#: Built-in globals a template may use, besides ``range``.
_GLOBALS = frozenset({'cycler', 'dict', 'joiner'})

#: Cost given to a value of a type :func:`_measure` does not know.
_OPAQUE_SIZE = 64

Provider = collections.abc.Callable[..., collections.abc.Awaitable[object]]


class RenderError(ValueError):
    """The template or the variables cannot produce a prompt."""


def _too_large(size: int) -> RenderError:
    return RenderError(
        f'A value of {size} or more characters is larger than the limit '
        f'of {MAX_OUTPUT}'
    )


def _measure(value: object, limit: int = MAX_OUTPUT) -> int:
    """Estimate the length of ``str(value)``, stopping above ``limit``.

    Nested lists and dicts are walked, so a list of references to one
    large string counts each reference. The walk stops as soon as the
    total goes over ``limit``.
    """
    total = 0
    stack: list[object] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, (str, bytes, bytearray)):
            total += len(item)
        elif isinstance(item, bool) or item is None:
            total += 5
        elif isinstance(item, int):
            total += item.bit_length() // 3 + 1
        elif isinstance(item, float):
            total += 24
        elif isinstance(item, dict):
            mapping = typing.cast('dict[object, object]', item)
            total += 2 + 4 * len(mapping)
            stack.extend(mapping.keys())
            stack.extend(mapping.values())
        elif isinstance(item, (list, tuple, set, frozenset)):
            items = typing.cast('collections.abc.Collection[object]', item)
            total += 2 + 2 * len(items)
            stack.extend(items)
        elif isinstance(item, jinja2.Undefined):
            continue
        else:
            total += _OPAQUE_SIZE
        if total > limit:
            break
    return total


def _check_size(*values: object) -> None:
    total = 0
    for value in values:
        total += _measure(value, MAX_OUTPUT - total)
        if total > MAX_OUTPUT:
            raise _too_large(total)


def _safe_range(*args: int) -> range:
    rng = range(*args)
    if len(rng) > MAX_RANGE:
        raise RenderError(
            f'range() is limited to {MAX_RANGE} items, got {len(rng)}'
        )
    return rng


def _spend(cost: int) -> None:
    """Take ``cost`` units from the work budget of the current render."""
    remaining = _work.get()
    remaining[0] -= cost
    if remaining[0] < 0:
        raise RenderError(
            f'The template does more work than the limit of {MAX_WORK} units'
        )


def _remaining() -> int:
    return max(_work.get()[0], 0)


def _shallow_size(value: object) -> int:
    if isinstance(value, collections.abc.Sized) and not isinstance(
        value, jinja2.Undefined
    ):
        return len(value)
    return 0


def _counted_iter(
    items: collections.abc.Iterable[object], cost: int
) -> collections.abc.Iterator[object]:
    for item in items:
        _spend(cost)
        yield item


async def _counted_aiter(
    items: collections.abc.AsyncIterable[object], cost: int
) -> collections.abc.AsyncIterator[object]:
    async for item in items:
        _spend(cost)
        yield item


def _charge(value: object) -> object:
    """Charge for the value a filter receives.

    An iterator is wrapped so that each item it gives costs one unit,
    because its length is not known before it is consumed.
    """
    if isinstance(value, collections.abc.AsyncIterator):
        return _counted_aiter(
            typing.cast('collections.abc.AsyncIterator[object]', value), 1
        )
    if isinstance(value, collections.abc.Iterator):
        return _counted_iter(
            typing.cast('collections.abc.Iterator[object]', value), 1
        )
    _spend(1 + _shallow_size(value))
    return value


_PASS_ARGS = (
    jinja2.runtime.Context,
    jinja2.nodes.EvalContext,
    jinja2.Environment,
)


def _charged_filter(
    fn: collections.abc.Callable[..., object],
) -> collections.abc.Callable[..., object]:
    """Wrap a filter so it charges for the value it receives.

    :func:`functools.wraps` copies the Jinja ``pass_*`` marker, so the
    wrapper receives the same arguments as ``fn``.
    """

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        values = list(args)
        charged_input = False
        for i, arg in enumerate(values):
            if isinstance(arg, _PASS_ARGS):
                continue
            if not charged_input:
                values[i] = _charge(arg)
                charged_input = True
            else:
                _spend(_shallow_size(arg))
        for arg in kwargs.values():
            _spend(_shallow_size(arg))
        return fn(*values, **kwargs)

    return wrapper


def _charged_test(
    fn: collections.abc.Callable[..., object],
) -> collections.abc.Callable[..., object]:
    """Wrap a test so each call pays for the size of its operands.

    ``select``, ``reject``, and the ``in`` test call a test once for
    each item, so an uncharged test against a large operand would do
    work the budget never sees.
    """

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        _spend(
            1
            + sum(
                _shallow_size(arg)
                for arg in args
                if not isinstance(arg, _PASS_ARGS)
            )
            + sum(_shallow_size(arg) for arg in kwargs.values())
        )
        return fn(*args, **kwargs)

    return wrapper


def _sort_cost(value: object) -> None:
    """Charge ``n * log2(n)`` for a sort over ``n`` items."""
    n = _shallow_size(value)
    _spend(n * max(n.bit_length(), 1))


def _sorting_filter(
    fn: collections.abc.Callable[..., object],
) -> collections.abc.Callable[..., object]:
    """Wrap ``sort``, ``unique``, or ``dictsort`` with a sort charge.

    An iterator is read into a list first (one unit per item), so its
    length is known before the sort.
    """

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        values = list(args)
        for i, arg in enumerate(values):
            if isinstance(arg, _PASS_ARGS):
                continue
            if isinstance(arg, collections.abc.Iterator):
                arg = values[i] = list(
                    _counted_iter(
                        typing.cast('collections.abc.Iterator[object]', arg), 1
                    )
                )
            _sort_cost(arg)
            break
        return fn(*values, **kwargs)

    return wrapper


_COMPARE: dict[str, collections.abc.Callable[[object, object], object]] = {
    'eq': lambda a, b: a == b,
    'ne': lambda a, b: a != b,
    'gt': lambda a, b: a > b,  # type: ignore[operator]
    'gteq': lambda a, b: a >= b,  # type: ignore[operator]
    'lt': lambda a, b: a < b,  # type: ignore[operator]
    'lteq': lambda a, b: a <= b,  # type: ignore[operator]
    'in': lambda a, b: a in b,  # type: ignore[operator]
    'notin': lambda a, b: a not in b,  # type: ignore[operator]
}


def _safe_tojson(
    eval_ctx: jinja2.nodes.EvalContext, value: object, indent: object = None
) -> str:
    # ``json.dumps`` writes ``indent`` once for each line, so a large
    # indent makes a huge value before any check can run.
    if indent is not None:
        raise RenderError('tojson does not accept an indent')
    _check_size(value)
    _spend(_measure(value))
    return jinja2.filters.do_tojson(eval_ctx, value)


def _safe_indent(
    value: str, width: int | str = 4, first: bool = False, blank: bool = False
) -> str:
    _check_size(value)
    text = str(value)
    pad = len(width) if isinstance(width, str) else max(width, 0)
    size = len(text) + pad * (text.count('\n') + 1)
    if size > MAX_OUTPUT:
        raise _too_large(size)
    return jinja2.filters.do_indent(text, width, first, blank)


def _safe_replace(
    eval_ctx: jinja2.nodes.EvalContext,
    s: str,
    old: str,
    new: str,
    count: int | None = None,
) -> str:
    text, old, new = str(s), str(old), str(new)
    hits = text.count(old) if old else len(text) + 1
    if count is not None and count >= 0:
        hits = min(hits, count)
    size = len(text) + hits * max(len(new) - len(old), 0)
    if size > MAX_OUTPUT:
        raise _too_large(size)
    return jinja2.filters.do_replace(eval_ctx, text, old, new, count)


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
    size = _measure(items) + len(d) * max(len(items) - 1, 0)
    if size > MAX_OUTPUT:
        raise _too_large(size)
    return jinja2.filters.sync_do_join(eval_ctx, items, d, attribute)


def _safe_string(value: object) -> str:
    _check_size(value)
    return str(value)


def _finalize(value: object) -> object:
    """Check each ``{{ }}`` value before it is turned into text."""
    _check_size(value)
    _spend(_measure(value))
    return value


class _CodeGenerator(jinja2.compiler.CodeGenerator):
    """Send ``~`` through :meth:`_Sandbox.checked_concat`."""

    def visit_Concat(  # noqa: N802 - overrides the Jinja visitor
        self, node: jinja2.nodes.Concat, frame: jinja2.compiler.Frame
    ) -> None:
        self.write('environment.checked_concat((')
        for arg in node.nodes:
            self.visit(arg, frame)
            self.write(', ')
        self.write('))')

    def visit_Getitem(  # noqa: N802 - overrides the Jinja visitor
        self, node: jinja2.nodes.Getitem, frame: jinja2.compiler.Frame
    ) -> None:
        # Jinja compiles a slice to a plain Python subscript, which skips
        # ``environment.getitem``. Send it through ``checked_slice``.
        if not isinstance(node.arg, jinja2.nodes.Slice):
            super().visit_Getitem(node, frame)
            return
        self.write('environment.checked_slice(')
        self.visit(node.node, frame)
        self.write(', slice(')
        for part in (node.arg.start, node.arg.stop, node.arg.step):
            if part is None:
                self.write('None')
            else:
                self.visit(part, frame)
            self.write(', ')
        self.write('))')

    def visit_Compare(  # noqa: N802 - overrides the Jinja visitor
        self, node: jinja2.nodes.Compare, frame: jinja2.compiler.Frame
    ) -> None:
        # Every operand is evaluated before the comparison, so a chain
        # such as ``a < b < c`` does not short-circuit. Template
        # expressions have no side effects, so only the cost differs.
        self.write('environment.checked_compare(')
        self.visit(node.expr, frame)
        self.write(', (')
        for operand in node.ops:
            self.write(f'({operand.op!r}, ')
            self.visit(operand.expr, frame)
            self.write('), ')
        self.write('))')


class _Sandbox(jinja2.sandbox.ImmutableSandboxedEnvironment):
    """Sandbox that checks the size of values before it builds them."""

    code_generator_class = _CodeGenerator
    intercepted_binops = frozenset({'*', '+', '**', '%'})

    @staticmethod
    def checked_concat(values: collections.abc.Iterable[object]) -> str:
        items = list(values)
        _check_size(*items)
        text = ''.join(str(item) for item in items)
        _spend(1 + len(text))
        return text

    @staticmethod
    def checked_compare(
        left: object, ops: collections.abc.Iterable[tuple[str, object]]
    ) -> bool:
        """Compare like Python, paying for the size of each operand."""
        for op, right in ops:
            _spend(1 + _shallow_size(left) + _shallow_size(right))
            if not _COMPARE[op](left, right):
                return False
            left = right
        return True

    @staticmethod
    def checked_iter(iterable: object) -> object:
        """Charge :data:`ITERATION_COST` for each loop iteration."""
        if isinstance(iterable, collections.abc.AsyncIterable):
            return _counted_aiter(
                typing.cast('collections.abc.AsyncIterable[object]', iterable),
                ITERATION_COST,
            )
        return _counted_iter(
            typing.cast('collections.abc.Iterable[object]', iterable),
            ITERATION_COST,
        )

    def call(
        self,
        context: jinja2.runtime.Context,
        obj: typing.Any,
        /,
        *args: typing.Any,
        **kwargs: typing.Any,
    ) -> typing.Any:
        # A method can do work in proportion to the object it is
        # bound to, so the call pays for that object's size.
        owner = getattr(obj, '__self__', None)
        _spend(1 + _shallow_size(owner))
        return super().call(context, obj, *args, **kwargs)

    def call_binop(
        self,
        context: jinja2.runtime.Context,
        operator: str,
        left: typing.Any,
        right: typing.Any,
    ) -> typing.Any:
        ints = isinstance(left, int) and isinstance(right, int)
        if operator == '*':
            if ints:
                if left.bit_length() + right.bit_length() > MAX_INT_BITS:
                    raise RenderError('The integer result is too large')
            else:
                for seq, times in ((left, right), (right, left)):
                    if isinstance(times, int) and not isinstance(times, bool):
                        if _measure(seq) * max(times, 0) > MAX_OUTPUT:
                            raise _too_large(_measure(seq) * times)
        elif operator == '+':
            if not ints:
                _check_size(left, right)
        elif operator == '**':
            if ints and left.bit_length() * abs(right) > MAX_INT_BITS:
                raise RenderError('The integer result is too large')
            if isinstance(right, (int, float)) and abs(right) > MAX_INT_BITS:
                raise RenderError('The exponent is too large')
        elif operator == '%' and not isinstance(left, (int, float)):
            raise RenderError('% is allowed only on numbers')
        result = super().call_binop(context, operator, left, right)
        _spend(1 if ints else 1 + _measure(result, _remaining()))
        return result

    @staticmethod
    def checked_slice(obj: typing.Any, index: slice) -> typing.Any:
        """Slice ``obj``, paying for the size of the copy before it."""
        size = _shallow_size(obj)
        _spend(1 + len(range(*index.indices(size))))
        target: typing.Any = obj
        return target[index]

    def is_safe_attribute(self, obj: object, attr: str, value: object) -> bool:
        if isinstance(obj, (str, bytes, bytearray)):
            return attr in _STR_METHODS and isinstance(obj, str)
        if isinstance(obj, (list, tuple)):
            return False
        if isinstance(obj, dict):
            return attr in _DICT_METHODS
        return super().is_safe_attribute(obj, attr, value)


def _environment() -> _Sandbox:
    env = _Sandbox(
        enable_async=True,
        undefined=jinja2.StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        finalize=_finalize,
    )
    # The stubs type these mappings by their default values only.
    env_globals = typing.cast('dict[str, object]', env.globals)  # type: ignore[redundant-cast]
    env_filters = typing.cast('dict[str, object]', env.filters)
    for name in set(env_globals) - _GLOBALS:
        del env_globals[name]
    for name in set(env_filters) - _FILTERS:
        del env_filters[name]
    env_globals['range'] = _safe_range
    env_filters['indent'] = _safe_indent
    env_filters['join'] = jinja2.pass_eval_context(_safe_join)
    env_filters['replace'] = jinja2.pass_eval_context(_safe_replace)
    env_filters['string'] = _safe_string
    env_filters['tojson'] = jinja2.pass_eval_context(_safe_tojson)
    for name in ('sort', 'unique', 'dictsort'):
        env_filters[name] = _sorting_filter(
            typing.cast(
                'collections.abc.Callable[..., object]', env_filters[name]
            )
        )
    for name, fn in list(env_filters.items()):
        env_filters[name] = _charged_filter(
            typing.cast('collections.abc.Callable[..., object]', fn)
        )
    env_tests = typing.cast('dict[str, object]', env.tests)
    for name, fn in list(env_tests.items()):
        env_tests[name] = _charged_test(
            typing.cast('collections.abc.Callable[..., object]', fn)
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


def _check_structure(node: jinja2.nodes.Node, depth: int = 0) -> None:
    """Reject macros, block assignments, filter blocks, recursive loops,
    and loops nested too deep.
    """
    if isinstance(node, (jinja2.nodes.Macro, jinja2.nodes.CallBlock)):
        raise RenderError('Macros are not allowed')
    # These collect a body in memory, outside the streamed output cap
    # (``self.name()`` renders a block to a string).
    if isinstance(
        node,
        (
            jinja2.nodes.AssignBlock,
            jinja2.nodes.FilterBlock,
            jinja2.nodes.Block,
        ),
    ):
        raise RenderError(
            'Blocks, block assignments, and filter blocks are not allowed'
        )
    # A prompt is one template; there is no loader to pull in others.
    if isinstance(
        node,
        (
            jinja2.nodes.Extends,
            jinja2.nodes.Include,
            jinja2.nodes.Import,
            jinja2.nodes.FromImport,
        ),
    ):
        raise RenderError('extends, include, and import are not allowed')
    if isinstance(node, jinja2.nodes.For):
        if node.recursive:
            raise RenderError('Recursive loops are not allowed')
        depth += 1
        if depth > MAX_LOOP_DEPTH:
            raise RenderError(f'Loops may nest at most {MAX_LOOP_DEPTH} deep')
    for child in node.iter_child_nodes():
        _check_structure(child, depth)


def _parse(source: str) -> jinja2.nodes.Template:
    tree = _ENV.parse(source)
    _check_structure(tree)
    # Send each loop's iterable through ``checked_iter``, so that every
    # iteration takes from the work budget.
    for loop in tree.find_all(jinja2.nodes.For):
        loop.iter = jinja2.nodes.Call(
            jinja2.nodes.EnvironmentAttribute('checked_iter'),
            [loop.iter],
            [],
            None,
            None,
            lineno=loop.lineno,
        )
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


class RenderedDecision(typing.NamedTuple):
    #: A ``dict`` or ``list`` when the state renders to JSON, else text.
    state: object
    questions: dict[str, models.DecisionQuestion]


def decision_sources(
    state: str,
    questions: collections.abc.Mapping[str, models.DecisionQuestion],
) -> dict[str, str]:
    """Return every template of a decision version, by field label.

    The labels (``state``, ``questions.<id>.instructions``,
    ``questions.<id>.criteria.<key>``) name the field in an error.
    Choice option names are not templates: code reads them.
    """
    sources = {'state': state}
    for qid, question in questions.items():
        base = f'questions.{qid}'
        sources[f'{base}.instructions'] = question.instructions
        match question:
            case models.NoulQuestion(criteria=models.NoulCriteria() as c):
                sources[f'{base}.criteria.true'] = c.true
                sources[f'{base}.criteria.false'] = c.false
            case models.ChoiceQuestion(criteria=options):
                for key, text in options.items():
                    if text is not None:
                        sources[f'{base}.criteria.{key}'] = text
            case models.ScoreQuestion(criteria=levels):
                for index, text in enumerate(levels):
                    sources[f'{base}.criteria.{index}'] = text
            case _:
                pass
    return sources


async def _render_sources(
    version: models.PromptVersion,
    variables: collections.abc.Mapping[str, object],
    providers: collections.abc.Mapping[str, Provider],
    sources: collections.abc.Mapping[str, str],
) -> dict[str, str]:
    """Render each template in ``sources`` in a worker process.

    The worker (:mod:`.worker`) runs :func:`render_sources_local`; the
    parent can kill it, so a template that escapes the sandbox budgets
    costs one disposable process. Providers still run here, in the
    caller's process, with the caller's permissions.

    Raises:
        RenderError: As :func:`render_sources_local`, or the worker was
            killed or stopped.

    """
    # Imported here: the pool imports this module.
    from imbi.common.prompts import pool

    validate_variables(version.variable_schema, variables)
    if pool.in_process():
        return await render_sources_local(
            version.variable_schema, variables, providers, sources
        )
    return await pool.get_pool().render_sources(
        version.variable_schema, variables, providers, sources
    )


async def render_sources_local(
    schema: collections.abc.Mapping[str, models.PromptVariable],
    variables: collections.abc.Mapping[str, object],
    providers: collections.abc.Mapping[str, Provider],
    sources: collections.abc.Mapping[str, str],
) -> dict[str, str]:
    """Render each template in ``sources`` under one set of limits.

    This is the sandbox itself. Services call :func:`render` and
    :func:`render_decision`, which run it in a worker process; only the
    worker and the in-process escape hatch call it directly.

    All templates of one render share the output budget, the work
    budget, and the timeout.

    Raises:
        RenderError: The variables are not valid, the template fails or
            breaks a limit, the render takes too long, or the output is
            too large.

    """
    validate_variables(schema, variables)
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
        except RenderError:
            raise
        except (ArithmeticError, TypeError, ValueError) as e:
            raise RenderError(f'{type(e).__name__}: {e}') from e
        return ''.join(parts)

    token = _work.set([MAX_WORK])
    try:
        async with asyncio.timeout(RENDER_TIMEOUT):
            return {key: await one(text) for key, text in sources.items()}
    except TimeoutError as e:
        raise RenderError(
            f'Render took longer than {RENDER_TIMEOUT} seconds'
        ) from e
    finally:
        _work.reset(token)


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
    sources = {'system': version.system} | {
        f'messages.{i}': m.content for i, m in enumerate(version.messages)
    }
    rendered = await _render_sources(version, variables, providers, sources)
    return RenderedPrompt(
        system=rendered['system'],
        messages=[
            models.PromptMessage(
                role=m.role, content=rendered[f'messages.{i}']
            )
            for i, m in enumerate(version.messages)
        ],
    )


def _state_value(text: str) -> object:
    """Send the state as JSON when it is a JSON object or array."""
    try:
        value: object = json.loads(text)
    except ValueError:
        return text
    return value if isinstance(value, (dict, list)) else text


async def render_decision(
    version: models.PromptVersion,
    variables: collections.abc.Mapping[str, object],
    providers: collections.abc.Mapping[str, Provider],
) -> RenderedDecision:
    """Render the state and every question template of ``version``.

    Raises:
        RenderError: As :func:`render`.

    """
    rendered = await _render_sources(
        version,
        variables,
        providers,
        decision_sources(version.state, version.questions),
    )
    questions: dict[str, models.DecisionQuestion] = {}
    for qid, question in version.questions.items():
        base = f'questions.{qid}'
        instructions = rendered[f'{base}.instructions']
        match question:
            case models.NoulQuestion():
                criteria = (
                    None
                    if question.criteria is None
                    else models.NoulCriteria(
                        true=rendered[f'{base}.criteria.true'],
                        false=rendered[f'{base}.criteria.false'],
                    )
                )
                questions[qid] = models.NoulQuestion(
                    instructions=instructions, criteria=criteria
                )
            case models.ChoiceQuestion():
                questions[qid] = models.ChoiceQuestion(
                    instructions=instructions,
                    criteria={
                        key: (
                            None
                            if text is None
                            else rendered[f'{base}.criteria.{key}']
                        )
                        for key, text in question.criteria.items()
                    },
                )
            case models.ScoreQuestion():
                questions[qid] = models.ScoreQuestion(
                    instructions=instructions,
                    criteria=[
                        rendered[f'{base}.criteria.{i}']
                        for i in range(len(question.criteria))
                    ],
                )
    return RenderedDecision(
        state=_state_value(rendered['state']), questions=questions
    )
