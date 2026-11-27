"""Pull a provider's model list from its own list-models API.

Used to seed :class:`imbi.common.models.AIModel` nodes instead of having
an admin type vendor model ids by hand, and doubling as a connection
test for the stored credential.

Every failure is normalised to :class:`DiscoveryError` carrying a
message safe to show an admin: the driver, and the transport or HTTP
status that failed. Provider response bodies and the API key never
appear in it, because the caller surfaces the message verbatim.
"""

import dataclasses
import datetime
import logging
import typing
import urllib.parse

import anthropic
import httpx

from imbi.common.llm import drivers

LOGGER = logging.getLogger(__name__)

__all__ = ['DiscoveredModel', 'DiscoveryError', 'list_models']

#: Outbound calls target an endpoint an admin supplied for
#: ``openai_compatible`` providers, so they get a short leash.
TIMEOUT = 10.0

#: Ceiling on auto-paginated results, so a misbehaving endpoint that
#: keeps handing back a next cursor cannot spin here forever.
MAX_MODELS = 1000


#: A Bearer token on the Anthropic API needs this beta (anthropic SDK
#: ``lib/credentials``).
OAUTH_BETA = 'oauth-2025-04-20'


class DiscoveryError(Exception):
    """A provider's model list could not be retrieved.

    ``status`` is the HTTP status of the provider, when it answered.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclasses.dataclass(frozen=True, slots=True)
class DiscoveredModel:
    """One model reported by a provider."""

    model_id: str
    display_name: str
    created_at: datetime.datetime | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None


async def list_models(
    driver: str,
    api_key: str,
    base_url: str | None,
    *,
    bearer: bool = False,
    region: str | None = None,
    auth: httpx.Auth | None = None,
) -> list[DiscoveredModel]:
    """Return the models ``driver`` reports for ``api_key``.

    Parameters:
        driver: Provider driver slug.
        api_key: Decrypted credential for the provider.
        base_url: Endpoint to call, already resolved against the
            driver's default.
        bearer: ``api_key`` is a workload identity access token.
        region: Bedrock only: the AWS region to list.
        auth: Bedrock only: signs the request when ``api_key`` is
            empty (SigV4 with the AWS credentials of the process).

    Returns:
        The provider's models, in the order the provider returned them.

    Raises:
        DiscoveryError: The driver cannot be discovered, or the call
            failed. The message is safe to show an admin.

    """
    if driver == 'anthropic':
        return await _list_anthropic(api_key, base_url, bearer=bearer)
    if driver in ('openai', 'openai_compatible'):
        if not base_url:
            raise DiscoveryError(
                f'Driver {driver!r} has no endpoint configured'
            )
        return await _list_openai(api_key, base_url)
    if driver == 'bedrock':
        return await _list_bedrock(api_key, region, auth)
    if driver == 'vertex':
        return await _list_vertex(api_key, base_url, bearer=bearer)
    raise DiscoveryError(f'Driver {driver!r} does not support discovery')


def _as_int(value: object) -> int | None:
    """Coerce a provider-supplied token count, dropping nonsense."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


async def _list_anthropic(
    api_key: str, base_url: str | None, *, bearer: bool = False
) -> list[DiscoveredModel]:
    """List Anthropic models through the ``anthropic`` SDK.

    ``AsyncModels.list`` returns a paginator that fetches the next page
    on demand, so iterating it walks the whole catalog;
    :data:`MAX_MODELS` bounds that walk. ``max_input_tokens`` and
    ``max_tokens`` are optional on ``ModelInfo`` (they only appear on
    models published since March 2026), so both are treated as absent
    rather than assumed.
    """
    found: list[DiscoveredModel] = []
    try:
        # An explicit credential stops the SDK from reading
        # ANTHROPIC_API_KEY, so a token is never sent with a key.
        auth: dict[str, typing.Any] = (
            {
                'auth_token': api_key,
                'default_headers': {'anthropic-beta': OAUTH_BETA},
            }
            if bearer
            else {'api_key': api_key}
        )
        async with anthropic.AsyncAnthropic(
            **auth,
            base_url=base_url,
            timeout=TIMEOUT,
            max_retries=1,
        ) as client:
            async for model in client.models.list(limit=100):
                found.append(
                    DiscoveredModel(
                        model_id=model.id,
                        display_name=model.display_name or model.id,
                        created_at=model.created_at,
                        context_window=_as_int(model.max_input_tokens),
                        max_output_tokens=_as_int(model.max_tokens),
                    )
                )
                if len(found) >= MAX_MODELS:
                    break
    except anthropic.APIStatusError as exc:
        LOGGER.warning(
            'Model discovery for anthropic returned HTTP %s',
            exc.status_code,
        )
        raise DiscoveryError(
            f'The anthropic endpoint returned HTTP {exc.status_code}',
            exc.status_code,
        ) from exc
    except anthropic.AnthropicError as exc:
        LOGGER.warning(
            'Model discovery failure for anthropic: %s', type(exc).__name__
        )
        raise DiscoveryError(
            f'Could not reach the anthropic endpoint ({type(exc).__name__})'
        ) from exc
    return found


async def _list_openai(api_key: str, base_url: str) -> list[DiscoveredModel]:
    """List models via the OpenAI-compatible ``GET {base_url}/models``.

    The OpenAI model object carries no context or output-token metadata,
    so those stay ``None`` and the admin fills them in if they matter.
    """
    payload = await _get_json(
        f'{base_url.rstrip("/")}/models',
        {'Authorization': f'Bearer {api_key}'},
        'openai',
    )
    found: list[DiscoveredModel] = []
    for item in _entries(payload, 'data'):
        model_id = item.get('id')
        if not isinstance(model_id, str) or not model_id:
            continue
        found.append(
            DiscoveredModel(
                model_id=model_id,
                display_name=model_id,
                created_at=_parse_timestamp(item.get('created')),
            )
        )
    return found


