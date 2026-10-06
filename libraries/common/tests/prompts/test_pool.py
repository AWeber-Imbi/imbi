"""Tests for rendering prompt templates in worker processes."""

import asyncio
import os
import pathlib
import signal
import sys
import time
import unittest
from unittest import mock

from imbi.common import models
from imbi.common.prompts import pool, rendering

LINUX = sys.platform.startswith('linux')

#: A worker that starts, then never answers: it stands in for a template
#: that is CPU-bound and never yields.
HANG = (
    sys.executable,
    '-c',
    'import json, sys, time\n'
    'print(json.dumps({"type": "ready"}), flush=True)\n'
    'sys.stdin.readline()\n'
    'time.sleep(600)\n',
)


def version(
    system: str, **schema: models.PromptVariable
) -> models.PromptVersion:
    prompt = models.Prompt(namespace='demo', name='Demo', slug='core')
    return models.PromptVersion(
        prompt=prompt,
        prompt_id=prompt.id,
        n=1,
        system=system,
        variable_schema=schema,
        content_sha256='x',
        created_by='test',
    )


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class PoolTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        await pool.shutdown()

    async def render(
        self,
        system: str,
        variables: dict[str, object] | None = None,
        providers: dict[str, rendering.Provider] | None = None,
        **schema: models.PromptVariable,
    ) -> str:
        result = await rendering.render(
            version(system, **schema), variables or {}, providers or {}
        )
        return result.system


class RenderTestCase(PoolTestCase):
    async def test_renders_in_a_worker(self) -> None:
        text = await self.render(
            'Hi {{ name }}',
            {'name': 'Ada'},
            name=models.PromptVariable(type='str'),
        )
        self.assertEqual(text, 'Hi Ada')
        pids = pool.get_pool().pids
        self.assertEqual(len(pids), 1)
        self.assertNotEqual(pids[0], os.getpid())

    async def test_render_errors_keep_the_worker(self) -> None:
        with self.assertRaises(rendering.RenderError):
            await self.render('{{ missing }}')
        before = pool.get_pool().pids
        self.assertEqual(await self.render('ok'), 'ok')
        self.assertEqual(pool.get_pool().pids, before)

    async def test_provider_round_trip_is_memoized(self) -> None:
        calls: list[object] = []

        async def project(project_id: object) -> object:
            calls.append(project_id)
            return {'name': f'P{project_id}'}

        text = await self.render(
            '{{ project(1).name }} {{ project(1).name }} '
            '{{ project(2).name }}',
            providers={'project': project},
        )
        self.assertEqual(text, 'P1 P1 P2')
        self.assertEqual(calls, [1, 2])

    async def test_provider_exception_reaches_the_caller(self) -> None:
        class Denied(Exception):
            pass

        async def project(project_id: object) -> object:
            raise Denied(project_id)

        with self.assertRaises(Denied):
            await self.render(
                '{{ project(1).name }}', providers={'project': project}
            )
        # The worker reported the failure and stays usable.
        self.assertEqual(await self.render('ok'), 'ok')

    async def test_provider_result_is_size_checked(self) -> None:
        async def project(project_id: object) -> object:
            return {'blob': 'x' * (rendering.MAX_OUTPUT + 1)}

        with self.assertRaisesRegex(rendering.RenderError, 'returned more'):
            await self.render(
                '{{ project(1).blob }}', providers={'project': project}
            )

    async def test_concurrent_renders_are_isolated(self) -> None:
        names = [f'n{i}' for i in range(8)]
        results = await asyncio.gather(
            *(
                self.render(
                    '{{ name }}',
                    {'name': n},
                    name=models.PromptVariable(type='str'),
                )
                for n in names
            )
        )
        self.assertEqual(results, names)
        self.assertLessEqual(len(pool.get_pool().pids), pool.get_pool().size)

    async def test_decision_renders_in_a_worker(self) -> None:
        prompt = models.Prompt(
            namespace='demo', name='Demo', slug='decide', kind='decision'
        )
        decision = models.PromptVersion(
            prompt=prompt,
            prompt_id=prompt.id,
            n=1,
            state='{"ticket": {{ t | tojson }}}',
            questions={
                'urgent': models.NoulQuestion(
                    instructions='Is {{ t }} urgent?'
                )
            },
            variable_schema={'t': models.PromptVariable(type='str')},
            content_sha256='x',
            created_by='test',
        )
        result = await rendering.render_decision(decision, {'t': 'down'}, {})
        self.assertEqual(result.state, {'ticket': 'down'})
        self.assertEqual(
            result.questions['urgent'].instructions, 'Is down urgent?'
        )


