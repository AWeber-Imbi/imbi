"""The ``aws_sts`` identity source (WIF plan 4.2).

imbi-api assumes the organization's identity role (with
``sts:ExternalId`` ``imbi:<organization id>``) and calls STS
``GetWebIdentityToken`` with that session. The JWT ``sub`` is the role
ARN. Core sets the audience, tags, lifetime, and signing algorithm.

The role needs ``sts:GetWebIdentityToken`` and
``sts:TagGetWebIdentityToken``, and a ``MaxSessionDuration`` of at least
:func:`session_seconds` of the longest JWT (3900 seconds for a 3600
second JWT). The AWS account must have outbound web identity
federation turned on.
"""

import logging
import typing
import urllib.parse
import xml.etree.ElementTree as ET

import httpx
from botocore import (  # pyright: ignore[reportMissingTypeStubs]
    exceptions as botocore_exceptions,
)

from imbi.common.plugins import identity
from imbi.plugins.aws import aws_session, secrets_manager

LOGGER = logging.getLogger(__name__)

#: STS error codes, by safe reason code. Anything else is
#: ``provider_error``.
_REASONS = {
    'AccessDenied': 'access_denied',
    'AccessDeniedException': 'access_denied',
    'OutboundWebIdentityFederationDisabled': 'federation_disabled',
    'SessionDurationEscalation': 'session_duration_escalation',
    'JWTPayloadSizeExceeded': 'payload_too_large',
    'ExpiredToken': 'credentials_expired',
    'ExpiredTokenException': 'credentials_expired',
    'ValidationError': 'invalid_request',
}
_RETRYABLE = frozenset(
    {'Throttling', 'ThrottlingException', 'ServiceUnavailable'}
)
_TIMEOUT_SECONDS = 10


def session_seconds(jwt_seconds: int) -> int:
    """The role session lifetime for a JWT of ``jwt_seconds``.

    STS refuses a JWT that would outlive the session
    (``SessionDurationEscalation``), so the session lasts 5 minutes
    longer. AssumeRole needs at least 900 seconds.
    """
    return max(900, jwt_seconds + 300)


def _error(code: str) -> identity.IdentityError:
    if code in _RETRYABLE:
        return identity.IdentityError('throttled', retryable=True)
    return identity.IdentityError(_REASONS.get(code, 'provider_error'))


def _endpoint(region: str) -> str:
    """The regional STS endpoint. ``GetWebIdentityToken`` is not on the
    global endpoint. The operator override is for LocalStack only."""
    override = secrets_manager.endpoint_url()
    if override:
        return override
    suffix = (
        '.amazonaws.com.cn' if region.startswith('cn-') else '.amazonaws.com'
    )
    return f'https://sts.{region}{suffix}/'


def _body(request: identity.IdentityRequest) -> str:
    params = {
        'Action': 'GetWebIdentityToken',
        'Version': '2011-06-15',
        'Audience.member.1': request.audience,
        'SigningAlgorithm': request.signing_algorithm,
        'DurationSeconds': str(request.duration_seconds),
    }
    for number, (key, value) in enumerate(sorted(request.tags.items()), 1):
        params[f'Tags.member.{number}.Key'] = key
        params[f'Tags.member.{number}.Value'] = value
    return urllib.parse.urlencode(params)


class AwsStsIdentity(identity.IdentitySource):
    """AWS STS ``GetWebIdentityToken`` with the organization's role."""

    type = 'aws_sts'
    label = 'AWS STS'

    def validate_config(
        self, config: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        return identity.validate_model(secrets_manager.RoleConfig, config)

    async def check_config(
        self, config: dict[str, typing.Any], organization_id: str
    ) -> None:
        await secrets_manager.check_role(config, organization_id)

    async def identity_token(
        self, config: dict[str, typing.Any], request: identity.IdentityRequest
    ) -> str:
        # ponytail: each JWT costs a new aioboto3 session, an AssumeRole,
        # and a new httpx client (two TLS handshakes). Cache the role
        # session (renew it before it has less than session_seconds
        # left) and share the clients if the mint rate matters.
        try:
            credentials = await secrets_manager.assume_role(
                config,
                request.organization_id,
                RoleSessionName='imbi-workload-identity',
                DurationSeconds=session_seconds(request.duration_seconds),
            )
        except botocore_exceptions.ClientError as err:
            code = secrets_manager.client_error_code(err)
            LOGGER.warning('AWS identity role assumption failed: %s', code)
            raise _error(code) from None
        except Exception as err:  # noqa: BLE001 - fail closed
            LOGGER.warning(
                'AWS identity role assumption failed: %s', type(err).__name__
            )
            raise identity.IdentityError(
                'unreachable', retryable=True
            ) from None
        return await self._get_web_identity_token(
            config['region'], credentials, request
        )

    async def _get_web_identity_token(
        self,
        region: str,
        credentials: dict[str, typing.Any],
        request: identity.IdentityRequest,
    ) -> str:
        """Call ``GetWebIdentityToken`` as a signed STS Query request.

        The locked botocore (aioboto3 pins it) has no model for this
        operation, so the request is signed here.
        """
        # ponytail: hand-signed Query call. Use
        # ``sts.get_web_identity_token`` when aioboto3 ships a botocore
        # with the operation.
        url = _endpoint(region)
        body = _body(request).encode()
        headers = aws_session.sign_request(
            method='POST',
            url=url,
            headers={
                'Content-Type': 'application/x-www-form-urlencoded; '
                'charset=utf-8'
            },
            body=body,
            service='sts',
            credentials=aws_session.AwsCredentials(
                credentials['AccessKeyId'],
                credentials['SecretAccessKey'],
                credentials['SessionToken'],
                region,
            ),
        )
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT_SECONDS, follow_redirects=False
            ) as client:
                response = await client.post(
                    url, content=body, headers=headers
                )
            root = ET.fromstring(response.content)  # noqa: S314
        except (httpx.HTTPError, ET.ParseError) as err:
            LOGGER.warning(
                'AWS GetWebIdentityToken failed: %s', type(err).__name__
            )
            raise identity.IdentityError(
                'unreachable', retryable=True
            ) from None
        if response.status_code != 200:
            code = root.findtext('.//{*}Code') or ''
            LOGGER.warning('AWS GetWebIdentityToken failed: %s', code)
            if response.status_code >= 500 and code not in _REASONS:
                raise identity.IdentityError('unavailable', retryable=True)
            raise _error(code)
        token = root.findtext('.//{*}WebIdentityToken')
        if not token:
            raise identity.IdentityError('provider_error')
        return token