async def _list_bedrock(
    api_key: str, region: str | None, auth: httpx.Auth | None
) -> list[DiscoveredModel]:
    """List Bedrock foundation models (``ListFoundationModels``).

    The control plane is ``bedrock.{region}``, not the runtime endpoint
    in ``base_url``. Only models with text output and on-demand
    inference are kept: a model that needs an inference profile cannot
    be called by its own id. A ``LEGACY`` model is dropped too.
    """
    if not region:
        raise DiscoveryError("Driver 'bedrock' has no region configured")
    try:
        drivers.check_location('bedrock', region, None)
    except ValueError as exc:
        raise DiscoveryError(str(exc)) from None
    payload = await _get_json(
        f'https://bedrock.{region}.amazonaws.com/foundation-models'
        '?byOutputModality=TEXT&byInferenceType=ON_DEMAND',
        {'Authorization': f'Bearer {api_key}'} if api_key else {},
        'bedrock',
        auth,
    )
    found: list[DiscoveredModel] = []
    for item in _entries(payload, 'modelSummaries'):
        model_id = item.get('modelId')
        if (
            not isinstance(model_id, str)
            or not model_id
            or 'TEXT' not in (item.get('outputModalities') or ())
            or 'ON_DEMAND' not in (item.get('inferenceTypesSupported') or ())
            or (item.get('modelLifecycle') or {}).get('status', 'ACTIVE')
            != 'ACTIVE'
        ):
            continue
        found.append(
            DiscoveredModel(
                model_id=model_id,
                display_name=str(item.get('modelName') or model_id),
            )
        )
    return found


async def _list_vertex(
    api_key: str, base_url: str | None, *, bearer: bool = False
) -> list[DiscoveredModel]:
    """List Gemini models (``publishers.models.list``, ``v1beta1``).

    The express mode API reference does not include this method, so an
    express key can be refused. A 401 or 403 then gives a message that
    tells the admin to add the models by id.
    """
    url = (
        f'{(base_url or "https://aiplatform.googleapis.com").rstrip("/")}'
        '/v1beta1/publishers/google/models'
    )
    headers = (
        {'Authorization': f'Bearer {api_key}'}
        if bearer
        else {'x-goog-api-key': api_key}
    )
    found: list[DiscoveredModel] = []
    token = ''
    seen: set[str] = set()
    # Count pages, not kept models: most models are not Gemini.
    for _page in range(MAX_MODELS // 100 + 1):
        try:
            payload = await _get_json(
                f'{url}?pageSize=100&pageToken={token}', headers, 'vertex'
            )
        except DiscoveryError as exc:
            if exc.status in (401, 403):
                raise DiscoveryError(
                    f'The vertex endpoint returned HTTP {exc.status}. An '
                    'express mode API key may not be allowed to list '
                    'models: add the models by id',
                    exc.status,
                ) from exc
            raise
        for item in _entries(payload, 'publisherModels'):
            model_id = str(item.get('name') or '').rpartition('/')[2]
            # Generation calls Gemini only (generateContent).
            if model_id.startswith('gemini'):
                found.append(DiscoveredModel(model_id, model_id))
        page = typing.cast(
            'dict[str, object]', payload if isinstance(payload, dict) else {}
        )
        token = urllib.parse.quote(str(page.get('nextPageToken') or ''))
        if not token or token in seen or len(found) >= MAX_MODELS:
            break
        seen.add(token)
    return found[:MAX_MODELS]


def _entries(payload: object, key: str) -> list[dict[str, typing.Any]]:
    """Return the list of objects under ``key`` in a provider payload."""
    if not isinstance(payload, dict):
        return []
    data = typing.cast('dict[str, object]', payload).get(key)
    if not isinstance(data, list):
        return []
    items = typing.cast('list[object]', data)
    return [
        typing.cast('dict[str, typing.Any]', item)
        for item in items
        if isinstance(item, dict)
    ]


def _parse_timestamp(value: object) -> datetime.datetime | None:
    """Parse an ISO-8601 string or a Unix epoch into a datetime."""
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    try:
        return datetime.datetime.fromtimestamp(value, datetime.UTC)
    except (OverflowError, OSError, ValueError):
        return None


async def _get_json(
    url: str,
    headers: dict[str, str],
    driver: str,
    auth: httpx.Auth | None = None,
) -> object:
    """GET ``url`` and return the decoded JSON body.

    Raises:
        DiscoveryError: On any transport error, non-2xx status, or
            undecodable body. The message names the driver and the
            status only — never the response body, which can echo the
            credential back.

    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                url, headers=headers, auth=auth or httpx.USE_CLIENT_DEFAULT
            )
    except httpx.HTTPError as exc:
        LOGGER.warning(
            'Model discovery transport failure for %s: %s',
            driver,
            type(exc).__name__,
        )
        raise DiscoveryError(
            f'Could not reach the {driver} endpoint ({type(exc).__name__})'
        ) from exc
    if response.status_code >= 400:
        LOGGER.warning(
            'Model discovery for %s returned HTTP %s',
            driver,
            response.status_code,
        )
        raise DiscoveryError(
            f'The {driver} endpoint returned HTTP {response.status_code}',
            response.status_code,
        )
    try:
        return response.json()
    except ValueError as exc:
        raise DiscoveryError(
            f'The {driver} endpoint returned a non-JSON response'
        ) from exc
