"""Run the code of a ``script`` step (ADR 0027).

Needs the ``script`` extra. The workflow engine and the editor preview
of imbi-api both run scripts here, so they share one sandbox
configuration.

Each run takes one checkout of a pool of ``monty`` worker processes. A
worker serves one checkout, then the pool replaces it, so nothing that
a script leaves behind reaches the next script. The script gets no host
functions, no host modules, and no mounts.
"""

import contextlib
import dataclasses
import datetime
import decimal
import json
import math
import typing
from collections import abc

import jsonschema
import pydantic_monty

from imbi.common.workflows.registry import agent, script

#: The largest output of a step, in bytes of JSON.
MAX_OUTPUT_BYTES = 64 * 1024
#: The most printed text that the output keeps, in characters.
MAX_STDOUT = 8 * 1024
#: The most printed text a script can make. More fails the script as
#: over its memory limit.
MAX_PRINT_BYTES = 64 * 1024
#: Seconds the pool waits past a script's own time limit before it
#: kills the worker, for a worker that does not stop itself.
KILL_GRACE = 2.0
#: Seconds a run waits for a free worker.
CHECKOUT_TIMEOUT = 10.0
#: The deepest nesting of a result.
MAX_DEPTH = 32
#: The longest error message kept, in characters.
MAX_MESSAGE = 200

_VALIDATOR = jsonschema.Draft202012Validator


class ScriptError(Exception):
    """The script failed. ``code`` names the cause (ADR 0027)."""

    def __init__(
        self, code: str, message: str = '', *, retry: bool = False
    ) -> None:
        self.code = code
        self.message = message[:MAX_MESSAGE]
        self.retry = retry
        super().__init__(f'{code}: {self.message}' if self.message else code)


class Busy(Exception):
    """No worker became free in time."""


@dataclasses.dataclass(frozen=True)
class Result:
    #: The output of the step, as :class:`.script.Output` holds it.
    output: dict[str, typing.Any]
    #: The port that the step takes.
    port: int


class Runner:
    def __init__(
        self,
        pool: pydantic_monty.AsyncMonty,
        max_memory: int,
        max_seconds: float,
    ) -> None:
        self.pool = pool
        self.max_memory = max_memory
        self.max_seconds = max_seconds

    async def run(
        self, params: script.Params, *, max_seconds: float | None = None
    ) -> Result:
        """Run the script of ``params`` and return the step's output.

        ``max_seconds`` lowers the time limit, never raises it.

        Raises:
            Busy: No worker became free in time.
            ScriptError: The script failed, or its result is not valid.

        """
        seconds = min(self.max_seconds, max_seconds or self.max_seconds)
        printed = pydantic_monty.CollectString(max_bytes=MAX_PRINT_BYTES)
        try:
            async with self.pool.checkout(
                limits={
                    'max_memory': self.max_memory,
                    'max_feed_duration_secs': seconds,
                }
            ) as session:
                value = await session.feed_run(
                    params.code,
                    inputs=params.inputs,
                    print_callback=printed,
                )
        except TimeoutError as e:  # Only the checkout raises it.
            raise Busy from e
        except pydantic_monty.MontySyntaxError as e:
            raise ScriptError('script_syntax_error', str(e)) from e
        except pydantic_monty.MontyRuntimeError as e:
            raise _runtime_error(e) from e
        except pydantic_monty.MontyCrashedError as e:
            if e.timed_out:
                raise ScriptError('script_timeout') from e
            raise ScriptError('script_crashed', retry=True) from e
        except pydantic_monty.MontyError as e:
            raise ScriptError('script_error', str(e)) from e
        return result(params, value, printed.output)


@contextlib.asynccontextmanager
async def open_runner(
    *, processes: int, max_memory: int, max_seconds: float
) -> abc.AsyncGenerator[Runner]:
    """Start a pool of ``processes`` workers, and stop it after.

    Raises:
        RuntimeError: The ``monty`` worker does not start.

    """
    async with pydantic_monty.AsyncMonty(
        max_processes=processes,
        max_checkouts_per_worker=1,
        checkout_timeout=CHECKOUT_TIMEOUT,
        request_timeout=max_seconds + KILL_GRACE,
    ) as pool:
        yield Runner(pool, max_memory, max_seconds)


def _runtime_error(error: pydantic_monty.MontyRuntimeError) -> ScriptError:
    exception = error.exception()
    if isinstance(exception, TimeoutError):
        return ScriptError('script_timeout')
    if isinstance(exception, MemoryError):
        return ScriptError('script_memory')
    return ScriptError('script_error', error.display(format='type-msg'))


