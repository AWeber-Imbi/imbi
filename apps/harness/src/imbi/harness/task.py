"""One task of a chain (plan sections 6.2 to 6.6).

:class:`TaskRun` opens an ADR 0020 session, builds the chain workspace
(root task only), gets the model key, starts the task's model proxy,
writes the task's ``CLAUDE_CONFIG_DIR``, runs the SDK, sends the events,
and sets the outcome.

Control and budget: a session heartbeat every
:data:`SESSION_HEARTBEAT` seconds, and each usage report, return the
task state. When the control is ``cancel`` or the task is closed (for
example ``exceeded_ceiling`` after a usage report), the runner
interrupts the SDK, which stops at the end of the current step. The
proxy refuses model calls when the remaining budget is zero.
"""

import asyncio
import dataclasses
import decimal
import http
import json
import logging
import pathlib
import re
import shutil
import typing
import urllib.parse
import uuid

import claude_agent_sdk as sdk
import httpx
from claude_agent_sdk._internal.transport import subprocess_cli

from imbi.harness import api, events, ipc, privilege, proxy, redact

if typing.TYPE_CHECKING:
    from collections import abc

LOGGER = logging.getLogger(__name__)

#: ``#!/bin/sh -p`` + ``setpriv --reuid=agent ...`` + the bundled CLI.
CLI_WRAPPER = '/usr/local/bin/agent-cli'
SESSION_HEARTBEAT = 10
#: The largest CLI message line that the SDK reads.
SDK_BUFFER = 64 * 1024 * 1024
RESOLUTION_TTL = 300
ANTHROPIC_API = 'https://api.anthropic.com'
#: The built-in tools when the organization allows all of them. The
#: runner uses ``dontAsk``, so a tool must be listed to run: the CLI's
#: default mode sends ``Bash`` to a classifier (P5a).
BUILTIN_TOOLS = (
    'Bash',
    'Edit',
    'Glob',
    'Grep',
    'MultiEdit',
    'NotebookEdit',
    'Read',
    'TodoWrite',
    'WebFetch',
    'WebSearch',
    'Write',
)
IMBI_TOOLS = ('mcp__imbi__run_with_secret',)
#: Every setup secret goes to the executor, which hands it over on a
#: descriptor (git) or to the runner (the model key).
SETUP_DELIVERY = {'mode': 'file_descriptor', 'target': '3'}
#: The purposes of the runner's own setup secrets (H22).
SETUP_PURPOSES = frozenset(
    {'marketplace_fetch', 'model_inference', 'workspace_checkout'}
)
_REASON = re.compile(r'^[a-z0-9][a-z0-9_.-]{0,99}$')
_RULES = """\
# Imbi harness

- The workspace is {cwd}. Other tasks of this chain can use it too.
- Use the `run_with_secret` tool of the `imbi` server for a command that
  needs a secret, for example `gh` with `GH_TOKEN`. Its output never
  contains the secret. No other tool gets a secret.
- The secret references that you may request: {secrets}.
"""

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


