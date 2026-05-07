"""Shared AWS credentials + JSON-protocol client for the SSM and
CloudWatch Logs plugins.

We deliberately stay on ``httpx`` (already used by the IAM IC identity
plugin) and implement a minimal AWS SigV4 signer so the test suite can
keep using ``respx`` for mocking.  Both SSM and CloudWatch Logs speak
the JSON-1.1 wire protocol, so a single helper covers both surfaces.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import typing
import urllib.parse

import httpx
from imbi_common.plugins.base import PluginContext
from imbi_common.plugins.errors import (
    PluginCredentialsMissing,
    PluginTimeoutError,
    PluginUnavailableError,
)

ServiceName = typing.Literal['ssm', 'logs']

_SIGNING_ALGORITHM = 'AWS4-HMAC-SHA256'
_AWS_REQUEST = 'aws4_request'

_TARGET_PREFIX: dict[ServiceName, str] = {
    'ssm': 'AmazonSSM',
    'logs': 'Logs_20140328',
}


class AwsCredentials(typing.NamedTuple):
    """A validated set of AWS credentials + region."""

    access_key_id: str
    secret_access_key: str
    session_token: str | None
    region: str


_AWS_IDENTITY_KEYS = (
    'aws_access_key_id',
    'aws_secret_access_key',
    'aws_session_token',
    'aws_region',
    'aws_account_id',
)


def resolve_credentials(
    credentials: dict[str, str],
    *,
    region: str | None = None,
    ctx: PluginContext | None = None,
) -> AwsCredentials:
    """Validate the credentials dict and resolve the effective region.

    Two credential sources are supported and combined here:

    * ``credentials`` — static keys stored on the ``Plugin`` node by
      the operator (``api_token``-style auth).
    * ``ctx.identity.extra`` — STS keys minted by an identity plugin
      (currently ``aws-iam-ic``).  The host attaches these to
      :attr:`PluginContext.identity` via ``hydrate_identity`` and the
      data plugin must consult them, since the host does not merge
      identity creds into the ``credentials`` dict.

    Identity-supplied keys take precedence when present (a connected
    user's STS keys are always preferable to static fallbacks).
    ``region`` argument wins over both — it's the assignment option.

    Raises:
        PluginCredentialsMissing: when either AWS key is missing or
            when the region cannot be resolved.
    """
    merged: dict[str, str] = {k: v for k, v in credentials.items() if v}
    if ctx is not None and ctx.identity is not None:
        for key in _AWS_IDENTITY_KEYS:
            value = ctx.identity.extra.get(key)
            if isinstance(value, str) and value:
                merged[key] = value

    access_key = merged.get('aws_access_key_id') or ''
    secret_key = merged.get('aws_secret_access_key') or ''
    if not access_key and not secret_key:
        raise PluginCredentialsMissing(
            'AWS credentials missing: aws_access_key_id and '
            'aws_secret_access_key are required'
        )
    if not access_key or not secret_key:
        raise PluginCredentialsMissing(
            'AWS credentials malformed: both aws_access_key_id and '
            'aws_secret_access_key must be provided'
        )
    resolved_region = region or merged.get('aws_region')
    if not resolved_region:
        raise PluginCredentialsMissing(
            'AWS region missing: pass region explicitly or set '
            'aws_region in credentials'
        )
    session_token = merged.get('aws_session_token') or None
    return AwsCredentials(
        access_key_id=access_key,
        secret_access_key=secret_key,
        session_token=session_token,
        region=resolved_region,
    )


def _hmac(key: bytes, data: str) -> bytes:
    return hmac.new(key, data.encode('utf-8'), hashlib.sha256).digest()


def _signing_key(
    secret_access_key: str, date_stamp: str, region: str, service: str
) -> bytes:
    k_date = _hmac(f'AWS4{secret_access_key}'.encode(), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    return _hmac(k_service, _AWS_REQUEST)


def sign_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
    service: str,
    credentials: AwsCredentials,
    now: datetime.datetime | None = None,
) -> dict[str, str]:
    """Return signed request headers (SigV4) for an AWS JSON request.

    The returned mapping is the *complete* set of headers to send: the
    caller's ``headers`` plus ``Host``, ``X-Amz-Date``,
    ``X-Amz-Security-Token`` (when applicable), and ``Authorization``.
    """
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc
    canonical_uri = parsed.path or '/'
    canonical_query = parsed.query
    timestamp = (now or datetime.datetime.now(datetime.UTC)).strftime(
        '%Y%m%dT%H%M%SZ'
    )
    date_stamp = timestamp[:8]
    payload_hash = hashlib.sha256(body).hexdigest()

    signed: dict[str, str] = {**headers, 'host': host, 'x-amz-date': timestamp}
    if credentials.session_token:
        signed['x-amz-security-token'] = credentials.session_token

    canonical_headers_pairs = sorted(
        (name.lower(), value.strip()) for name, value in signed.items()
    )
    canonical_headers = ''.join(
        f'{name}:{value}\n' for name, value in canonical_headers_pairs
    )
    signed_header_names = ';'.join(name for name, _ in canonical_headers_pairs)
    canonical_request = '\n'.join(
        [
            method.upper(),
            canonical_uri,
            canonical_query,
            canonical_headers,
            signed_header_names,
            payload_hash,
        ]
    )

    credential_scope = (
        f'{date_stamp}/{credentials.region}/{service}/{_AWS_REQUEST}'
    )
    string_to_sign = '\n'.join(
        [
            _SIGNING_ALGORITHM,
            timestamp,
            credential_scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )

    signature = hmac.new(
        _signing_key(
            credentials.secret_access_key,
            date_stamp,
            credentials.region,
            service,
        ),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()
    authorization = (
        f'{_SIGNING_ALGORITHM} '
        f'Credential={credentials.access_key_id}/{credential_scope}, '
        f'SignedHeaders={signed_header_names}, '
        f'Signature={signature}'
    )
    signed['Authorization'] = authorization
    return signed


def _service_endpoint(service: ServiceName, region: str) -> str:
    return f'https://{service}.{region}.amazonaws.com/'


def _extract_error_code(payload: dict[str, typing.Any]) -> str:
    error_type = payload.get('__type') or payload.get('Code') or ''
    if isinstance(error_type, str) and '#' in error_type:
        error_type = error_type.split('#', 1)[1]
    return str(error_type or '')


def _map_status_error(
    status_code: int,
    error_code: str,
    message: str,
    error_map: dict[str, type[Exception]],
) -> Exception:
    """Translate an AWS error into the appropriate Imbi exception."""
    if error_code in error_map:
        return error_map[error_code](message or error_code)
    if status_code >= 500:
        return PluginUnavailableError(message or f'AWS {status_code}')
    return PluginUnavailableError(
        message or f'AWS error {error_code or status_code}'
    )


async def call_aws_json(
    *,
    service: ServiceName,
    action: str,
    body: dict[str, typing.Any],
    credentials: AwsCredentials,
    error_map: dict[str, type[Exception]],
    timeout: float = 15.0,
    client: httpx.AsyncClient | None = None,
) -> dict[str, typing.Any]:
    """Invoke an AWS JSON-1.1 action and return the decoded response.

    ``error_map`` maps AWS error codes (e.g. ``ParameterNotFound``) to
    the Imbi exception class to raise.  Errors not in the map fall back
    to :class:`PluginUnavailableError` for 5xx and a default of
    :class:`PluginUnavailableError` otherwise.
    """
    payload = json.dumps(body).encode()
    target = f'{_TARGET_PREFIX[service]}.{action}'
    base_headers: dict[str, str] = {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': target,
    }
    url = _service_endpoint(service, credentials.region)
    signed_headers = sign_request(
        method='POST',
        url=url,
        headers=base_headers,
        body=payload,
        service=service,
        credentials=credentials,
    )

    async def _do(http: httpx.AsyncClient) -> httpx.Response:
        return await http.post(url, content=payload, headers=signed_headers)

    try:
        if client is None:
            async with httpx.AsyncClient(timeout=timeout) as http:
                response = await _do(http)
        else:
            response = await _do(client)
    except (httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
        raise PluginTimeoutError(str(exc)) from exc

    if response.status_code == 200:
        if not response.content:
            return {}
        return typing.cast(dict[str, typing.Any], response.json())

    try:
        err_payload = typing.cast(dict[str, typing.Any], response.json())
    except ValueError:
        err_payload = {}
    error_code = _extract_error_code(err_payload)
    error_message = str(
        err_payload.get('message')
        or err_payload.get('Message')
        or response.text
        or ''
    )
    raise _map_status_error(
        response.status_code, error_code, error_message, error_map
    )
