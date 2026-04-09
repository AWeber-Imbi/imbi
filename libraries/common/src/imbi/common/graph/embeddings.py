"""Local embedding generation via fastembed.

Models are loaded lazily on first use and cached for the
lifetime of the process.  All embedding calls are offloaded
to a thread to avoid blocking the event loop.
"""

import asyncio
import logging
import threading
import typing

import fastembed

from imbi_common import settings

LOGGER = logging.getLogger(__name__)

_lock = threading.RLock()
_models: dict[str, fastembed.TextEmbedding] = {}
_registry: dict[str, settings.EmbeddingModelConfig] | None = None
_default_model: str | None = None


def _get_registry() -> dict[str, settings.EmbeddingModelConfig]:
    """Return the model registry, loading from settings."""
    global _registry, _default_model
    with _lock:
        if _registry is None:
            embed_settings = settings.Embeddings()
            _registry = embed_settings.models
            _default_model = embed_settings.default_model
    return _registry


def default_model() -> str:
    """Return the configured default model name."""
    _get_registry()
    return _default_model or 'text'


def _resolve(model_name: str | None) -> str:
    """Resolve *model_name*, falling back to the default."""
    if model_name is not None:
        return model_name
    return default_model()


def _get_model(model_name: str) -> fastembed.TextEmbedding:
    """Return a cached TextEmbedding, loading on first call."""
    with _lock:
        if model_name not in _models:
            registry = _get_registry()
            if model_name not in registry:
                raise KeyError(
                    f'Unknown embedding model: {model_name!r}',
                )
            spec = registry[model_name]
            LOGGER.info(
                'Loading embedding model %r (%s)',
                model_name,
                spec.fastembed_id,
            )
            _models[model_name] = fastembed.TextEmbedding(
                model_name=spec.fastembed_id,
            )
    return _models[model_name]


def get_dimensions(model_name: str | None = None) -> int:
    """Return the output dimensions for the named model."""
    name = _resolve(model_name)
    registry = _get_registry()
    if name not in registry:
        raise KeyError(
            f'Unknown embedding model: {name!r}',
        )
    return registry[name].dimensions


def embed(
    texts: list[str],
    model_name: str | None = None,
) -> list[list[float]]:
    """Embed a batch of texts synchronously.

    Returns a list of float vectors, one per input text.

    """
    name = _resolve(model_name)
    model = _get_model(name)
    return [typing.cast(list[float], v.tolist()) for v in model.embed(texts)]


async def aembed(
    texts: list[str],
    model_name: str | None = None,
) -> list[list[float]]:
    """Embed a batch of texts asynchronously via thread."""
    return await asyncio.to_thread(
        embed,
        texts,
        _resolve(model_name),
    )


async def aembed_one(
    text: str,
    model_name: str | None = None,
) -> list[float]:
    """Embed a single text string."""
    results = await aembed([text], model_name)
    return results[0]


def close() -> None:
    """Release all cached models."""
    global _registry, _default_model
    with _lock:
        _models.clear()
        _registry = None
        _default_model = None