class Failed(Exception):
    """The task cannot run. ``reason`` is the outcome reason slug."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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


@dataclasses.dataclass(frozen=True)
class Layout:
    """``/work/<chain>``: the chain workspace (plan section 6.1).

    ``repos`` and ``plugins`` are for the whole chain; ``tasks/<id>``
    holds ``HOME``, ``TMPDIR``, and ``CLAUDE_CONFIG_DIR`` of each task.
    """

    root: pathlib.Path

    @property
    def repos(self) -> pathlib.Path:
        return self.root / 'repos'

    @property
    def plugins(self) -> pathlib.Path:
        return self.root / 'plugins'

    def task(self, task_id: str) -> pathlib.Path:
        return self.root / 'tasks' / task_id

    def make(self) -> None:
        """Make the chain directories as ``agent``.

        Mode ``0711`` on the root and on ``repos``: the CLI process
        changes to its directory (a repository) before ``setpriv`` makes
        it ``agent``, and root has no ``CAP_DAC_OVERRIDE``. Others can
        pass through, and list nothing.
        """
        with privilege.effective(privilege.AGENT):
            self.root.mkdir(mode=0o711, exist_ok=True)
            self.repos.mkdir(mode=0o711, exist_ok=True)
            for path in (self.plugins, self.root / 'tasks'):
                path.mkdir(mode=0o700, exist_ok=True)

    def make_task(self, task_id: str) -> pathlib.Path:
        path = self.task(task_id)
        with privilege.effective(privilege.AGENT):
            path.mkdir(mode=0o700, exist_ok=True)
            for name in ('home', 'tmp', '.claude'):
                (path / name).mkdir(mode=0o700, exist_ok=True)
        return path


def outcome(result: sdk.ResultMessage | None) -> tuple[str, str | None]:
    """The ADR 0020 outcome of an SDK result."""
    if result is None:
        return 'failed_external', 'no_result'
    if not result.is_error and result.subtype == 'success':
        return 'done_acted', None
    if result.subtype == 'error_max_turns':
        return 'partial_capped', 'max_turns'
    if result.api_error_status is not None:
        return 'failed_external', 'model_api_error'
    reason = result.subtype if _REASON.match(result.subtype) else 'sdk_error'
    return 'failed_external', reason


def _cli_stderr(line: str) -> None:
    # The CLI holds no credential, so its stderr holds none.
    LOGGER.info('cli: %s', line.rstrip())


def _tool_error(text: str) -> Body:
    return {'content': [{'type': 'text', 'text': text}], 'is_error': True}


def _decimal(value: typing.Any) -> decimal.Decimal | None:
    return None if value is None else decimal.Decimal(str(value))


def _relative(value: typing.Any) -> pathlib.PurePosixPath:
    """A plugin path in a marketplace: relative, with no ``..``."""
    path = pathlib.PurePosixPath(str(value or '.'))
    if path.is_absolute() or '..' in path.parts:
        raise Failed('plugin_path_invalid')
    return path


async def _no_prompt() -> abc.AsyncIterator[dict[str, typing.Any]]:
    return
    yield {}  # pragma: no cover - makes this an async generator


class TaskRun:
    """Run one task of the runner's chain."""

    def __init__(  # noqa: PLR0913
        self,
        client: api.Api,
        claim: Body,
        layout: Layout,
        redactor: redact.Redactor,
        *,
        instance: str,
        transcripts: pathlib.Path,
        model: str | None = None,
        build: bool = True,
    ) -> None:
        self.claim = claim
        self.task: Body = claim['task']
        self.bundle: Body = claim.get('bundle') or {}
        self.config: Body = self.bundle.get('config') or {}
        self.api = api.TaskApi(
            client,
            str(claim['agent_token']),
            str(claim['organization_slug']),
            str(self.task['short_id']),
        )
        self.layout = layout
        self.redactor = redactor
        self.recorder = events.Recorder(redactor)
        self.instance = instance
        self.transcripts = transcripts
        self.model = model
        self.build = build
        self.home = layout.task(str(self.task['id']))
        self.cwd = layout.repos
        self.plugins: list[pathlib.Path] = []
        self.session_id = ''
        self.control = 'run'
        self.closed = False
        self.remaining: decimal.Decimal | None = None
        self.failure: str | None = None
        self.client: sdk.ClaudeSDKClient | None = None
        self.stopping: asyncio.Task[None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    @property
    def context(self) -> Body:
        return {
            'task_id': self.task['id'],
            'agent_id': self.task['agent_id'],
            'project_id': self.task.get('project_id'),
        }

    # --- Lifecycle ----------------------------------------------------

    async def run(self) -> None:
        """Run the task to its outcome. Never raises for a task error."""
        self.loop = asyncio.get_running_loop()
        try:
            opened = await self.api.open_session(
                f'{self.claim["attempt"]}:{self.task["id"]}', self.instance
            )
        except (api.Refused, httpx.HTTPError) as err:
            LOGGER.warning('Session of %s refused: %s', self.api.short_id, err)
            return
        self.session_id = str(opened['session']['id'])
        self._state(opened['task'])
        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            result = await self._work()
            done = outcome(result)
        except Failed as err:
            done = ('failed_external', err.reason)
        except Exception:
            LOGGER.exception('Task %s failed', self.api.short_id)
            done = ('failed_external', 'harness_error')
        finally:
            heartbeat.cancel()
        if self.failure is not None:
            done = ('failed_external', self.failure)
        await self.flush()
        await self._end(*done)

    async def _work(self) -> sdk.ResultMessage | None:
        if self.build:
            await self.build_workspace()
        self.cwd = self._cwd()
        self.layout.make_task(str(self.task['id']))
        key = await self.model_key()
        upstream: Body = self.config.get('model_upstream') or {}
        url = proxy.start(
            str(upstream.get('base_url') or ANTHROPIC_API),
            key,
            litellm=upstream.get('kind') == 'litellm',
            meter=self.meter,
            allowed=self.allowed,
        )
        self.write_config()
        return await self.run_sdk(url)

    async def _end(self, kind: str, reason: str | None) -> None:
        """Set the outcome. Imbi refuses it for a task that it closed
        (``exceeded_ceiling``, a timeout).

        With control ``cancel``, closing the session closes the task as
        ``cancelled_by_human``.
        """
        try:
            if self.control == 'cancel':
                await self.api.close_session(self.session_id, 'cancelled')
            else:
                await self.api.set_outcome(kind, reason)
        except api.Refused as err:
            if err.code != 'task_closed':
                LOGGER.warning('End of %s refused: %s', self.api.short_id, err)
        except httpx.HTTPError as err:
            LOGGER.warning('End of %s failed: %s', self.api.short_id, err)
        LOGGER.info('Task %s ended: %s %s', self.api.short_id, kind, reason)

    def _state(self, state: Body) -> None:
        """Apply a task state from a heartbeat or a usage report."""
        self.control = str(state.get('control') or self.control)
        self.remaining = _decimal(state.get('budget_remaining'))
        if state.get('status') == 'closed':
            self.closed = True
        if self.control == 'cancel' or self.closed:
            self.stop()

    def stop(self) -> None:
        """Interrupt the SDK once. Never awaits: a caller can be in the
        middle of a model call that the interrupt waits on."""
        if self.stopping is None and self.loop is not None:
            self.stopping = self.loop.create_task(self._interrupt())

    async def _interrupt(self) -> None:
        if self.client is not None:
            LOGGER.info('Stopping task %s', self.api.short_id)
            try:
                await self.client.interrupt()
            except (sdk.ClaudeSDKError, RuntimeError) as err:
                LOGGER.warning('Interrupt failed: %s', err)

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(SESSION_HEARTBEAT)
            try:
                self._state(await self.api.heartbeat(self.session_id))
            except api.Refused as err:
                if err.code in {'task_closed', 'session_closed'}:
                    self._state({'status': 'closed'})
                LOGGER.warning('Session heartbeat refused: %s', err)
            except httpx.HTTPError as err:
                LOGGER.warning('Session heartbeat failed: %s', err)

    # --- Model proxy --------------------------------------------------

    def allowed(self) -> bool:
        """A new model call is allowed (proxy thread)."""
        return not self.closed and (
            self.remaining is None or self.remaining > 0
        )

    def meter(self, model: str, usage: Body) -> None:
        """Report one model call (proxy thread). Wait for the reply, so
        the next call sees the new budget."""
        assert self.loop is not None  # noqa: S101 - set by run()
        future = asyncio.run_coroutine_threadsafe(
            self.report(model, usage), self.loop
        )
        try:
            future.result(timeout=60)
        except Exception:  # noqa: BLE001 - the proxy thread must go on
            LOGGER.warning('Usage report of %s failed', self.api.short_id)

    async def report(self, model: str, usage: Body) -> None:
        """Send the ADR 0020 usage report. A missing cache field is 0;
        no usage at all is an unmeasured report."""
        measured = bool(usage)

        def count(name: str) -> int | None:
            value = usage.get(name)
            return (
                int(value) if value is not None else (0 if measured else None)
            )

        body = {
            'idempotency_key': str(uuid.uuid4()),
            'model_id': model or 'unknown',
            'tokens_in': usage.get('input_tokens'),
            'tokens_out': usage.get('output_tokens'),
            'cache_read_tokens': count('cache_read_input_tokens'),
            'cache_write_tokens': count('cache_creation_input_tokens'),
            'session_id': self.session_id,
        }
        for attempt in range(3):
            try:
                reply = await self.api.report_usage(body)
            except httpx.HTTPError:
                await asyncio.sleep(attempt + 1)
                continue
            except api.Refused as err:
                if err.code == 'task_closed':
                    self._state({'status': 'closed'})
                    return
                raise
            self._state(reply['task'])
            return
        raise RuntimeError('usage report failed')

    async def model_key(self) -> str:
        """Get the model key through a ``model_inference`` resolution.

        The executor materializes it and gives it to the runner, then
        releases it: the key is static, so the release ends only Imbi
        access (plan section 9.1 rule 7).
        """
        upstream: Body = self.config.get('model_upstream') or {}
        reference = upstream.get('key_ref')
        if not reference:
            raise Failed('model_key_missing')
        secret = await self.setup_secret(str(reference), 'model_inference')
        if secret is None:
            raise Failed('model_key_refused')
        try:
            reply = await ipc.call(
                {'op': 'fetch', 'context': self.context, 'secret': secret}
            )
        except OSError as err:
            raise Failed('executor_unavailable') from err
        if 'material' not in reply:
            raise Failed('model_key_unavailable')
        key = str(reply['material'])
        self.redactor.add(key)
        return key

    async def setup_secret(self, reference: str, purpose: str) -> Body | None:
        """A resolution for the runner's own use (H22), or ``None``
        when Imbi refuses it."""
        try:
            created = await self.api.create_resolution(
                {
                    'reference': reference,
                    'purpose': purpose,
                    'ttl_seconds': RESOLUTION_TTL,
                    'delivery': SETUP_DELIVERY,
                }
            )
        except api.Refused as err:
            LOGGER.warning('Refused %s secret: %s', purpose, err.code)
            return None
        return {
            'handle': created['handle'],
            'resolution_id': created['resolution_id'],
            'purpose': purpose,
            'delivery': created['delivery'],
        }

    # --- Workspace ----------------------------------------------------

    async def build_workspace(self) -> None:
        """Clone each repository of the project and each pinned plugin
        (plan sections 5.2 and 6.2)."""
        binding = self.config.get('github_app_binding')
        repo: Body
        for repo in api.items(self.bundle, 'repositories'):
            name = str(repo['name']).rpartition('/')[2]
            secret = None
            if binding:
                secret = await self.setup_secret(
                    str(binding), 'workspace_checkout'
                )
                if secret is None:
                    raise Failed('workspace_checkout_refused')
            if not await self.clone(
                str(repo['url']), self.layout.repos / name, None, secret
            ):
                raise Failed('workspace_checkout_failed')
        cloned: set[pathlib.Path] = set()
        plugin: Body
        for plugin in api.items(self.config, 'plugins'):
            if not plugin.get('url') or not plugin.get('sha'):
                raise Failed('plugin_not_pinned')
            dest = self.layout.plugins / (
                f'{plugin["marketplace"]}-{str(plugin["sha"])[:12]}'
            )
            if dest not in cloned:
                await self._marketplace(plugin, dest, binding)
                cloned.add(dest)
            self.plugins.append(dest / _relative(plugin.get('path')))

    async def _marketplace(
        self, plugin: Body, dest: pathlib.Path, binding: typing.Any
    ) -> None:
        """Clone a marketplace at its pinned commit.

        With a GitHub App binding: with a ``marketplace_fetch`` token.
        When Imbi refuses the token or the clone fails, fall back to an
        anonymous clone only for a public ``github.com`` marketplace; a
        marketplace on another host (GHE) fails the build. With no
        binding: anonymously.
        """
        url, sha = str(plugin['url']), str(plugin['sha'])
        if binding:
            secret = await self.setup_secret(str(binding), 'marketplace_fetch')
            if secret is not None and await self.clone(url, dest, sha, secret):
                LOGGER.info('Marketplace %s: cloned with a token', url)
                return
            self._remove(dest)
            if urllib.parse.urlsplit(url).hostname != 'github.com':
                raise Failed('marketplace_fetch_failed')
            LOGGER.info('Marketplace %s: no token, trying anonymously', url)
        if not await self.clone(url, dest, sha, None):
            raise Failed('marketplace_fetch_failed')
        LOGGER.info('Marketplace %s: cloned anonymously', url)

    async def clone(
        self,
        url: str,
        dest: pathlib.Path,
        sha: str | None,
        secret: Body | None,
    ) -> bool:
        """Clone in the executor, as ``agent``."""
        request: Body = {
            'op': 'clone',
            'url': url,
            'dest': str(dest),
            'sha': sha,
            'context': self.context,
        }
        if secret is not None:
            request['secret'] = secret
        try:
            reply = await ipc.call(request)
        except OSError as err:
            raise Failed('executor_unavailable') from err
        self.redactor.add(*reply.get('values', []))
        if reply.get('exit_code') != 0:
            LOGGER.warning(
                'Clone of %s failed: %s',
                url,
                reply.get('error')
                or self.redactor.text(reply.get('output', '')),
            )
            return False
        return True

    def _remove(self, path: pathlib.Path) -> None:
        with privilege.effective(privilege.AGENT):
            shutil.rmtree(path, ignore_errors=True)

    def _repo_dirs(self) -> list[pathlib.Path]:
        return [
            self.layout.repos / str(repo['name']).rpartition('/')[2]
            for repo in typing.cast(
                'list[Body]', api.items(self.bundle, 'repositories')
            )
        ]

    def _cwd(self) -> pathlib.Path:
        """The only repository, or the ``repos`` directory."""
        repos = self._repo_dirs()
        return repos[0] if len(repos) == 1 else self.layout.repos

    def tools(self) -> tuple[list[str], list[str]]:
        """The allowed and the denied tools of the merged configuration."""
        denied = sorted(self.config.get('denied_tools') or [])
        base = self.config.get('allowed_tools')
        allowed = [
            tool
            for tool in (BUILTIN_TOOLS if base is None else base)
            if tool not in denied
        ]
        return [*allowed, *IMBI_TOOLS], denied

    def write_config(self) -> None:
        """Write ``settings.json`` and ``CLAUDE.md`` of the task's
        ``CLAUDE_CONFIG_DIR`` (plan section 6.2 step 4)."""
        allowed, denied = self.tools()
        settings: Body = {'permissions': {'allow': allowed, 'deny': denied}}
        if self.config.get('hooks'):
            settings['hooks'] = self.config['hooks']
        sandbox: Body = self.config.get('sandbox') or {}
        if sandbox.get('enabled'):
            settings['sandbox'] = {
                'enabled': True,
                'allowUnsandboxedCommands': bool(
                    sandbox.get('allow_unsandboxed_commands')
                ),
            }
        rules = _RULES.format(
            cwd=self.cwd,
            secrets=', '.join(
                f'`{ref}`' for ref in api.items(self.config, 'secrets')
            )
            or 'none',
        )
        config = self.home / '.claude'
        with privilege.effective(privilege.AGENT):
            # The repositories' own instructions, as imports. They are
            # memory, so the settings above (the organization policy)
            # still win; a repository's .claude/settings.json is never
            # read (setting_sources has no 'project').
            imports = [
                f'@{path}'
                for repo in self._repo_dirs()
                for path in (repo / 'CLAUDE.md', repo / 'AGENTS.md')
                if path.is_file()
            ]
            (config / 'settings.json').write_text(json.dumps(settings))
            (config / 'CLAUDE.md').write_text(
                '\n'.join([rules, *imports]) + '\n'
            )

    # --- SDK ----------------------------------------------------------

    def system_prompt(self) -> str:
        """The organization prefix, then the agent's rendered prompt."""
        prompt: Body = self.bundle.get('prompt') or {}
        parts = [self.config.get('system_prompt_prefix'), prompt.get('system')]
        return '\n\n'.join(str(part) for part in parts if part)

    def options(self, proxy_url: str) -> sdk.ClaudeAgentOptions:
        allowed, denied = self.tools()
        prompt: Body = self.bundle.get('prompt') or {}
        server = sdk.create_sdk_mcp_server(
            'imbi', tools=[self.run_with_secret_tool()]
        )
        return sdk.ClaudeAgentOptions(
            cli_path=CLI_WRAPPER,
            cwd=str(self.cwd),
            env={
                'ANTHROPIC_BASE_URL': proxy_url,
                'ANTHROPIC_API_KEY': 'placeholder',
                'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
                # TodoWrite, not the Task* tools: the todos.updated event
                # holds the whole list (plan section 6.6).
                'CLAUDE_CODE_ENABLE_TASKS': '0',
                'HOME': str(self.home / 'home'),
                'CLAUDE_CONFIG_DIR': str(self.home / '.claude'),
                # agent-cli sets TMPDIR from this: glibc secure mode
                # removes TMPDIR.
                'HARNESS_TMPDIR': str(self.home / 'tmp'),
            },
            system_prompt={
                'type': 'preset',
                'preset': 'claude_code',
                'append': self.system_prompt(),
            },
            mcp_servers={'imbi': server},
            allowed_tools=allowed,
            disallowed_tools=denied,
            # Only the allowed tools, with no prompt and no classifier.
            permission_mode=(
                'plan'
                if self.config.get('permission_mode') == 'plan'
                else 'dontAsk'
            ),
            # Not 'project': a repository's settings could widen the
            # organization's policy.
            setting_sources=['user'],
            plugins=[
                {'type': 'local', 'path': str(path)} for path in self.plugins
            ],
            model=prompt.get('model_id') or self.model,
            thinking={'type': 'adaptive', 'display': 'summarized'},
            # The SDK default (1 MiB) fails the task on one large message.
            max_buffer_size=SDK_BUFFER,
            stderr=_cli_stderr,
        )

    async def run_sdk(self, proxy_url: str) -> sdk.ResultMessage | None:
        """Run the SDK session. Each SDK message goes to a transcript
        file that only ``runner`` can read, and to the recorder."""
        options = self.options(proxy_url)
        self.transcripts.mkdir(mode=0o700, exist_ok=True)
        path = self.transcripts / f'{self.task["id"]}.jsonl'
        LOGGER.info('Running task %s', self.api.short_id)
        transport = AgentTransport(prompt=_no_prompt(), options=options)
        self.client = sdk.ClaudeSDKClient(options, transport=transport)
        result: sdk.ResultMessage | None = None
        with path.open('a', encoding='utf-8') as transcript:
            async with self.client:
                if self.stopping is not None:
                    return None
                await self.client.query(str(self.task['description']))
                async for message in self.client.receive_response():
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
                    self._check_plugins(message)
                    self.recorder.message(message)
                    if isinstance(message, sdk.ResultMessage):
                        result = message
                    if isinstance(
                        message, (sdk.UserMessage, sdk.ResultMessage)
                    ):
                        await self.flush()
        self.client = None
        return result

    def _check_plugins(self, message: typing.Any) -> None:
        """Fail the task when a pinned plugin did not load (plan 5.2)."""
        if not (
            isinstance(message, sdk.SystemMessage)
            and message.subtype == 'init'
            and self.plugins
        ):
            return
        plugins = typing.cast('list[Body]', api.items(message.data, 'plugins'))
        loaded = {str(item.get('path')) for item in plugins}
        missing = [path for path in self.plugins if str(path) not in loaded]
        if missing:
            LOGGER.error('Plugins did not load: %s', missing)
            self.failure = 'plugin_not_loaded'
            self.stop()

    async def flush(self) -> None:
        """Send the recorded events (plan section 6.6).

        - A network error puts the unsent events back for the next
          flush.
        - A batch that imbi-api refuses as too large (413) is sent again
          one event at a time, so only the event that fails is lost.
        - Any other refusal drops the batch.
        """
        queue = events.batches(self.recorder.take())
        while queue:
            batch = queue.pop(0)
            try:
                await self.api.append_events(self.session_id, batch)
            except httpx.HTTPError as err:
                LOGGER.warning(
                    'Events of %s not sent: %s', self.api.short_id, err
                )
                self.recorder.requeue([e for b in [batch, *queue] for e in b])
                return
            except api.Refused as err:
                if err.status == http.HTTPStatus.REQUEST_ENTITY_TOO_LARGE and (
                    len(batch) > 1
                ):
                    queue[:0] = [[event] for event in batch]
                    continue
                LOGGER.warning(
                    'Dropped %d events of %s: %s',
                    len(batch),
                    self.api.short_id,
                    err,
                )

    # --- run_with_secret ----------------------------------------------

    def run_with_secret_tool(self) -> sdk.SdkMcpTool[typing.Any]:
        @sdk.tool(
            'run_with_secret',
            'Run a shell command in the workspace with named secrets in '
            'its environment. The output never contains the secrets.',
            _RUN_WITH_SECRET_SCHEMA,
        )
        async def run_with_secret(args: Body) -> Body:
            return await self.run_with_secret(args)

        return run_with_secret

    async def run_with_secret(self, args: Body) -> Body:
        """The runner asks for the resolutions and sends the handles to
        the executor. Only the filtered output goes back to the model."""
        resolved: list[Body] = []
        upstream: Body = self.config.get('model_upstream') or {}
        try:
            wanted: list[Body] = args.get('secrets') or []
            for secret in wanted:
                # The runner's own secrets never go to a command that the
                # model chose. The executor checks the purpose again.
                if secret['purpose'] in SETUP_PURPOSES or (
                    secret['reference'] == upstream.get('key_ref')
                ):
                    return _tool_error(
                        'The secret request was refused: '
                        'the secret is for the harness only'
                    )
            for secret in wanted:
                created = await self.api.create_resolution(
                    {
                        'reference': secret['reference'],
                        'purpose': secret['purpose'],
                        'ttl_seconds': RESOLUTION_TTL,
                        'delivery': {
                            'mode': 'environment',
                            'target': secret['env'],
                        },
                    }
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
                    'cwd': str(self.cwd),
                    'home': str(self.home / 'home'),
                    'context': self.context,
                    'secrets': resolved,
                }
            )
        except api.Refused as err:
            return _tool_error(f'The secret request was refused: {err.code}')
        except (httpx.HTTPError, OSError):
            return _tool_error('The secret service is not available')
        except (KeyError, TypeError):
            return _tool_error('The input is not valid')
        self.redactor.add(*reply.get('values', []))
        if 'error' in reply:
            return _tool_error(f'The command did not run: {reply["error"]}')
        return {
            'content': [
                {
                    'type': 'text',
                    'text': f'exit code {reply["exit_code"]}\n'
                    f'{reply["output"]}',
                }
            ]
        }
