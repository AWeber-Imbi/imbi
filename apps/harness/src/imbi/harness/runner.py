"""The runner process (plan sections 4.2, 4.3, and 6.3).

The runner registers with imbi-api, gives the executor its credential,
claims a chain, and runs the claimed task (:class:`task.TaskRun`). The
SDK starts the Claude Code CLI through the ``setpriv`` wrapper
(:data:`task.CLI_WRAPPER`), so the CLI and its tools run as ``agent``.
The in-process ``imbi`` MCP server gives the model ``run_with_secret``:
the runner asks for the resolutions and sends the handles to the
executor. No handle passes through the SDK.

One chain per process (plan section 4.2 step 5): at the end of the
chain the runner kills every ``agent`` process in both containers,
removes the chain workspace, finishes, and exits. It never claims a
second chain. Pod deletion, child tasks, and the tool policy come in
later slices.
"""

import asyncio
import contextlib
import dataclasses
import http
import logging
import os
import pathlib
import shutil
import signal
import time
import typing
import uuid

import httpx

from imbi.harness import api, ipc, kube, privilege, redact, task, version

LOGGER = logging.getLogger(__name__)

POOL_CREDENTIAL = '/var/run/secrets/imbi/pool'
CREDENTIALS = '/run/creds'
WORK = pathlib.Path('/work')
CLAIM_WAIT = 20
#: The time for the shutdown steps after SIGTERM. Less than the pod's
#: terminationGracePeriodSeconds (30), so the fence comes before the
#: SIGKILL.
SHUTDOWN_SECONDS = 20

type Body = api.Body


@dataclasses.dataclass(frozen=True)
class Settings:
    api_url: str
    pool: str
    instance: str
    #: The model when the agent's prompt names none.
    model: str | None

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            api_url=os.environ['IMBI_API_URL'],
            pool=os.environ.get('IMBI_HARNESS_POOL', 'general'),
            instance=os.environ.get('HOSTNAME', 'runner'),
            model=os.environ.get('IMBI_HARNESS_MODEL') or None,
        )


def _fence(reason: str) -> typing.NoReturn:
    """Stop every agent process and exit (plan section 4.3).

    The executor sees the socket close, stops its children, and
    releases their resolutions.
    """
    LOGGER.error('Fencing: %s', reason)
    privilege.kill_agent()
    os._exit(75)