def result(params: script.Params, value: typing.Any, printed: str) -> Result:
    """Return the output of a script that returned ``value``.

    Raises:
        ScriptError: ``value`` is not a valid result.

    """
    if not isinstance(value, dict):
        raise _invalid(
            f'the last expression is a {type(value).__name__}, not a dict'
        )
    found = typing.cast('dict[str, typing.Any]', _Converter().convert(value))
    branch: typing.Any = None
    port = 0
    if params.branches:
        branch = found.pop(script.BRANCH_FIELD, None)
        if branch not in params.branches:
            raise ScriptError(
                'script_branch_invalid',
                f'{script.BRANCH_FIELD!r} must be one of '
                + ', '.join(params.branches),
            )
        port = params.branches.index(branch)
    output = script.Output(
        result=found, branch=branch, stdout=printed[:MAX_STDOUT] or None
    ).model_dump()
    size = len(json.dumps(output, ensure_ascii=False).encode())
    if size > MAX_OUTPUT_BYTES:
        raise ScriptError(
            'script_output_too_large',
            f'{size} bytes of JSON, more than {MAX_OUTPUT_BYTES}',
        )
    schema = typing.cast(
        'dict[str, typing.Any]', agent.output_schema(params.output_fields)
    )
    error = jsonschema.exceptions.best_match(
        _VALIDATOR(
            schema, format_checker=_VALIDATOR.FORMAT_CHECKER
        ).iter_errors(found)
    )
    if error is not None:
        where = '.'.join(str(p) for p in error.absolute_path) or 'result'
        raise _invalid(f'{where}: {error.message}')
    # After the check: the schema does not permit the None that this
    # sets for an optional field that the script left out.
    output['result'] = agent.complete_result(params.output_fields, found)
    return Result(output=output, port=port)


def _invalid(message: str) -> ScriptError:
    return ScriptError('script_output_invalid', message)


class _Converter:
    """Convert a result to JSON types, within a budget of bytes.

    A script can return one list many times over, such as ``[a] * 1000``
    where ``a`` is ``[0] * 1000``. It crosses to the host as shared
    references, so its full form can be much larger than the memory
    limit of the sandbox. Each value is charged no more than the bytes
    of its JSON, so the walk stops as soon as the result cannot fit in
    :data:`MAX_OUTPUT_BYTES`, before it expands the rest.
    """

    def __init__(self) -> None:
        self.left = MAX_OUTPUT_BYTES

    def _charge(self, size: int) -> None:
        self.left -= size
        if self.left < 0:
            raise ScriptError(
                'script_output_too_large',
                f'the result is more than {MAX_OUTPUT_BYTES} bytes of JSON',
            )

    def convert(self, value: typing.Any, depth: int = 0) -> typing.Any:
        """Return ``value`` with JSON types only.

        Raises:
            ScriptError: A value has no JSON form, nests too deep, or
                the result is too large.

        """
        if depth > MAX_DEPTH:
            raise _invalid(f'the result nests deeper than {MAX_DEPTH}')
        # A comma or a bracket: every value takes one byte at least.
        self._charge(1)
        match value:
            case str():
                self._charge(len(value))
                return value
            case None | bool():
                return value
            case int():
                # Python cannot write an int of more than 4300 digits
                # as text, and JSON readers lose precision past 64 bits.
                if not -(2**63) <= value < 2**64:
                    raise _invalid('an integer is out of the 64-bit range')
                return value
            case float() | decimal.Decimal():
                number = float(value)
                if not math.isfinite(number):
                    raise _invalid(f'{value} is not a finite number')
                return number
            case datetime.datetime() | datetime.date() | datetime.time():
                return self.convert(value.isoformat(), depth)
            case dict():
                mapping = typing.cast('dict[typing.Any, typing.Any]', value)  # type: ignore[redundant-cast]
                found: dict[str, typing.Any] = {}
                for key, item in mapping.items():
                    if not isinstance(key, str):
                        raise _invalid('a dict key is not a string')
                    self._charge(len(key) + 1)
                    found[key] = self.convert(item, depth + 1)
                return found
            case list() | tuple() | set() | frozenset():
                items = typing.cast('abc.Iterable[typing.Any]', value)
                return [self.convert(v, depth + 1) for v in items]
            case _:
                raise _invalid(f'a {type(value).__name__} has no JSON form')
