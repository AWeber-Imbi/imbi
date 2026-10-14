"""The runner process (plan sections 4.2, 4.3, and 6.3), P5a slice.

The runner registers with imbi-api, gives the executor its credential,
claims a chain, and runs the claimed task in one SDK session. The SDK
starts the Claude Code CLI through the ``setpriv`` wrapper
(:data:`CLI_WRAPPER`), so the CLI and its tools run as ``agent``. The
in-process ``imbi`` MCP server gives the model ``run_with_secret``: the
runner asks for the resolutions and sends the handles to the executor.
No handle passes through the SDK.

One chain per process (plan section 4.2 step 5): at the end of the
chain the runner kills every ``agent`` process in both containers,
removes the chain workspace, finishes, and exits. It never claims a
second chain. P5 then deletes the pod; P5a has no pod deletion and no
task logic (events, tool policy, child tasks).
"""

import asyncio
import dataclasses
import http
import json
import logging
import os
import pathlib
import shutil
import signal
import time
import typing
import uuid

import claude_agent_sdk as sdk
import httpx
from claude_agent_sdk._internal.transport import subprocess_cli

from imbi.harness import api, ipc, privilege, proxy, version

if typing.TYPE_CHECKING:
    from collections import abc

LOGGER = logging.getLogger(__name__)

POOL_CREDENTIAL = '/var/run/secrets/imbi/pool'
MODEL_KEY = '/var/run/secrets/imbi/model/key'
CREDENTIALS = '/run/creds'
WORK = pathlib.Path('/work')
#: ``#!/bin/sh -p`` + ``setpriv --reuid=agent ...`` + the bundled CLI.
CLI_WRAPPER = '/usr/local/bin/agent-cli'
CLAIM_WAIT = 20
RESOLUTION_TTL = 300
TOOLS = ['Bash', 'mcp__imbi__run_with_secret']

type Body = api.Body

_RUN_WITH_SECRET_SCHEMA: dict[str, typing.Any] = {
    'type': 'object',
    'properties': {
        'command': {'type': 'string', 'description': 'A shell command.'},
        'secrets': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'reference': {
                        'type': 'string',
                        'description': 'secret://<scope>/<path>[#<field>]',
                    },
                    'purpose': {'type': 'string'},
                    'env': {
                        'type': 'string',
                        'description': 'The environment variable name.',
                    },
                },
                'required': ['reference', 'purpose', 'env'],
            },
        },
    },
    'required': ['command', 'secrets'],
}


@dataclasses.dataclass(frozen=True)
class Settings:
    api_url: str
    pool: str
    instance: str
    model_url: str
    model: str | None

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            api_url=os.environ['IMBI_API_URL'],
            pool=os.environ.get('IMBI_HARNESS_POOL', 'general'),
            instance=os.environ.get('HOSTNAME', 'runner'),
            model_url=os.environ.get(
                'IMBI_HARNESS_MODEL_URL', 'https://api.anthropic.com'
            ),
            model=os.environ.get('IMBI_HARNESS_MODEL') or None,
        )


class AgentTransport(subprocess_cli.SubprocessCLITransport):
    """Start the CLI wrapper with effective uid 0.

    ``setpriv`` needs ``CAP_SETUID`` when it starts. With
    ``CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK`` set and ``cli_path`` given,
    the only work under uid 0 is the process start.
    """

    async def connect(self) -> None:
        with privilege.effective():
            await super().connect()

    async def close(self) -> None:
        try:
            await super().close()
        except PermissionError:
            # The SDK signals the CLI as the runner after a timeout.
            privilege.kill_agent()


def _fence(reason: str) -> typing.NoReturn:
    """Stop every agent process and exit (plan section 4.3).

    The executor sees the socket close, stops its children, and
    releases their resolutions.
    """
    LOGGER.error('Fencing: %s', reason)
    privilege.kill_agent()
    os._exit(75)


def _cli_stderr(line: str) -> None:
    # The CLI holds no credential, so its stderr holds none.
    LOGGER.info('cli: %s', line.rstrip())


def _tool_error(text: str) -> Body:
    return {'content': [{'type': 'text', 'text': text}], 'is_error': True}


