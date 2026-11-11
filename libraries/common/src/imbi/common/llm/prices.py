"""Model list prices from the LiteLLM price file.

The Anthropic and OpenAI list-models APIs return no prices, so the
catalog takes list prices from the public LiteLLM file. That file is
one JSON object keyed by model id; each entry gives USD per token. The
catalog stores USD per 1M tokens, kept to six decimal places to fit the
``NUMERIC(14, 6)`` cost columns.

Download failures raise :class:`~imbi.common.llm.discovery.DiscoveryError`
with a message safe to show an admin.
"""

import decimal
import time
import typing

from imbi.common.llm import discovery

__all__ = ['FIELDS', 'Prices', 'fetch', 'lookup', 'plan_update']

URL = (
    'https://raw.githubusercontent.com/BerriAI/litellm/main/'
    'model_prices_and_context_window.json'
)

#: A preview and the apply that follows it see the same prices, and the
#: file is not downloaded again for each request.
CACHE_SECONDS = 300.0

#: Catalog field -> LiteLLM per-token field.
FIELDS: dict[str, str] = {
    'input_cost_per_million': 'input_cost_per_token',
    'output_cost_per_million': 'output_cost_per_token',
    'cache_read_cost_per_million': 'cache_read_input_token_cost',
    'cache_write_cost_per_million': 'cache_creation_input_token_cost',
}

#: Drivers whose models LiteLLM also files under ``<driver>/<model_id>``.
_PREFIX_DRIVERS = frozenset({'anthropic', 'openai'})

_PLACES = decimal.Decimal('0.000001')

Prices = dict[str, decimal.Decimal | None]

_cache: tuple[float, dict[str, Prices]] | None = None


async def fetch() -> dict[str, Prices]:
    """Return the priced LiteLLM entries, cached for :data:`CACHE_SECONDS`.

    Entries without a valid ``input_cost_per_token`` are not priced
    models (``sample_spec``, for example) and are dropped.

    Raises:
        DiscoveryError: The download failed or was not a JSON object.

    """
    global _cache
    if _cache is not None and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    payload = await discovery._get_json(URL, {}, 'LiteLLM price file')
    if not isinstance(payload, dict):
        raise discovery.DiscoveryError(
            'The LiteLLM price file is not a JSON object'
        )
    table = _priced(typing.cast('dict[str, object]', payload))
    _cache = (time.monotonic(), table)
    return table


def _priced(payload: dict[str, object]) -> dict[str, Prices]:
    """Reduce the raw file to per-million prices of the priced entries."""
    table: dict[str, Prices] = {}
    for key, entry in payload.items():
        if not isinstance(entry, dict):
            continue
        entry = typing.cast('dict[str, object]', entry)
        if _per_million(entry.get('input_cost_per_token')) is None:
            continue
        table[key] = {
            field: _per_million(entry.get(source))
            for field, source in FIELDS.items()
        }
    return table


def lookup(
    table: dict[str, Prices], model_id: str, driver: str
) -> tuple[str, Prices] | None:
    """Find the prices of one catalog model.

    The exact ``model_id`` key wins; ``<driver>/<model_id>`` is tried
    next for the ``anthropic`` and ``openai`` drivers.

    Returns:
        The matched key and the per-million prices (``None`` where the
        entry has no price), or ``None`` when nothing matches.

    """
    keys = [model_id]
    if driver in _PREFIX_DRIVERS:
        keys.append(f'{driver}/{model_id}')
    for key in keys:
        if key in table:
            return key, table[key]
    return None


def plan_update(
    current: Prices, synced: Prices, *, overwrite: bool
) -> dict[str, decimal.Decimal]:
    """Return the fields to write and their new values.

    A missing price is filled. A set price that differs changes only
    with ``overwrite``, because contract rates can differ from list
    prices. A price LiteLLM does not have is left alone.
    """
    return {
        field: new
        for field, new in synced.items()
        if new is not None
        and new != current.get(field)
        and (overwrite or current.get(field) is None)
    }


#: USD per token. At or above this, the per-million price does not fit
#: the ``NUMERIC(14, 6)`` cost columns.
_MAX_PER_TOKEN = 100


def _per_million(value: object) -> decimal.Decimal | None:
    """USD per token -> USD per 1M tokens, or ``None`` for junk."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        # Also refuses NaN and infinity.
        or not 0 <= value < _MAX_PER_TOKEN
    ):
        return None
    result = (decimal.Decimal(str(value)) * 1_000_000).quantize(_PLACES)
    # Plain notation on the wire: ``10`` and ``0.01``, never ``1E+1``.
    if result == result.to_integral_value():
        return result.quantize(decimal.Decimal(1))
    return result.normalize()
