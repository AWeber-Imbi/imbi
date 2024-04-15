from __future__ import annotations

import datetime
import inspect
import logging
import types

import typing_extensions as typing

if typing.TYPE_CHECKING:  # pragma: nocover
    import imbi.models

CompensatingAction: typing.TypeAlias = typing.Callable[
    ['AutomationContext', BaseException], typing.Union[typing.Awaitable[None],
                                                       None]]


async def do_nothing(context: AutomationContext,
                     automation: imbi.models.Automation, *_args: object,
                     **_kwargs: object) -> None:
    context.note_progress('default action running for %s', automation.slug)


class AutomationFailedError(Exception):
    def __init__(self, automation: imbi.models.Automation,
                 error: Exception) -> None:
        super().__init__(f'Automation {automation.slug} failed: {error}')
        self.automation = automation
        self.error = error


class AutomationContext:
    """Run automations with automated cleanup & injected context

    You may want to use the `run_automations` function instead of
    directly creating a context instance.

    The automation context provides a convenient way to run automation
    *actions*. Each *action* is a callable that accepts the context
    instance as it's first parameter. Additional parameters are passed
    via `args` & `kwargs`.

    The context also has a stack of *compensating callbacks* that will
    be invoked if an exception is thrown during the processing of an
    action. The callback stack is *only* invoked when an exception occurs
    and each callback will be invoked exactly once. It is passed the
    context instance and the exception instance that was caught.


    """
    def __init__(self) -> None:
        self.logger = logging.getLogger('AutomationContext')
        self.notes: list[tuple[datetime.datetime, str]] = []
        self._cleanups: list[CompensatingAction] = []

    def note_progress(self, message_format: str, *args: object) -> None:
        """Add a note to the list of notes

        These could be made available in an API response so don't
        log anything sensitive.
        """
        self.logger.info(message_format, *args)
        self.notes.append((datetime.datetime.now(datetime.timezone.utc),
                           message_format % args if args else message_format))

    async def run_automation(self, automation: imbi.models.Automation, *args,
                             **kwargs) -> None:
        self.logger.debug('running automation %s = %r', automation.slug,
                          automation.callable)
        try:
            result = automation.callable(self, automation, *args, **kwargs)
            if inspect.isawaitable(result):
                await result
        except Exception as error:
            self.logger.error(
                'automation %s failed with %s, running %s cleanups',
                automation.slug, error, len(self._cleanups))
            await self._run_cleanups(error)
            raise error

    def add_callback(self, compensating_action: CompensatingAction) -> None:
        """Add a cleanup action"""
        self._cleanups.append(compensating_action)

    # Implement an async context manager that runs cleanups if an
    # exception is raised
    async def __aenter__(self) -> typing.Self:
        return self

    async def __aexit__(self, _exc_type: typing.Type[BaseException] | None,
                        exc_val: BaseException | None,
                        _exc_tb: types.TracebackType | None) -> None:
        if exc_val is not None:
            await self._run_cleanups(exc_val)

    async def _run_cleanups(self, exc: BaseException) -> None:
        cleanups, self._cleanups = self._cleanups, []
        for cleanup in reversed(cleanups):
            try:
                maybe_coro = cleanup(self, exc)
                if inspect.isawaitable(maybe_coro):
                    await maybe_coro
            except Exception as error:
                self.logger.exception('cleanup %r failed with %s', cleanup,
                                      error)
