"""Call a catalog model with the credentials of its provider.

The credential comes from the provider, in this order:

1. The stored key.
2. A workload identity token (one retry with a new token after a 401).
3. Bedrock only: the AWS credentials of this process (the runtime IAM
   role), which sign each request with SigV4.

A Vertex provider with no key fails with ``provider_misconfigured``:
Google credentials need ``google-auth``, which imbi-api does not have.
"""

import asyncio
import collections.abc
import dataclasses
import functools
import http
import typing

import httpx
from botocore import (  # pyright: ignore[reportMissingTypeStubs]
    auth as aws_auth,
)
from botocore import (  # pyright: ignore[reportMissingTypeStubs]
    awsrequest,
    exceptions,
    session,
)

from imbi.api.llm import tokens
from imbi.api.secret_broker import store
from imbi.common import models
from imbi.common.auth.encryption import decrypt_config_value
from imbi.common.llm import generate
from imbi.common.plugins.identity import IdentityError


class SigV4(httpx.Auth):
    """Sign each request for Bedrock with AWS SigV4."""

    requires_request_body = True

    def __init__(self, credentials: object, region: str) -> None:
        self._signer: typing.Any = aws_auth.SigV4Auth(
            credentials, 'bedrock', region
        )

    def auth_flow(
        self, request: httpx.Request
    ) -> collections.abc.Generator[httpx.Request, httpx.Response]:
        signed = awsrequest.AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers={'Content-Type': request.headers['Content-Type']},
        )
        self._signer.add_auth(signed)
        request.headers.update(dict(signed.headers.items()))
        yield request


@functools.cache
def _aws_session() -> typing.Any:
    """One botocore session: its credentials refresh themselves."""
    aws: typing.Any = session
    return aws.get_session()


async def _sigv4(region: str | None) -> SigV4:
    """Return a signer with the AWS credentials of this process."""

    def frozen() -> object:
        # The credential chain can read files and call the instance
        # metadata service, so it runs in a thread.
        found = _aws_session().get_credentials()
        return found and found.get_frozen_credentials()

    try:
        credentials = await asyncio.to_thread(frozen)
    except exceptions.BotoCoreError:
        # For example, the container credential endpoint is down.
        raise generate.GenerateError(
            'credentials_unavailable', retry=True
        ) from None
    if not credentials or not region:
        raise generate.GenerateError('provider_misconfigured')
    return SigV4(credentials, region)


async def call(
    secrets: store.SecretStore,
    provider: models.AIProvider,
    request: generate.Request,
    dispatched: asyncio.Event | None = None,
) -> generate.Result:
    """Call the model of ``request`` once, with the provider's
    credentials.

    ``dispatched`` is set when the credentials are ready and the request
    to the provider starts. Before that, no request was sent. A ``401``
    for a workload identity token clears it until the request with a
    new token starts.

    Raises:
        generate.GenerateError: The call failed. A workload identity
            token that could not be minted is ``credentials_unavailable``
            (retry) or ``credentials_failed``.

    """

    async def send(request: generate.Request) -> generate.Result:
        if dispatched is not None:
            dispatched.set()
        return await generate.generate(request)

    def unauthorized(exc: Exception) -> bool:
        # The provider rejected the token: no call ran. Until the
        # request with a new token starts, no request is in flight.
        if not (
            isinstance(exc, generate.GenerateError)
            and exc.status == http.HTTPStatus.UNAUTHORIZED
        ):
            return False
        if dispatched is not None:
            dispatched.clear()
        return True

    key = decrypt_config_value(provider.credentials_encrypted)
    if key:
        return await send(dataclasses.replace(request, credential=key))
    if provider.workload_identity is not None:
        try:
            return await tokens.call(
                secrets,
                provider,
                lambda token: send(
                    dataclasses.replace(request, credential=token, bearer=True)
                ),
                unauthorized,
            )
        except IdentityError as exc:
            if exc.retryable:
                raise generate.GenerateError(
                    'credentials_unavailable', retry=True
                ) from None
            raise generate.GenerateError('credentials_failed') from None
    if provider.driver == 'bedrock':
        auth = await _sigv4(provider.region)
        return await send(dataclasses.replace(request, auth=auth))
    if provider.driver == 'vertex':
        raise generate.GenerateError('provider_misconfigured')
    return await send(request)
