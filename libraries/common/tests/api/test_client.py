import unittest
import unittest.mock

import httpx

from imbi.common.api import client

_BASE_URL = 'http://imbi-api:8000'
_TOKEN = 'test-token'


def _make_client(**overrides: object) -> client.Imbi:
    kwargs: dict[str, object] = {'base_url': _BASE_URL, 'token': _TOKEN}
    kwargs.update(overrides)
    return client.Imbi(**kwargs)  # type: ignore[arg-type]


class ConstructionTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_headers(self) -> None:
        async with _make_client() as imbi:
            self.assertEqual(f'Bearer {_TOKEN}', imbi.headers['authorization'])
            self.assertTrue(
                imbi.headers['user-agent'].startswith('imbi-common/')
            )
            self.assertEqual(str(imbi.base_url), _BASE_URL)

    async def test_user_agent_override(self) -> None:
        async with _make_client(user_agent='imbi-gateway/9.9.9') as imbi:
            self.assertEqual('imbi-gateway/9.9.9', imbi.headers['user-agent'])

    async def test_timeout_override(self) -> None:
        async with _make_client(timeout=2.5) as imbi:
            self.assertEqual(2.5, imbi.timeout.read)


class PatchProjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_url_is_constructed_from_org_and_project(self) -> None:
        with unittest.mock.patch.object(
            client.Imbi,
            'patch',
            new_callable=unittest.mock.AsyncMock,
            return_value=httpx.Response(200),
        ) as mock_patch:
            async with _make_client() as imbi:
                await imbi.patch_project('myorg', 'proj-42', [])

        mock_patch.assert_called_once_with(
            '/organizations/myorg/projects/proj-42', json=[]
        )

    async def test_error_response_logs_warning_with_json(self) -> None:
        with (
            unittest.mock.patch.object(
                client.Imbi,
                'patch',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(422, json={'detail': 'invalid'}),
            ),
            self.assertLogs(client.LOGGER, level='WARNING') as cm,
        ):
            async with _make_client() as imbi:
                response = await imbi.patch_project('o', 'p', [])

        self.assertEqual(422, response.status_code)
        self.assertTrue(any('Failed to patch' in line for line in cm.output))
        self.assertTrue(any("'detail'" in line for line in cm.output))

    async def test_error_response_with_non_json_body_logs_content(
        self,
    ) -> None:
        with (
            unittest.mock.patch.object(
                client.Imbi,
                'patch',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(500, content=b'boom'),
            ),
            self.assertLogs(client.LOGGER, level='WARNING') as cm,
        ):
            async with _make_client() as imbi:
                response = await imbi.patch_project('o', 'p', [])

        self.assertEqual(500, response.status_code)
        self.assertTrue(any('Failed to patch' in line for line in cm.output))
        self.assertTrue(any('boom' in line for line in cm.output))

    async def test_success_response_does_not_log(self) -> None:
        ops = [{'op': 'replace', 'path': '/name', 'value': 'x'}]
        with (
            unittest.mock.patch.object(
                client.Imbi,
                'patch',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ),
            self.assertNoLogs(client.LOGGER, level='WARNING'),
        ):
            async with _make_client() as imbi:
                response = await imbi.patch_project('o', 'p', ops)

        self.assertEqual(200, response.status_code)


class FindUserByIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_email_on_success(self) -> None:
        with unittest.mock.patch.object(
            client.Imbi,
            'get',
            new_callable=unittest.mock.AsyncMock,
            return_value=httpx.Response(
                200, json={'email': 'alice@example.com'}
            ),
        ) as mock_get:
            async with _make_client() as imbi:
                result = await imbi.find_user_by_identity('github', 's-1')

        mock_get.assert_called_once_with(
            '/users/by-identity',
            params={'plugin_slug': 'github', 'subject': 's-1'},
        )
        self.assertEqual('alice@example.com', result)

    async def test_404_returns_none_without_logging(self) -> None:
        with (
            unittest.mock.patch.object(
                client.Imbi,
                'get',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(404),
            ),
            self.assertNoLogs(client.LOGGER, level='WARNING'),
        ):
            async with _make_client() as imbi:
                result = await imbi.find_user_by_identity('github', 's-1')

        self.assertIsNone(result)

    async def test_other_error_logs_and_returns_none(self) -> None:
        with (
            unittest.mock.patch.object(
                client.Imbi,
                'get',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(500, content=b'boom'),
            ),
            self.assertLogs(client.LOGGER, level='WARNING') as cm,
        ):
            async with _make_client() as imbi:
                result = await imbi.find_user_by_identity('github', 's-1')

        self.assertIsNone(result)
        self.assertTrue(
            any('Failed to look up user' in line for line in cm.output)
        )

    async def test_missing_email_returns_none(self) -> None:
        with unittest.mock.patch.object(
            client.Imbi,
            'get',
            new_callable=unittest.mock.AsyncMock,
            return_value=httpx.Response(200, json={'id': 1}),
        ):
            async with _make_client() as imbi:
                result = await imbi.find_user_by_identity('github', 's-1')

        self.assertIsNone(result)

    async def test_null_email_returns_none(self) -> None:
        with unittest.mock.patch.object(
            client.Imbi,
            'get',
            new_callable=unittest.mock.AsyncMock,
            return_value=httpx.Response(200, json={'email': None}),
        ):
            async with _make_client() as imbi:
                result = await imbi.find_user_by_identity('github', 's-1')

        self.assertIsNone(result)

    async def test_transport_error_returns_none(self) -> None:
        with (
            unittest.mock.patch.object(
                client.Imbi,
                'get',
                new_callable=unittest.mock.AsyncMock,
                side_effect=httpx.ConnectError('connection refused'),
            ),
            self.assertLogs(client.LOGGER, level='WARNING') as cm,
        ):
            async with _make_client() as imbi:
                result = await imbi.find_user_by_identity('github', 's-1')

        self.assertIsNone(result)
        self.assertTrue(
            any('Failed to look up user' in line for line in cm.output)
        )

    async def test_malformed_json_returns_none(self) -> None:
        with (
            unittest.mock.patch.object(
                client.Imbi,
                'get',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200, content=b'not json'),
            ),
            self.assertLogs(client.LOGGER, level='WARNING') as cm,
        ):
            async with _make_client() as imbi:
                result = await imbi.find_user_by_identity('github', 's-1')

        self.assertIsNone(result)
        self.assertTrue(any('Failed to decode' in line for line in cm.output))

    async def test_non_dict_json_returns_none(self) -> None:
        with unittest.mock.patch.object(
            client.Imbi,
            'get',
            new_callable=unittest.mock.AsyncMock,
            return_value=httpx.Response(200, json=[1, 2, 3]),
        ):
            async with _make_client() as imbi:
                result = await imbi.find_user_by_identity('github', 's-1')

        self.assertIsNone(result)


class CreateReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_url_is_constructed_from_org_and_project(self) -> None:
        with unittest.mock.patch.object(
            client.Imbi,
            'post',
            new_callable=unittest.mock.AsyncMock,
            return_value=httpx.Response(201),
        ) as mock_post:
            async with _make_client() as imbi:
                await imbi.create_release(
                    'myorg', 'proj-42', {'version': 'v1'}
                )

        mock_post.assert_called_once_with(
            '/organizations/myorg/projects/proj-42/releases/',
            json={'version': 'v1'},
        )

    async def test_409_does_not_log_warning(self) -> None:
        with (
            unittest.mock.patch.object(
                client.Imbi,
                'post',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(409, json={'detail': 'exists'}),
            ),
            self.assertNoLogs(client.LOGGER, level='WARNING'),
        ):
            async with _make_client() as imbi:
                response = await imbi.create_release('o', 'p', {})

        self.assertEqual(409, response.status_code)

    async def test_other_error_logs_warning(self) -> None:
        with (
            unittest.mock.patch.object(
                client.Imbi,
                'post',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(500, content=b'boom'),
            ),
            self.assertLogs(client.LOGGER, level='WARNING') as cm,
        ):
            async with _make_client() as imbi:
                response = await imbi.create_release('o', 'p', {})

        self.assertEqual(500, response.status_code)
        self.assertTrue(
            any('Failed to create release' in line for line in cm.output)
        )


class RecordDeploymentTests(unittest.IsolatedAsyncioTestCase):
    async def test_url_is_constructed(self) -> None:
        with unittest.mock.patch.object(
            client.Imbi,
            'post',
            new_callable=unittest.mock.AsyncMock,
            return_value=httpx.Response(200),
        ) as mock_post:
            async with _make_client() as imbi:
                await imbi.record_deployment(
                    'o', 'p', 'v1.2.3', 'prod', {'status': 'success'}
                )

        mock_post.assert_called_once_with(
            '/organizations/o/projects/p/releases/v1.2.3/environments/prod',
            json={'status': 'success'},
        )

    async def test_404_does_not_log_warning(self) -> None:
        with (
            unittest.mock.patch.object(
                client.Imbi,
                'post',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(404),
            ),
            self.assertNoLogs(client.LOGGER, level='WARNING'),
        ):
            async with _make_client() as imbi:
                response = await imbi.record_deployment(
                    'o', 'p', 'v1', 'prod', {}
                )

        self.assertEqual(404, response.status_code)

    async def test_other_error_logs_warning(self) -> None:
        with (
            unittest.mock.patch.object(
                client.Imbi,
                'post',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(500, content=b'boom'),
            ),
            self.assertLogs(client.LOGGER, level='WARNING') as cm,
        ):
            async with _make_client() as imbi:
                response = await imbi.record_deployment(
                    'o', 'p', 'v1', 'prod', {}
                )

        self.assertEqual(500, response.status_code)
        self.assertTrue(
            any('Failed to record deployment' in line for line in cm.output)
        )