class Runner:
    def __init__(
        self,
        settings: Settings,
        pool_credential: tuple[str, str],
        credentials: pathlib.Path,
        proxy_url: str,
    ) -> None:
        self.settings = settings
        self.api = api.Api(settings.api_url)
        self.pool_credential = pool_credential
        self.credentials = credentials
        self.proxy_url = proxy_url
        self.runner_id = ''
        self.runner_token = ''
        self.claimed = False

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
                # One chain per process, also after a failure.
                return
            await asyncio.sleep(5)

    async def cycle(self) -> None:
        """Register, claim one chain, run it, and finish."""
        token = await self.api.pool_token(*self.pool_credential)
        registered = await self.api.register(
            token, self.settings.pool, self.settings.instance, version
        )
        self.runner_id = str(registered['runner_id'])
        self.runner_token = str(registered['runner_token'])
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
            workspace = self._workspace(str(claim['chain_id']))
            try:
                await self.run_chain(claim, workspace)
            except sdk.ClaudeSDKError:
                # P5 ends the task as failed; P5a only logs it.
                LOGGER.exception('Task %s failed', claim['task']['short_id'])
            finally:
                await self.end_chain(workspace)
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
        ``SIGKILL``.
        """
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
            except (httpx.HTTPError, TimeoutError) as err:
                LOGGER.warning('Heartbeat failed: %s', type(err).__name__)
            if time.monotonic() >= expires - margin:
                _fence('the lease was not renewed')

    def _workspace(self, chain_id: str) -> pathlib.Path:
        """Make ``/work/<chain>`` as ``agent``.

        Mode ``0711``: the executor starts a child there, and the child
        changes its directory before it becomes ``agent``.
        """
        root = WORK / chain_id
        with privilege.effective(privilege.AGENT):
            root.mkdir(mode=0o711, exist_ok=True)
            for name in ('home', 'tmp', '.claude'):
                (root / name).mkdir(mode=0o700, exist_ok=True)
        return root

    def _run_with_secret(
        self, claim: Body, workspace: pathlib.Path
    ) -> sdk.SdkMcpTool[typing.Any]:
        task = claim['task']
        agent_token = str(claim['agent_token'])

        @sdk.tool(
            'run_with_secret',
            'Run a shell command in the workspace with named secrets in '
            'its environment. The output never contains the secrets.',
            _RUN_WITH_SECRET_SCHEMA,
        )
        async def run_with_secret(args: Body) -> Body:
            resolved: list[Body] = []
            try:
                wanted: list[Body] = args.get('secrets') or []
                for secret in wanted:
                    created = await self.api.create_resolution(
                        agent_token,
                        {
                            'short_id': task['short_id'],
                            'reference': secret['reference'],
                            'purpose': secret['purpose'],
                            'ttl_seconds': RESOLUTION_TTL,
                            'delivery': {
                                'mode': 'environment',
                                'target': secret['env'],
                            },
                        },
                    )
                    resolved.append(
                        {
                            'handle': created['handle'],
                            'resolution_id': created['resolution_id'],
                            'purpose': secret['purpose'],
                            'delivery': created['delivery'],
                        }
                    )
                reply = await ipc.call(
                    {
                        'op': 'run',
                        'command': str(args.get('command') or ''),
                        'cwd': str(workspace),
                        'context': {
                            'task_id': task['id'],
                            'agent_id': task['agent_id'],
                            'project_id': task.get('project_id'),
                        },
                        'secrets': resolved,
                    }
                )
            except api.Refused as err:
                return _tool_error(
                    f'The secret request was refused: {err.code}'
                )
            except (httpx.HTTPError, OSError):
                return _tool_error('The secret service is not available')
            except (KeyError, TypeError):
                return _tool_error('The input is not valid')
            if 'error' in reply:
                return _tool_error(
                    f'The command did not run: {reply["error"]}'
                )
            return {
                'content': [
                    {
                        'type': 'text',
                        'text': f'exit code {reply["exit_code"]}\n'
                        f'{reply["output"]}',
                    }
                ]
            }

        return run_with_secret

    async def run_chain(self, claim: Body, workspace: pathlib.Path) -> None:
        """Run the claimed task in one SDK session.

        Each SDK message goes to a transcript file that only ``runner``
        can read.
        """
        task = claim['task']
        server = sdk.create_sdk_mcp_server(
            'imbi', tools=[self._run_with_secret(claim, workspace)]
        )
        options = sdk.ClaudeAgentOptions(
            cli_path=CLI_WRAPPER,
            cwd=str(workspace),
            env={
                'ANTHROPIC_BASE_URL': self.proxy_url,
                'ANTHROPIC_API_KEY': 'placeholder',
                'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
                'HOME': str(workspace / 'home'),
                'CLAUDE_CONFIG_DIR': str(workspace / '.claude'),
                # agent-cli sets TMPDIR from this: glibc secure mode
                # removes TMPDIR.
                'HARNESS_TMPDIR': str(workspace / 'tmp'),
            },
            mcp_servers={'imbi': server},
            allowed_tools=TOOLS,
            # Only the allowed tools, with no prompt and no classifier.
            # P5 adds the tool policy (can_use_tool).
            permission_mode='dontAsk',
            setting_sources=[],
            model=self.settings.model,
            thinking={'type': 'adaptive', 'display': 'summarized'},
            stderr=_cli_stderr,
        )
        transcripts = self.credentials / 'transcripts'
        transcripts.mkdir(mode=0o700, exist_ok=True)
        path = transcripts / f'{task["id"]}.jsonl'
        LOGGER.info('Running task %s', task['short_id'])
        transport = AgentTransport(prompt=_no_prompt(), options=options)
        client = sdk.ClaudeSDKClient(options, transport=transport)
        with path.open('a', encoding='utf-8') as transcript:
            async with client:
                await client.query(str(task['description']))
                async for message in client.receive_response():
                    transcript.write(
                        json.dumps(
                            {
                                'type': type(message).__name__,
                                **dataclasses.asdict(message),
                            },
                            default=str,
                        )
                        + '\n'
                    )
                    transcript.flush()
        LOGGER.info('Task %s ended', task['short_id'])


async def _no_prompt() -> abc.AsyncIterator[dict[str, typing.Any]]:
    return
    yield {}  # pragma: no cover - makes this an async generator


def main() -> None:
    """Start as uid 0, read the root-only secrets, drop, and serve."""
    settings = Settings.from_environment()
    pool_credential = (
        privilege.read_root_file(f'{POOL_CREDENTIAL}/client_id'),
        privilege.read_root_file(f'{POOL_CREDENTIAL}/client_secret'),
    )
    model_key = privilege.read_root_file(MODEL_KEY)
    credentials = privilege.make_private_dir(CREDENTIALS, privilege.RUNNER)
    privilege.drop(privilege.RUNNER)
    # Read from the runner's own environment, which the CLI inherits.
    os.environ['CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK'] = '1'
    proxy_url = proxy.start(settings.model_url, model_key)
    del model_key
    runner = Runner(settings, pool_credential, credentials, proxy_url)

    async def run() -> None:
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, _fence, 'stop signal')
        await runner.serve()

    asyncio.run(run())
