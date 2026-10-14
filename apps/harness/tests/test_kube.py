import contextlib
import os
import ssl
import unittest
from unittest import mock

import httpx
import respx

from imbi.harness import kube, privilege

POD = f'{kube.API}/api/v1/namespaces/runners/pods/runner-abc'


class DeleteOwnPodTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        for patcher in (
            mock.patch.dict(
                os.environ,
                {'POD_NAME': 'runner-abc', 'POD_NAMESPACE': 'runners'},
            ),
            mock.patch.object(
                privilege, 'effective', return_value=contextlib.nullcontext()
            ),
            mock.patch.object(
                privilege, 'read_root_file', return_value='sa-token'
            ),
            mock.patch.object(
                ssl,
                'create_default_context',
                return_value=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.mock = respx.mock(assert_all_called=False)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    async def test_deletes_with_the_token_read_as_root(self) -> None:
        route = self.mock.delete(POD).respond(200, json={})
        self.assertTrue(await kube.delete_own_pod())
        self.assertEqual(
            route.calls.last.request.headers['Authorization'],
            'Bearer sa-token',
        )
        privilege.read_root_file.assert_called_once_with(kube.TOKEN)  # type: ignore[attr-defined]
        privilege.effective.assert_called_once_with()  # type: ignore[attr-defined]

    async def test_refused(self) -> None:
        self.mock.delete(POD).respond(403)
        with self.assertLogs('imbi.harness.kube', 'ERROR'):
            self.assertFalse(await kube.delete_own_pod())

    async def test_unreachable(self) -> None:
        self.mock.delete(POD).mock(side_effect=httpx.ConnectError('down'))
        with self.assertLogs('imbi.harness.kube', 'ERROR'):
            self.assertFalse(await kube.delete_own_pod())

    async def test_no_token(self) -> None:
        privilege.read_root_file.side_effect = PermissionError()  # type: ignore[attr-defined]
        with self.assertLogs('imbi.harness.kube', 'ERROR'):
            self.assertFalse(await kube.delete_own_pod())

    async def test_not_in_a_pool(self) -> None:
        with mock.patch.dict(os.environ, {'POD_NAME': ''}):
            self.assertFalse(await kube.delete_own_pod())
