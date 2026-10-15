"""The spawn window of :mod:`imbi.harness.privilege`.

The real id changes need uid 0 and Linux; ``isolation/`` runs them in a
pod. Here the ``os`` calls are recorded.
"""

import typing
import unittest
from unittest import mock

from imbi.harness import privilege


class SpawnAsRootTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[str, tuple[int, ...]]] = []

        def record(name: str) -> typing.Callable[..., None]:
            def call(*ids: int) -> None:
                self.calls.append((name, ids))

            return call

        patcher = mock.patch.object(privilege.sys, 'platform', 'linux')
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, value in (
            ('getresuid', (10001, 10001, 0)),
            ('getresgid', (10001, 10001, 0)),
        ):
            patcher = mock.patch.object(
                privilege.os, name, return_value=value, create=True
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ('setresuid', 'setresgid'):
            patcher = mock.patch.object(
                privilege.os, name, record(name), create=True
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def expected(self, inside: list[str]) -> list[tuple[str, tuple[int, ...]]]:
        return [
            ('setresuid', (0, 0, 0)),
            ('setresgid', (0, 0, 0)),
            *[('inside', ()) for _ in inside],
            ('setresgid', (10001, 10001, 0)),
            ('setresuid', (10001, 10001, 0)),
        ]

    def test_real_root_for_the_spawn_then_restore(self) -> None:
        with privilege.spawn_as_root():
            self.calls.append(('inside', ()))
        self.assertEqual(self.calls, self.expected(['spawn']))

    def test_restore_when_the_spawn_fails(self) -> None:
        with (
            self.assertRaises(OSError),
            privilege.spawn_as_root(),
        ):
            self.calls.append(('inside', ()))
            raise OSError('exec failed')
        self.assertEqual(self.calls, self.expected(['spawn']))
