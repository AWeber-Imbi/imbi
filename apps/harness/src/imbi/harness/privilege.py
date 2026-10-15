"""User switching for the runner and the executor (plan section 2).

Both processes start as uid 0 with only ``CAP_SETUID`` and
``CAP_SETGID``, and with ``no_new_privs`` set. :func:`drop` makes the
real and effective ids the service user and keeps uid 0 as the saved
uid. The saved uid is needed only to start and signal ``agent``
processes and to make ``agent`` files (:func:`effective`).

An effective id change applies to all threads of the process. Keep
each :func:`effective` block short.
"""

import contextlib
import grp
import os
import pathlib
import pwd
import signal
import sys
import typing

if typing.TYPE_CHECKING:
    from collections import abc

RUNNER = 'runner'
EXECUTOR = 'executor'
AGENT = 'agent'
IPC_GROUP = 'harness-ipc'


def uid(user: str) -> int:
    return pwd.getpwnam(user).pw_uid


def gid(user: str) -> int:
    return pwd.getpwnam(user).pw_gid


def ipc_gid() -> int:
    return grp.getgrnam(IPC_GROUP).gr_gid


@contextlib.contextmanager
def effective(user: str | None = None) -> abc.Generator[None]:
    """Run the block with the effective ids of ``user``, or uid 0.

    Root has no ``CAP_CHOWN``, ``CAP_DAC_OVERRIDE``, or ``CAP_KILL``.
    So it makes a file for a user, and signals a process of a user,
    with the effective ids of that user.
    """
    euid, egid = os.geteuid(), os.getegid()
    os.seteuid(0)
    try:
        if user is not None:
            os.setegid(gid(user))
            os.seteuid(uid(user))
        yield
    finally:
        os.seteuid(0)
        os.setegid(egid)
        os.seteuid(euid)


@contextlib.contextmanager
def spawn_as_root() -> abc.Generator[None]:
    """Start a process with the real, effective and saved ids 0.

    :func:`effective` is not sufficient to start a program that must
    have uid 0. Some kernels (seen on 6.12, SELinux, ``no_new_privs``
    set) start the new program with the effective uid set to the real
    uid, so it runs as the service user, and ``setpriv`` cannot become
    ``agent``. The ids apply to all threads of the process: use this
    block for the process start only, and restore the ids at once.
    """
    if sys.platform != 'linux':  # pragma: no cover
        raise OSError('setresuid needs Linux')
    ruid, euid, suid = os.getresuid()
    rgid, egid, sgid = os.getresgid()
    # The saved uid 0 allows this; uid 0 gives back CAP_SETGID.
    os.setresuid(0, 0, 0)
    try:
        os.setresgid(0, 0, 0)
        try:
            yield
        finally:
            os.setresgid(rgid, egid, sgid)
    finally:
        os.setresuid(ruid, euid, suid)


def make_private_dir(parent: str, user: str) -> pathlib.Path:
    """Make ``parent/user`` with mode ``0700``, owned by ``user``.

    Call as uid 0, before :func:`drop`. ``parent`` is an ``emptyDir``,
    which Kubernetes makes as ``root`` with mode ``0777``. After this,
    ``parent`` has mode ``0711``: no other user can list it, or add,
    rename, or remove an entry in it.
    """
    path = pathlib.Path(parent) / user
    with effective(user):
        path.mkdir(mode=0o700, exist_ok=True)
    if path.stat().st_uid != uid(user):
        raise PermissionError(f'{path} is not owned by {user}')
    pathlib.Path(parent).chmod(0o711)
    return path


def read_root_file(path: str) -> str:
    """Read a ``root`` mode ``0400`` file. Call as uid 0 only."""
    return pathlib.Path(path).read_text(encoding='utf-8').strip()


def drop(user: str) -> None:
    """Become ``user``, in the ``harness-ipc`` group, with saved uid 0.

    A drop of only the effective uid is not sufficient: each program
    that the process starts would run as uid 0.
    """
    if sys.platform != 'linux':  # pragma: no cover
        raise OSError('setresuid needs Linux')
    os.setgroups([ipc_gid()])
    os.setresgid(gid(user), gid(user), 0)
    os.setresuid(uid(user), uid(user), 0)


def kill_agent(target: int = -1) -> None:
    """Send ``SIGKILL`` to ``agent`` processes.

    ``target`` is ``-1`` for every ``agent`` process of this container
    (``kill(-1)`` skips the caller and PID 1), or ``-pgid`` for one
    process group.
    """
    with effective(AGENT), contextlib.suppress(ProcessLookupError):
        os.kill(target, signal.SIGKILL)
