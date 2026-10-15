"""The imbi-api routes that the runner and the executor call."""

import http
import typing

import httpx

type Body = dict[str, typing.Any]


def items(body: Body, key: str) -> list[typing.Any]:
    """The list at ``key``; empty when it is missing or ``None``."""
    return typing.cast('list[typing.Any]', body.get(key) or [])


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

    async def post(
        self, path: str, token: str, **kwargs: typing.Any
    ) -> httpx.Response:
        return await self.request('POST', path, token, **kwargs)

    async def request(
        self, method: str, path: str, token: str, **kwargs: typing.Any
    ) -> httpx.Response:
        response = await self.http.request(
            method,
            path,
            headers={'Authorization': f'Bearer {token}'},
            **kwargs,
        )
        if response.is_error:
            code = str(response.status_code)
            try:
                decoded = response.json()
            except ValueError:
                decoded = None
            detail = (
                typing.cast('Body', decoded).get('detail')
                if isinstance(decoded, dict)
                else None
            )
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
        response = await self.post(
            '/harness/runners',
            token,
            json={
                'pool': pool,
                'instance': instance,
                'image_version': image_version,
            },
        )
        return _body(response)

    async def heartbeat(
        self, runner_id: str, token: str, tasks: list[str] | None = None
    ) -> dict[str, str]:
        """Renew the lease, and the agent API tokens of ``tasks``.

        Only the status renews the lease. Return the new API tokens by
        short id; a body that is not what imbi-api sends gives none.
        """
        response = await self.post(
            f'/harness/runners/{runner_id}/heartbeat',
            token,
            json={'tasks': tasks} if tasks else None,
        )
        try:
            renewed = typing.cast(
                'dict[str, Body]', response.json().get('api_tokens') or {}
            )
            return {
                str(short_id): str(value['token'])
                for short_id, value in renewed.items()
            }
        except (ValueError, AttributeError, KeyError, TypeError):
            return {}

    async def claim(
        self, runner_id: str, token: str, wait: int
    ) -> Body | None:
        response = await self.post(
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

    async def chain_claim(self, runner_id: str, token: str) -> Body | None:
        """Claim the oldest queued child task of the runner's chain."""
        response = await self.post(
            f'/harness/runners/{runner_id}/chain/claim', token
        )
        return (
            None
            if response.status_code == http.HTTPStatus.NO_CONTENT
            else _body(response)
        )

    async def finish(self, runner_id: str, token: str) -> None:
        await self.post(f'/harness/runners/{runner_id}/finish', token)

    async def create_resolution(self, agent_token: str, body: Body) -> Body:
        response = await self.post(
            '/harness/secret-resolutions', agent_token, json=body
        )
        return _body(response)

    async def materialize(self, executor_token: str, body: Body) -> Body:
        response = await self.post(
            '/harness/executor/secret-materializations',
            executor_token,
            json=body,
        )
        return _body(response)

    async def release(self, executor_token: str, resolution_id: str) -> Body:
        response = await self.post(
            f'/harness/executor/secret-resolutions/{resolution_id}/release',
            executor_token,
        )
        return _body(response)


class TaskApi:
    """The ADR 0020 harness routes of one task, with its agent token."""

    def __init__(
        self, client: Api, token: str, organization: str, short_id: str
    ) -> None:
        self.client = client
        self.token = token
        self.path = f'/organizations/{organization}/agent-tasks/{short_id}'
        self.short_id = short_id

    async def _call(self, path: str, body: Body | None = None) -> Body:
        response = await self.client.post(
            self.path + path, self.token, json=body
        )
        return _body(response)

    async def open_session(self, key: str, instance: str) -> Body:
        return await self._call(
            '/sessions', {'session_key': key, 'harness_instance': instance}
        )

    async def heartbeat(self, session_id: str) -> Body:
        return await self._call(f'/sessions/{session_id}/heartbeat')

    async def close_session(self, session_id: str, reason: str) -> Body:
        return await self._call(
            f'/sessions/{session_id}/close', {'reason': reason}
        )

    async def append_events(self, session_id: str, events: list[Body]) -> Body:
        return await self._call(
            '/events', {'session_id': session_id, 'events': events}
        )

    async def report_usage(self, body: Body) -> Body:
        return await self._call('/usage', body)

    async def set_outcome(self, outcome: str, reason: str | None) -> Body:
        return await self._call(
            '/outcome', {'outcome': outcome, 'reason': reason}
        )

    async def create_resolution(self, body: Body) -> Body:
        return await self.client.create_resolution(
            self.token, {'short_id': self.short_id, **body}
        )

    async def open_request(self, body: Body) -> Body:
        return await self._call('/requests', body)

    async def events(self, after_seq: int) -> list[Body]:
        """The events after ``after_seq`` (the harness route)."""
        response = await self.client.request(
            'GET',
            f'/harness/tasks/{self.short_id}/events',
            self.token,
            params={'after_seq': after_seq, 'limit': 1000},
        )
        return typing.cast('list[Body]', response.json())

    async def create_child(self, body: Body) -> Body:
        response = await self.client.post(
            f'/harness/tasks/{self.short_id}/children', self.token, json=body
        )
        return _body(response)

    async def check_tool(self, tool_key: str) -> Body:
        """Count a call against the tool's rate limit, across runners."""
        response = await self.client.post(
            f'/harness/tasks/{self.short_id}/tool-calls/check',
            self.token,
            json={'tool_key': tool_key},
        )
        return _body(response)
