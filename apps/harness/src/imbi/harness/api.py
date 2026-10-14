"""The imbi-api routes that the runner and the executor call."""

import http
import typing

import httpx

type Body = dict[str, typing.Any]


def _body(response: httpx.Response) -> Body:
    return typing.cast('Body', response.json())


class Refused(Exception):
    """imbi-api refused a request. ``code`` is its error code."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(f'{status} {code}')
        self.status = status
        self.code = code


class Api:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.http = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def _post(
        self, path: str, token: str, **kwargs: typing.Any
    ) -> httpx.Response:
        response = await self.http.post(
            path, headers={'Authorization': f'Bearer {token}'}, **kwargs
        )
        if response.is_error:
            code = str(response.status_code)
            try:
                detail = response.json().get('detail')
            except ValueError:
                detail = None
            if isinstance(detail, dict):
                code = str(typing.cast('Body', detail).get('error', code))
            raise Refused(response.status_code, code)
        return response

    async def pool_token(self, client_id: str, client_secret: str) -> str:
        """Exchange the pool credential for an access token."""
        response = await self.http.post(
            '/auth/token',
            data={
                'grant_type': 'client_credentials',
                'client_id': client_id,
                'client_secret': client_secret,
            },
        )
        if response.status_code != http.HTTPStatus.OK:
            raise Refused(response.status_code, 'invalid_pool_credential')
        return str(response.json()['access_token'])

    async def register(
        self, token: str, pool: str, instance: str, image_version: str
    ) -> Body:
        response = await self._post(
            '/harness/runners',
            token,
            json={
                'pool': pool,
                'instance': instance,
                'image_version': image_version,
            },
        )
        return _body(response)

    async def heartbeat(self, runner_id: str, token: str) -> Body:
        response = await self._post(
            f'/harness/runners/{runner_id}/heartbeat', token
        )
        return _body(response)

    async def claim(
        self, runner_id: str, token: str, wait: int
    ) -> Body | None:
        response = await self._post(
            f'/harness/runners/{runner_id}/claim',
            token,
            params={'wait': wait},
            timeout=wait + 10,
        )
        return (
            None
            if response.status_code == http.HTTPStatus.NO_CONTENT
            else _body(response)
        )

    async def finish(self, runner_id: str, token: str) -> None:
        await self._post(f'/harness/runners/{runner_id}/finish', token)

    async def create_resolution(self, agent_token: str, body: Body) -> Body:
        response = await self._post(
            '/harness/secret-resolutions', agent_token, json=body
        )
        return _body(response)

    async def materialize(self, executor_token: str, body: Body) -> Body:
        response = await self._post(
            '/harness/executor/secret-materializations',
            executor_token,
            json=body,
        )
        return _body(response)

    async def release(self, executor_token: str, resolution_id: str) -> Body:
        response = await self._post(
            f'/harness/executor/secret-resolutions/{resolution_id}/release',
            executor_token,
        )
        return _body(response)