class Runner:
    def __init__(
        self,
        settings: Settings,
        pool_credential: tuple[str, str],
        credentials: pathlib.Path,
    ) -> None:
        self.settings = settings
        self.api = api.Api(settings.api_url)
        self.pool_credential = pool_credential
        self.credentials = credentials
        self.runner_id = ''
        self.runner_token = ''
        self.claimed = False
        #: For every event of the chain (plan section 6.6).
        self.redactor = redact.Redactor()
        self.layout: task.Layout | None = None
        #: The task runs of the chain, by short id.
        self.runs: dict[str, asyncio.Task[Body]] = {}
        self.task_runs: list[task.TaskRun] = []
        #: One claimer at a time: a child that one parent claims is in
        #: :attr:`runs` before another parent looks for its own.
        self.claiming = asyncio.Lock()

    async def serve(self) -> None:
        self.remove_old_workspaces()
        while not pathlib.Path(ipc.SOCKET_PATH).exists():  # noqa: ASYNC110
            await asyncio.sleep(0.5)
        while True:
            try:
                await self.cycle()
            except (api.Refused, httpx.HTTPError, OSError) as err:
                LOGGER.warning('Runner cycle failed: %s', err)
            if self.claimed:
                # One chain per process, also after a failure. The
                # ReplicaSet starts a clean pod for the next chain.
                await kube.delete_own_pod()
                return
            await asyncio.sleep(5)

    async def shutdown(self) -> None:
        """``SIGTERM`` (eviction, node drain): plan section 4.2 step 5
        without the pod deletion, in the grace period.

        Stop every ``agent`` process in both containers (the executor
        releases the resolutions of its commands), close the sessions,
        remove the workspace, and finish: imbi-api fences the chain and
        puts it back in the queue with an ``attempt_marker``. What is
        not done in time, the lease sweep does.
        """
        LOGGER.warning('Stopping: SIGTERM')
        for run in self.runs.values():
            run.cancel()
        privilege.kill_agent()
        with contextlib.suppress(OSError):
            await ipc.call({'op': 'end_chain'})
        for task_run in self.task_runs:
            await task_run.abandon('runner_stopped')
        if self.layout is not None:
            await self.end_chain(self.layout.root)
        if self.runner_id:
            with contextlib.suppress(api.Refused, httpx.HTTPError):
                await self.api.finish(self.runner_id, self.runner_token)

    async def cycle(self) -> None:
        """Register, claim one chain, run it, and finish."""
        token = await self.api.pool_token(*self.pool_credential)
        registered = await self.api.register(
            token, self.settings.pool, self.settings.instance, version
        )
        self.runner_id = str(registered['runner_id'])
        self.runner_token = str(registered['runner_token'])
        self.redactor.add(
            self.pool_credential[1],
            self.runner_token,
            str(registered['executor_token']),
        )
        self._write_credential('runner.token', self.runner_token)
        await ipc.call(
            {
                'op': 'hello',
                'executor_token': registered['executor_token'],
            }
        )
        LOGGER.info('Registered runner %s', self.runner_id)
        heartbeat = asyncio.create_task(
            self.heartbeat(int(registered['lease_seconds']))
        )
        try:
            while (claim := await self._claim()) is None:
                pass
            self.claimed = True
            layout = task.Layout(WORK / str(claim['chain_id']))
            try:
                layout.make()
                await self.run_chain(claim, layout)
            finally:
                await self.end_chain(layout.root)
            await self.api.finish(self.runner_id, self.runner_token)
        finally:
            heartbeat.cancel()

    def remove_old_workspaces(self) -> None:
        """Remove the workspace of a chain that a crash left behind."""
        for path in WORK.iterdir():
            try:
                uuid.UUID(path.name)
            except ValueError:
                continue
            LOGGER.warning('Removing the old workspace %s', path)
            with privilege.effective(privilege.AGENT):
                shutil.rmtree(path, ignore_errors=True)

    async def end_chain(self, workspace: pathlib.Path) -> None:
        """Kill every ``agent`` process in both containers, then remove
        the workspace as ``agent``."""
        privilege.kill_agent()
        try:
            await ipc.call({'op': 'end_chain'})
        except OSError as err:
            # The executor is gone, and its children with it.
            LOGGER.warning('end_chain failed: %s', err)
        with privilege.effective(privilege.AGENT):
            shutil.rmtree(workspace, ignore_errors=True)
        if workspace.exists():
            LOGGER.error('Could not remove %s', workspace)

    async def _claim(self) -> Body | None:
        return await self.api.claim(
            self.runner_id, self.runner_token, CLAIM_WAIT
        )

    def _write_credential(self, name: str, value: str) -> None:
        old = os.umask(0o077)
        try:
            (self.credentials / name).write_text(value)
        finally:
            os.umask(old)

    async def heartbeat(self, lease_seconds: int) -> None:
        """Renew the lease. Fence before it expires (plan section 4.3).

        The margin is a third of the lease. The time to stop is one
        ``SIGKILL``. Only a cancel at the end of the chain stops the
        heartbeat; if it stops for any other reason, the runner fences.
        """
        try:
            await self._renew(lease_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001 - nothing renews the lease
            _fence(f'the heartbeat stopped: {type(err).__name__}')
        _fence('the heartbeat stopped')

    async def _renew(self, lease_seconds: int) -> None:
        margin = lease_seconds / 3
        expires = time.monotonic() + lease_seconds
        while True:
            deadline = expires - margin
            await asyncio.sleep(
                max(0.0, min(lease_seconds / 5, deadline - time.monotonic()))
            )
            sent = time.monotonic()
            try:
                async with asyncio.timeout(max(0.1, deadline - sent)):
                    await self.api.heartbeat(self.runner_id, self.runner_token)
                expires = sent + lease_seconds
            except api.Refused as err:
                if err.status == http.HTTPStatus.UNAUTHORIZED:
                    _fence(f'imbi-api does not know the runner: {err.code}')
                LOGGER.warning('Heartbeat refused: %s', err)
            except Exception as err:  # noqa: BLE001 - a failed renewal
                # Only the type: a message can hold a response body.
                LOGGER.warning('Heartbeat failed: %s', type(err).__name__)
            if time.monotonic() >= expires - margin:
                _fence('the lease was not renewed')

    async def run_chain(self, claim: Body, layout: task.Layout) -> None:
        """Run the root task, then wait for every child task that it
        started (plan section 4.2)."""
        self.layout = layout
        await self._start(claim, build=True)
        while pending := [run for run in self.runs.values() if not run.done()]:
            await asyncio.gather(*pending)

    def _start(self, claim: Body, *, build: bool) -> asyncio.Task[Body]:
        assert self.layout is not None  # noqa: S101 - set by run_chain
        self.redactor.add(str(claim['agent_token']))
        task_run = task.TaskRun(
            self.api,
            claim,
            self.layout,
            self.redactor,
            instance=self.settings.instance,
            transcripts=self.credentials / 'transcripts',
            model=self.settings.model,
            build=build,
            children=self.run_child,
        )
        self.task_runs.append(task_run)
        run = asyncio.create_task(task_run.run())
        self.runs[str(claim['task']['short_id'])] = run
        return run

    async def run_child(self, short_id: str) -> Body:
        """Claim child tasks of the chain until ``short_id`` runs, then
        wait for it (H2: a second SDK instance with the child agent's
        identity, in the same workspace).

        Two parents can make children at once, so a claim can return
        the child of the other parent; it starts too, and is in
        :attr:`runs` before the lock is released. The wait is shielded:
        a cancel of the parent does not cancel the child.
        """
        async with self.claiming:
            while short_id not in self.runs:
                claim = await self.api.chain_claim(
                    self.runner_id, self.runner_token
                )
                if claim is None:
                    return {'short_id': short_id, 'status': 'not_claimed'}
                self._start(claim, build=False)
        return await asyncio.shield(self.runs[short_id])


def main() -> None:
    """Start as uid 0, read the root-only secrets, drop, and serve."""
    settings = Settings.from_environment()
    pool_credential = (
        privilege.read_root_file(f'{POOL_CREDENTIAL}/client_id'),
        privilege.read_root_file(f'{POOL_CREDENTIAL}/client_secret'),
    )
    credentials = privilege.make_private_dir(CREDENTIALS, privilege.RUNNER)
    privilege.drop(privilege.RUNNER)
    # Read from the runner's own environment, which the CLI inherits.
    os.environ['CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK'] = '1'
    runner = Runner(settings, pool_credential, credentials)

    async def stop() -> None:
        try:
            async with asyncio.timeout(SHUTDOWN_SECONDS):
                await runner.shutdown()
        except TimeoutError:
            _fence('the shutdown did not end in time')
        os._exit(0)

    async def run() -> None:
        loop = asyncio.get_running_loop()
        stopping: list[asyncio.Task[None]] = []

        def on_signal() -> None:
            if not stopping:
                stopping.append(loop.create_task(stop()))

        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, on_signal)
        try:
            await runner.serve()
        except asyncio.CancelledError:
            # The shutdown cancels the task runs; it exits the process.
            if not stopping:
                raise
            await stopping[0]

    asyncio.run(run())
