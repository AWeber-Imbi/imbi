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

import anthropic
import httpx

LOGGER = logging.getLogger(__name__)

__all__ = ['DiscoveredModel', 'DiscoveryError', 'list_models']

#: Outbound calls target an endpoint an admin supplied for
#: ``openai_compatible`` providers, so they get a short leash.
TIMEOUT = 10.0

#: Ceiling on auto-paginated results, so a misbehaving endpoint that
#: keeps handing back a next cursor cannot spin here forever.
MAX_MODELS = 1000


class DiscoveryError(Exception):
    """A provider's model list could not be retrieved."""


@dataclasses.dataclass(frozen=True, slots=True)
class DiscoveredModel:
    """One model reported by a provider."""

    model_id: str
    display_name: str
    created_at: datetime.datetime | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None


async def list_models(
    driver: str, api_key: str, base_url: str | None
) -> list[DiscoveredModel]:
    """Return the models ``driver`` reports for ``api_key``.

    Parameters:
        driver: Provider driver slug.
        api_key: Decrypted credential for the provider.
        base_url: Endpoint to call, already resolved against the
            driver's default.

    Returns:
        The provider's models, in the order the provider returned them.

    Raises:
        DiscoveryError: The driver cannot be discovered, or the call
            failed. The message is safe to show an admin.

    """
    if driver == 'anthropic':
        return await _list_anthropic(api_key, base_url)
    if driver in ('openai', 'openai_compatible'):
        if not base_url:
            raise DiscoveryError(
                f'Driver {driver!r} has no endpoint configured'
            )
        return await _list_openai(api_key, base_url)
    raise DiscoveryError(f'Driver {driver!r} does not support discovery')


def _as_int(value: object) -> int | None:
    """Coerce a provider-supplied token count, dropping nonsense."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


async def _list_anthropic(
    api_key: str, base_url: str | None
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
        async with anthropic.AsyncAnthropic(
            api_key=api_key,
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
            f'The anthropic endpoint returned HTTP {exc.status_code}'
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


async def _get_json(url: str, headers: dict[str, str], driver: str) -> object:
    """GET ``url`` and return the decoded JSON body.

    Raises:
        DiscoveryError: On any transport error, non-2xx status, or
            undecodable body. The message names the driver and the
            status only — never the response body, which can echo the
            credential back.

    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(url, headers=headers)
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
            f'The {driver} endpoint returned HTTP {response.status_code}'
        )
    try:
        return response.json()
    except ValueError as exc:
        raise DiscoveryError(
            f'The {driver} endpoint returned a non-JSON response'
        ) from exc