class FailureTestCase(PoolTestCase):
    async def test_hung_worker_is_killed_and_replaced(self) -> None:
        hung: list[int] = []
        start = pool._Worker.start

        async def record() -> object:
            worker = await start()
            hung.append(worker.pid)
            return worker

        with (
            mock.patch.object(pool, 'WORKER_COMMAND', HANG),
            mock.patch.object(pool._Worker, 'start', record),
            mock.patch.object(rendering, 'RENDER_TIMEOUT', 0.2),
            mock.patch.object(pool, 'KILL_GRACE', 0.1),
        ):
            started = time.monotonic()
            with self.assertRaisesRegex(rendering.RenderError, 'longer than'):
                await self.render('x')
            self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(len(hung), 1)
        self.assertFalse(alive(hung[0]))
        self.assertEqual(pool.get_pool().pids, [])
        # The next render starts a real worker and succeeds.
        self.assertEqual(await self.render('ok'), 'ok')

    async def test_slow_provider_is_bounded_by_the_timeout(self) -> None:
        async def project(project_id: object) -> object:
            await asyncio.sleep(60)
            return {}

        with mock.patch.object(rendering, 'RENDER_TIMEOUT', 0.2):
            with mock.patch.object(pool, 'KILL_GRACE', 0.1):
                with self.assertRaises(rendering.RenderError):
                    await self.render(
                        '{{ project(1) }}', providers={'project': project}
                    )
        self.assertEqual(await self.render('ok'), 'ok')

    async def test_late_provider_reply_does_not_break_the_worker(
        self,
    ) -> None:
        # The provider answers after the worker's own timeout but before
        # the parent's, so the parent sends a reply the worker no longer
        # waits for. The kept worker must ignore it on the next render.
        async def project(project_id: object) -> object:
            await asyncio.sleep(rendering.RENDER_TIMEOUT + pool.KILL_GRACE / 2)
            return {'name': 'x'}

        with self.assertRaisesRegex(rendering.RenderError, 'longer than'):
            await self.render(
                '{{ project(1).name }}', providers={'project': project}
            )
        pids = pool.get_pool().pids
        self.assertEqual(await self.render('ok'), 'ok')
        self.assertEqual(pool.get_pool().pids, pids)

    async def test_crashed_worker_is_replaced(self) -> None:
        async def project(project_id: object) -> object:
            for pid in pool.get_pool().pids:
                os.kill(pid, signal.SIGKILL)
            await asyncio.sleep(0.2)
            return {'name': 'x'}

        with self.assertRaisesRegex(rendering.RenderError, 'worker failed'):
            await self.render(
                '{{ project(1).name }}', providers={'project': project}
            )
        self.assertEqual(await self.render('ok'), 'ok')

    async def test_worker_is_recycled(self) -> None:
        await pool.shutdown()
        with mock.patch.dict(
            os.environ, {'IMBI_PROMPT_WORKER_MAX_RENDERS': '2'}
        ):
            first = None
            for _ in range(2):
                await self.render('ok')
                first = first or pool.get_pool().pids
            await self.render('ok')
            self.assertNotEqual(pool.get_pool().pids, first)

    async def test_oversized_result_is_rejected(self) -> None:
        script = (
            sys.executable,
            '-c',
            'import json, sys\n'
            'print(json.dumps({"type": "ready"}), flush=True)\n'
            'm = json.loads(sys.stdin.readline())\n'
            f'big = "x" * {rendering.MAX_OUTPUT + 10}\n'
            'print(json.dumps({"type": "result", "id": m["id"],'
            ' "rendered": {"system": big}}), flush=True)\n'
            'sys.stdin.readline()\n',
        )
        with mock.patch.object(pool, 'WORKER_COMMAND', script):
            with self.assertRaisesRegex(rendering.RenderError, 'too much'):
                await self.render('x')

    async def test_in_process_escape_hatch(self) -> None:
        await pool.shutdown()
        with mock.patch.dict(
            os.environ, {'IMBI_PROMPT_RENDER_INPROCESS': 'true'}
        ):
            self.assertEqual(await self.render('ok'), 'ok')
        self.assertIsNone(pool._current)


class IsolationTestCase(PoolTestCase):
    def test_worker_env_has_no_secrets(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                'POSTGRES_URL': 'postgresql://user:secret@db/imbi',
                'IMBI_AUTH_JWT_SECRET': 'secret',
                'ANTHROPIC_API_KEY': 'secret',
                'IMBI_PROMPT_WORKER_MEMORY_MB': '64',
            },
        ):
            env = pool._worker_env()
        self.assertNotIn('POSTGRES_URL', env)
        self.assertNotIn('IMBI_AUTH_JWT_SECRET', env)
        self.assertNotIn('ANTHROPIC_API_KEY', env)
        self.assertEqual(env['IMBI_PROMPT_WORKER_MEMORY_MB'], '64')

    @unittest.skipUnless(LINUX, '/proc is Linux only')
    async def test_running_worker_has_no_secrets(self) -> None:
        with mock.patch.dict(os.environ, {'POSTGRES_URL': 'secret-url'}):
            await self.render('ok')
        pid = pool.get_pool().pids[0]
        environ = await asyncio.to_thread(
            pathlib.Path(f'/proc/{pid}/environ').read_bytes
        )
        self.assertNotIn(b'POSTGRES_URL', environ)
        self.assertNotIn(b'secret-url', environ)

    @unittest.skipUnless(LINUX, 'RLIMIT_AS is enforced on Linux only')
    async def test_memory_limit_stops_the_render(self) -> None:
        await pool.shutdown()
        with mock.patch.dict(
            os.environ, {'IMBI_PROMPT_WORKER_MEMORY_MB': '1'}
        ):
            # Each value is within the sandbox size limits and nothing is
            # output, but together they hold about 2.4 MB.
            source = (
                ''.join(f'{{% set v{i} = "x" * 200000 %}}' for i in range(12))
                + 'done'
            )
            with self.assertRaisesRegex(
                rendering.RenderError, 'more memory than allowed'
            ):
                await self.render(source)
            # The worker that ran out of memory is replaced.
            self.assertEqual(await self.render('ok'), 'ok')


class LifespanTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_starts_and_stops_workers(self) -> None:
        async with pool.pool_lifespan():
            pids = pool.get_pool().pids
            self.assertEqual(len(pids), pool.get_pool().size)
        for pid in pids:
            self.assertFalse(alive(pid))
