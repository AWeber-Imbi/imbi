from __future__ import annotations

import typing
import unittest.mock
import uuid

from imbi import automations


class AutomationContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_callbacks_called_upon_failure(self) -> None:
        sync_callback = unittest.mock.Mock()
        async_callback = unittest.mock.AsyncMock()
        error = RuntimeError()
        context = automations.AutomationContext()

        with self.assertRaises(RuntimeError):
            async with context:
                context.add_callback(sync_callback)
                context.add_callback(async_callback)
                raise error

        sync_callback.assert_called_once_with(context, error)
        async_callback.assert_awaited_once_with(context, error)

    async def test_callbacks_are_not_called_upon_success(self) -> None:
        sync_callback = unittest.mock.Mock()
        async_callback = unittest.mock.AsyncMock()
        async with automations.AutomationContext() as context:
            context.add_callback(sync_callback)
            context.add_callback(async_callback)

        sync_callback.assert_not_called()
        async_callback.assert_not_awaited()

    async def test_run_automation(self) -> None:
        automation = unittest.mock.Mock()
        context = automations.AutomationContext()

        await context.run_automation(automation,
                                     unittest.mock.sentinel.pos_arg,
                                     keyword=unittest.mock.sentinel.kwarg)
        automation.callable.assert_called_once_with(
            context,
            automation,
            unittest.mock.sentinel.pos_arg,
            keyword=unittest.mock.sentinel.kwarg)

        automation.callable = unittest.mock.AsyncMock()
        await context.run_automation(automation,
                                     unittest.mock.sentinel.pos_arg,
                                     keyword=unittest.mock.sentinel.kwarg)
        automation.callable.assert_awaited_once_with(
            context,
            automation,
            unittest.mock.sentinel.pos_arg,
            keyword=unittest.mock.sentinel.kwarg)

        failure = RuntimeError()
        automation.callable = unittest.mock.AsyncMock(side_effect=failure)
        compensating_action = unittest.mock.Mock()
        context.add_callback(compensating_action)
        with self.assertRaises(failure.__class__):
            await context.run_automation(automation,
                                         unittest.mock.sentinel.pos_arg,
                                         keyword=unittest.mock.sentinel.kwarg)
        automation.callable.assert_awaited_once_with(
            context,
            automation,
            unittest.mock.sentinel.pos_arg,
            keyword=unittest.mock.sentinel.kwarg)
        compensating_action.assert_called_once_with(context, failure)

    async def test_that_failing_callbacks_are_reported(self) -> None:
        context = automations.AutomationContext()
        failure = RuntimeError()

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
        autos[-1].action.side_effect = failure

        # make the first automation's cleanup fail... we want to
        # verify that the failure is ignored
        autos[0].callback.side_effect = ValueError()

        with self.assertRaises(RuntimeError) as cm:
            with self.assertLogs(context.logger) as log:
                async with context:
                    for a in autos:
                        await context.run_automation(a)
        self.assertIs(failure, cm.exception)
        for record in log.records:
            if (record.levelname == 'ERROR'
                    and record.msg == 'cleanup %r failed with %s'):
                break
        else:
            self.fail('Expected to find exception for cleanup failure')

        # verify that all actions were invoked
        for a in autos:
            a.action.assert_awaited_once_with(context, a)

        # verify that all callbacks except for the last one were invoked
        # with the correct parameters
        for a in autos[:-1]:
            a.callback.assert_awaited_once_with(context, failure)

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

        context = automations.AutomationContext()
        error = RuntimeError()
        autos = [Automation(), Automation(error)]

        with self.assertRaises(RuntimeError):
            async with context:
                for param, act in enumerate(autos):
                    await context.run_automation(act, param)
        self.assertEqual(1, len(context.notes))
        self.assertEqual(['action: param:0'], [n[1] for n in context.notes])
        autos[0].callback.assert_called_once_with(context, error)
