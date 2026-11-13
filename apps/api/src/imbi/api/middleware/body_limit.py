"""Refuse request bodies larger than a limit, with 413.

FastAPI reads and parses the full body before a handler runs, so
without this limit any route can buffer a body of any size in memory.
"""

import fastapi
from fastapi import responses
from starlette import types


def _too_large(limit: int) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=413,
        detail={
            'error': 'payload_too_large',
            'message': f'The request body is larger than {limit} bytes',
        },
    )


class BodyLimitMiddleware:
    """Pure ASGI middleware that counts body bytes as the app reads them.

    A ``Content-Length`` over the limit gets 413 before the app runs.
    Otherwise ``receive`` raises a 413 :class:`fastapi.HTTPException`
    when the bytes read so far pass the limit, which also covers
    chunked bodies without ``Content-Length``. The app's exception
    middleware turns that into the response. The body is not buffered
    here.

    ``path_limits`` maps exact paths (no trailing slash) to a limit
    that replaces ``limit`` for that path.
    """

    def __init__(
        self,
        app: types.ASGIApp,
        limit: int,
        path_limits: dict[str, int] | None = None,
    ) -> None:
        self.app = app
        self.limit = limit
        self.path_limits = path_limits or {}

    async def __call__(
        self, scope: types.Scope, receive: types.Receive, send: types.Send
    ) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        limit = self.path_limits.get(scope['path'].rstrip('/'), self.limit)
        length = dict(scope['headers']).get(b'content-length')
        if length is not None and length.isdigit() and int(length) > limit:
            exc = _too_large(limit)
            response = responses.JSONResponse(
                status_code=exc.status_code, content={'detail': exc.detail}
            )
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> types.Message:
            nonlocal received
            message = await receive()
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > limit:
                    raise _too_large(limit)
            return message

        await self.app(scope, limited_receive, send)
