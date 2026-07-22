"""Thumbnail generation for uploaded images."""

import asyncio
import io
import logging
import warnings

import PIL
import PIL.Image

from imbi.api import settings

LOGGER = logging.getLogger(__name__)

# Pillow's built-in decompression-bomb guard is 178956970 pixels (~178MP)
# and only emits a warning by default. Tighten the cap to 64MP — large
# enough for any legitimate user-uploaded image, small enough to keep a
# crafted PNG from exhausting memory during ``Image.open`` — and turn
# the warning into an exception so the upload pipeline rejects the
# request instead of silently allocating gigabytes.
PIL.Image.MAX_IMAGE_PIXELS = 64 * 1024 * 1024
warnings.simplefilter('error', PIL.Image.DecompressionBombWarning)

_THUMBNAIL_TYPES = frozenset(
    {
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
    }
)


def can_thumbnail(content_type: str) -> bool:
    """Check whether thumbnails can be generated for a content type.

    Returns True for raster image formats. SVG and non-image types
    are not supported.

    Args:
        content_type: MIME type to check

    Returns:
        True if thumbnail generation is supported.

    """
    return content_type in _THUMBNAIL_TYPES


async def generate_thumbnail(
    data: bytes,
    storage_settings: settings.Storage | None = None,
) -> bytes:
    """Generate a WEBP thumbnail from image data.

    Runs Pillow in a thread executor to avoid blocking the event
    loop. The thumbnail maintains the original aspect ratio and
    fits within the configured maximum dimensions.

    Args:
        data: Original image bytes
        storage_settings: Storage settings (uses defaults if None)

    Returns:
        Thumbnail image as WEBP bytes

    """
    if storage_settings is None:
        storage_settings = settings.get_storage_settings()

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _generate_thumbnail_sync,
        data,
        storage_settings.thumbnail_max_size,
        storage_settings.thumbnail_quality,
    )


def _generate_thumbnail_sync(
    data: bytes,
    max_size: int,
    quality: int,
) -> bytes:
    """Synchronous thumbnail generation.

    Args:
        data: Original image bytes
        max_size: Maximum dimension (width or height) in pixels
        quality: WEBP compression quality (1-100)

    Returns:
        Thumbnail image as WEBP bytes

    """
    try:
        with PIL.Image.open(io.BytesIO(data)) as img:
            img.thumbnail((max_size, max_size))
            buffer = io.BytesIO()
            img.save(buffer, format='WEBP', quality=quality)
            return buffer.getvalue()
    except (
        PIL.UnidentifiedImageError,
        PIL.Image.DecompressionBombError,
        PIL.Image.DecompressionBombWarning,
        OSError,
    ) as err:
        raise ValueError(f'Cannot generate thumbnail: {err}') from err
