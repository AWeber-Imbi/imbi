from __future__ import annotations

import inspect
import typing
import unittest.mock
import uuid

import sprockets_postgres  # type: ignore[import-untyped]

from imbi import automations, user


class AnyInstanceOf:
    """Make any "equality" check work with isinstance

    This is particularly useful to verify that a mock
    was called with a specific type of object without
    having to know the identity of the object::

        mocked.assert_called_once_with(
           AnyInstanceOf(automations.AutomationContext))

    """
    def __init__(self, cls: type) -> None:
        self.expected_class = cls

    def __eq__(self, other: object) -> bool:
        if isinstance(other, self.expected_class):
            return True
        return NotImplemented


class AutomationContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = unittest.mock.Mock(spec=user.User)
        self.query_function = unittest.mock.AsyncMock()
        self.context = automations.AutomationContext(self.application,
                                                     self.user,
                                                     self.query_function)

    async def test_callbacks_called_upon_failure(self) -> None:
        sync_callback = unittest.mock.Mock()
        async_callback = unittest.mock.AsyncMock()
        error = RuntimeError()
        with self.assertRaises(RuntimeError):
            async with self.context:
                self.context.add_callback(sync_callback)
                self.context.add_callback(async_callback)
                raise error

        sync_callback.assert_called_once_with(self.context, error)
        async_callback.assert_awaited_once_with(self.context, error)

    async def test_callbacks_are_not_called_upon_success(self) -> None:
        sync_callback = unittest.mock.Mock()
        async_callback = unittest.mock.AsyncMock()
        async with self.context:
            self.context.add_callback(sync_callback)
            self.context.add_callback(async_callback)

        sync_callback.assert_not_called()
        async_callback.assert_not_awaited()

    async def test_run_automation(self) -> None:
        automation = unittest.mock.Mock()

        await self.context.run_automation(automation,
                                          unittest.mock.sentinel.pos_arg,
                                          keyword=unittest.mock.sentinel.kwarg)
        automation.callable.assert_called_once_with(
            self.context,
            automation,
            unittest.mock.sentinel.pos_arg,
            keyword=unittest.mock.sentinel.kwarg)

        automation.callable = unittest.mock.AsyncMock()
        await self.context.run_automation(automation,
                                          unittest.mock.sentinel.pos_arg,
                                          keyword=unittest.mock.sentinel.kwarg)
        automation.callable.assert_awaited_once_with(
            self.context,
            automation,
            unittest.mock.sentinel.pos_arg,
            keyword=unittest.mock.sentinel.kwarg)

        failure = RuntimeError()
        automation.callable = unittest.mock.AsyncMock(side_effect=failure)
        compensating_action = unittest.mock.Mock()
        self.context.add_callback(compensating_action)
        with self.assertRaises(failure.__class__):
            await self.context.run_automation(
                automation,
                unittest.mock.sentinel.pos_arg,
                keyword=unittest.mock.sentinel.kwarg)
        automation.callable.assert_awaited_once_with(
            self.context,
            automation,
            unittest.mock.sentinel.pos_arg,
            keyword=unittest.mock.sentinel.kwarg)
        compensating_action.assert_called_once_with(self.context, failure)

    async def test_that_failing_callbacks_are_reported(self) -> None:
        class Automation:
            def __init__(self) -> None:
                self.slug = str(uuid.uuid4())
                self.action = unittest.mock.AsyncMock()
                self.callback = unittest.mock.AsyncMock()

            async def callable(self, c: automations.AutomationContext, *args,
                               **kwargs) -> None:
                await self.action(c, *args, **kwargs)
                c.add_callback(self.callback)

        autos = [Automation() for _ in range(3)]

        # make the last automation fail
        failure = RuntimeError()
        autos[-1].action.side_effect = failure

        # make the first automation's cleanup fail... we want to
        # verify that the failure is ignored
        autos[0].callback.side_effect = ValueError()

        with self.assertRaises(RuntimeError) as cm:
            with self.assertLogs(self.context.logger) as log:
                async with self.context:
                    for a in autos:
                        await self.context.run_automation(a)
        self.assertIs(failure, cm.exception)
        for record in log.records:
            if (record.levelname == 'ERROR'
                    and record.msg == 'cleanup %r failed with %s'):
                break
        else:
            self.fail('Expected to find exception for cleanup failure')

        # verify that all actions were invoked
        for a in autos:
            a.action.assert_awaited_once_with(self.context, a)

        # verify that all callbacks except for the last one were invoked
        # with the correct parameters
        for a in autos[:-1]:
            a.callback.assert_awaited_once_with(self.context, failure)

        # verify that the final callback was not invoked
        autos[-1].callback.assert_not_awaited()

    async def test_using_context_from_within_action(self) -> None:
        class Automation:
            def __init__(self, side_effect: Exception | None = None) -> None:
                self.slug = ''
                self.action = unittest.mock.Mock(side_effect=side_effect)
                self.callback = unittest.mock.Mock()

            def callable(self, c: automations.AutomationContext,
                         automation: typing.Self, param: int) -> None:
                self.action()
                c.note_progress('action: param:%s', param)
                c.add_callback(self.callback)

        error = RuntimeError()
        autos = [Automation(), Automation(error)]

        with self.assertRaises(RuntimeError):
            async with self.context:
                for param, act in enumerate(autos):
                    await self.context.run_automation(act, param)
        self.assertEqual(1, len(self.context.notes))
        self.assertEqual(['action: param:0'],
                         [n[1] for n in self.context.notes])
        autos[0].callback.assert_called_once_with(self.context, error)


class RunAutomationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.executor = unittest.mock.AsyncMock(
            spec=sprockets_postgres.RequestHandlerMixin)
        self.user = unittest.mock.Mock(spec=user.User)
        self.automations = [unittest.mock.Mock() for _ in range(3)]
        for automation in self.automations:
            automation.callable = unittest.mock.AsyncMock()

    async def test_that_context_is_correct(self) -> None:
        action = unittest.mock.AsyncMock()
        actions = [unittest.mock.Mock(callable=action)]
        await automations.run_automations(actions,
                                          user=self.user,
                                          query_executor=self.executor)
        action.assert_awaited_once_with(
            AnyInstanceOf(automations.AutomationContext), actions[0])
        context = typing.cast(automations.AutomationContext,
                              action.call_args[0][0])
        self.assertIs(self.user, context.user)
        self.assertIs(self.executor.postgres_execute, context.run_query)

    async def test_without_explicit_callbacks(self) -> None:
        await automations.run_automations(self.automations,
                                          user=self.user,
                                          query_executor=self.executor)
        for automation in self.automations:
            automation.callable.assert_awaited_once_with(
                AnyInstanceOf(automations.AutomationContext), automation)

    async def test_with_explicit_callbacks(self) -> None:
        error = RuntimeError()
        callbacks = [
            unittest.mock.AsyncMock() for _ in range(len(self.automations))
        ]
        self.automations[-1].callable.side_effect = error
        with self.assertRaises(automations.AutomationFailedError):
            await automations.run_automations(self.automations,
                                              user=self.user,
                                              query_executor=self.executor,
                                              addt_callbacks=callbacks)
        for cb in callbacks:
            cb.assert_awaited_once_with(
                AnyInstanceOf(automations.AutomationContext), error)

    async def test_without_automations(self) -> None:
        callbacks = [unittest.mock.AsyncMock()]
        await automations.run_automations([],
                                          user=self.user,
                                          query_executor=self.executor,
                                          addt_callbacks=callbacks)
        callbacks[0].assert_not_awaited()

    async def test_with_sync_and_nonsync_operations(self) -> None:
        sync_ops = [unittest.mock.Mock() for _ in range(3)]
        async_ops = [unittest.mock.AsyncMock() for _ in range(3)]
        actions = [
            unittest.mock.Mock(callable=op) for op in sync_ops + async_ops
        ]
        await automations.run_automations(
            actions,
            user=self.user,
            query_executor=self.executor,
        )
        sync_ops[0].assert_called_once_with(
            AnyInstanceOf(automations.AutomationContext),
            unittest.mock.ANY,
        )
        action_iter = iter(actions)
        context = sync_ops[0].call_args[0][0]
        for op, act in zip(sync_ops, action_iter):
            op.assert_called_once_with(context, act)
        for op, act in zip(async_ops, action_iter):
            op.assert_awaited_once_with(context, act)

    async def test_insane_edge_case(self) -> None:
        # this strange test covers the unlikely case that
        # something raises in `run_automations` BEFORE we
        # execute a single automation
        with unittest.mock.patch.object(
                automations.AutomationContext,
                'add_callback',
                new=unittest.mock.Mock(side_effect=RuntimeError)):
            with self.assertRaises(RuntimeError):
                await automations.run_automations(
                    self.automations,
                    user=self.user,
                    query_executor=self.executor,
                    addt_callbacks=[unittest.mock.Mock()])


class QueryRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test(self) -> None:
        runner = automations.query_runner(
            unittest.mock.sentinel.metric_name,
            unittest.mock.sentinel.query,
            unittest.mock.sentinel.parameters,
            timeout=unittest.mock.sentinel.timeout)
        self.assertTrue(inspect.iscoroutinefunction(runner),
                        'query_runner should return a coroutine function')

        context = unittest.mock.Mock()
        context.note_progress = unittest.mock.Mock()
        context.run_query = unittest.mock.AsyncMock()
        coro = runner(context, RuntimeError())
        self.assertTrue(inspect.iscoroutine(coro),
                        'query_runner() should return a coroutine')
        result = await coro
        self.assertIsNone(result, 'unexpected return from query runner')

        context.note_progress.assert_called_once_with(
            AnyInstanceOf(str),
            unittest.mock.sentinel.metric_name,
            (unittest.mock.sentinel.parameters, ),
        )
        context.run_query.assert_awaited_once_with(
            unittest.mock.sentinel.query,
            unittest.mock.sentinel.parameters,
            metric_name=unittest.mock.sentinel.metric_name,
            timeout=unittest.mock.sentinel.timeout)
