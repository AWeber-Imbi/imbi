from __future__ import annotations

import datetime
import inspect
import logging
import types

import sprockets_postgres  # type: ignore[import-untyped]
import typing_extensions as typing

if typing.TYPE_CHECKING:  # pragma: nocover
    import imbi.app
    import imbi.models
    import imbi.user

CompensatingAction: typing.TypeAlias = typing.Callable[
    ['AutomationContext', BaseException], typing.Union[typing.Awaitable[None],
                                                       None]]


class QueryFunction(typing.Protocol):
    async def __call__(
        self,
        sql: str,
        parameters: sprockets_postgres.QueryParameters = None,
        metric_name: str = '',
        *,
        timeout: sprockets_postgres.Timeout = None
    ) -> sprockets_postgres.QueryResult:  # pragma: nocover
        ...


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

    The context has a number of attributes exported for use inside an
    action.

    - *run_query* is a handle to the sprockets_postgres postgres_execute
      method. Use this for database access.
    - *user* is a `imbi.models.User` instance for the acting user. You
      can use this to retrieve user-specific tokens for external apps
      such as gitlab.

    """
    def __init__(self, application: imbi.app.Application, user: imbi.user.User,
                 query: QueryFunction) -> None:
        self.application = application
        self.logger = logging.getLogger(__name__).getChild('AutomationContext')
        self.notes: list[tuple[datetime.datetime, str]] = []
        self.user = user
        self.run_query = query

        self._cleanups: list[CompensatingAction] = []

    def note_progress(self, message_format: str, *args: object) -> None:
        """Add a note to the list of notes

        These could be made available in an API response so don't
        log anything sensitive.
        """
        self.logger.info(message_format, *args)
        self.notes.append((datetime.datetime.now(datetime.timezone.utc),
                           message_format % args if args else message_format))

    async def run_automation(self, automation: imbi.models.Automation,
                             *args: object, **kwargs: object) -> None:
        self.logger.debug('running automation %s = %r with args %r %r',
                          automation.slug, automation.callable, args, kwargs)
        try:
            result = automation.callable(self, automation, *args, **kwargs)
            if inspect.isawaitable(result):
                await result
        except Exception as error:
            self.logger.exception(
                'automation %s failed with %r, running %s cleanups',
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


async def run_automations(
        automations: typing.Iterable[imbi.models.Automation],
        *args: object,
        application: imbi.app.Application,
        user: imbi.user.User,
        query_executor: sprockets_postgres.RequestHandlerMixin,
        addt_callbacks: typing.Iterable[CompensatingAction] | None = None,
        **kwargs: object) -> None:
    """Run a list of operations in a AutomationContext instance

    `args` and `kwargs` are passed as-is to **every** automation
    callable. If an automation fails, then a AutomationFailedError
    will be raised instead of whatever the automation raised.
    """
    last_automation = None
    try:
        async with AutomationContext(application=application,
                                     query=query_executor.postgres_execute,
                                     user=user) as context:
            for cb in addt_callbacks or []:
                context.add_callback(cb)
            for automation in automations:
                last_automation = automation
                await context.run_automation(automation, *args, **kwargs)
    except Exception as error:
        # only note which automation failed if we ran one
        # AutomationContext.run_automation logs an "action failed" message,
        # so we don't have to
        if last_automation is not None:
            raise AutomationFailedError(last_automation, error) from None
        raise


def query_runner(
    metric_name: str,
    query: str,
    *args: sprockets_postgres.QueryParameters | str,
    **kwargs: sprockets_postgres.Timeout | str,
) -> CompensatingAction:
    """Returns a CompensatingAction that calls context.run_query()

    Use this to create compensating actions that run a simple
    SQL query. If you need to do something more in-depth, then
    write freestanding function.
    """
    kwargs['metric_name'] = metric_name

    async def runner(context: AutomationContext, *_: object) -> None:
        context.note_progress('running query %r with args %r', metric_name,
                              args)
        await context.run_query(query, *args, **kwargs)

    return runner
