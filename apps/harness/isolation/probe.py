"""Probe what an ``agent`` process can reach. Prints one JSON object.

``probe.py agent``: from the model's ``Bash`` tool in the ``runner``
container. ``probe.py child``: from a ``run_with_secret`` command in the
``executor`` container.

A read that works reports only its length, never the content.
"""

import errno
import json
import os
import pathlib
import socket
import subprocess
import sys
import typing

SOCKET = '/run/executor/executor.sock'


def attempt(action: typing.Callable[[], object]) -> str:
    try:
        return f'allowed:{action()}'
    except OSError as err:
        return f'denied:{errno.errorcode.get(err.errno or 0, err.errno)}'


def read(path: str) -> typing.Callable[[], object]:
    return lambda: len(pathlib.Path(path).read_bytes())


def open_mem(pid: int | None) -> typing.Callable[[], object]:
    def action() -> object:
        with pathlib.Path(f'/proc/{pid}/mem').open('rb'):
            return 'opened'

    return action


def connect() -> object:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(SOCKET)
    return 'connected'


def processes() -> dict[int, list[str]]:
    found = {}
    for entry in pathlib.Path('/proc').iterdir():
        if entry.name.isdigit():
            try:
                raw = (entry / 'cmdline').read_bytes()
            except OSError:
                continue
            found[int(entry.name)] = raw.decode(errors='replace').split('\0')[
                :-1
            ]
    return found


def harness_pid(process: str) -> int | None:
    """The pid of ``imbi-harness <process>``, not of ``tini``."""
    for pid, argv in processes().items():
        if (
            len(argv) >= 2
            and argv[-1] == process
            and argv[-2].endswith('imbi-harness')
            and 'tini' not in argv[0]
        ):
            return pid
    return None


def identity() -> dict[str, object]:
    status = pathlib.Path('/proc/self/status').read_text()
    fields = {}
    for line in status.splitlines():
        name, _, value = line.partition(':')
        if name in {'CapPrm', 'CapEff', 'CapInh', 'CapAmb', 'NoNewPrivs'}:
            fields[name] = value.strip()
    return {
        'uid': os.getresuid(),
        'gid': os.getresgid(),
        'groups': os.getgroups(),
        **fields,
    }


def setuid_files() -> list[str]:
    result = subprocess.run(
        ['find', '/', '-xdev', '-perm', '/6000', '-type', 'f'],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.split()


def regain() -> object:
    os.setuid(0)
    return 'uid 0'


def agent() -> dict[str, object]:
    runner = harness_pid('runner')
    return {
        'identity': identity(),
        'runner_pid': runner,
        'runner_credential': attempt(read('/run/creds/runner/runner.token')),
        'credential_dir': attempt(lambda: len(os.listdir('/run/creds'))),
        'runner_environ': attempt(read(f'/proc/{runner}/environ')),
        'runner_mem': attempt(open_mem(runner)),
        'pool_credential': attempt(
            read('/var/run/secrets/imbi/pool/client_secret')
        ),
        'model_key': attempt(read('/var/run/secrets/imbi/model/key')),
        'service_account_token': attempt(
            read('/var/run/secrets/kubernetes.io/serviceaccount/token')
        ),
        'executor_socket': attempt(connect),
        'executor_processes': [
            argv
            for argv in processes().values()
            if any('executor' in arg for arg in argv)
        ],
        'cli_key_is_placeholder': os.environ.get('ANTHROPIC_API_KEY')
        == 'placeholder',
        'setuid_0': attempt(regain),
        'setuid_files': setuid_files(),
    }


def child() -> dict[str, object]:
    executor = harness_pid('executor')
    return {
        'identity': identity(),
        'executor_pid': executor,
        'executor_credential': attempt(
            read('/run/creds/executor/executor.token')
        ),
        'credential_dir': attempt(lambda: len(os.listdir('/run/creds'))),
        'executor_environ': attempt(read(f'/proc/{executor}/environ')),
        'executor_mem': attempt(open_mem(executor)),
        'executor_socket': attempt(connect),
        'environment': sorted(os.environ),
        'secret_length': len(os.environ.get('GH_TOKEN', '')),
        'setuid_0': attempt(regain),
    }


def agent_processes() -> list[list[str]]:
    """The other ``agent`` processes: not this one and not its shell."""
    skip = {os.getpid(), os.getppid()}
    found = []
    for pid, argv in processes().items():
        if pid in skip:
            continue
        try:
            status = pathlib.Path(f'/proc/{pid}/status').read_text()
        except OSError:
            continue
        uids = next(
            line.split()[1:]
            for line in status.splitlines()
            if line.startswith('Uid:')
        )
        if str(os.getuid()) in uids:
            found.append(argv)
    return found


if __name__ == '__main__':
    probes = {'agent': agent, 'child': child, 'processes': agent_processes}
    print(json.dumps(probes[sys.argv[1]]()))
