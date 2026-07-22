"""Tests for thumbnail generation."""

import io
import unittest

import PIL.Image

from imbi_api.storage import thumbnails


class CanThumbnailTestCase(unittest.TestCase):
    """Test cases for can_thumbnail."""

    def test_jpeg(self) -> None:
        self.assertTrue(thumbnails.can_thumbnail('image/jpeg'))

    def test_png(self) -> None:
        self.assertTrue(thumbnails.can_thumbnail('image/png'))

    def test_gif(self) -> None:
        self.assertTrue(thumbnails.can_thumbnail('image/gif'))

    def test_webp(self) -> None:
        self.assertTrue(thumbnails.can_thumbnail('image/webp'))

    def test_svg_not_supported(self) -> None:
        self.assertFalse(thumbnails.can_thumbnail('image/svg+xml'))

    def test_pdf_not_supported(self) -> None:
        self.assertFalse(
            thumbnails.can_thumbnail('application/pdf'),
        )


def _create_test_image(
    width: int = 512,
    height: int = 512,
    fmt: str = 'PNG',
) -> bytes:
    """Create a small test image in the given format."""
    img = PIL.Image.new('RGB', (width, height), color='red')
    buffer = io.BytesIO()
    img.save(buffer, format=fmt)
    return buffer.getvalue()


class GenerateThumbnailTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for generate_thumbnail."""

    async def test_creates_webp_thumbnail(self) -> None:
        """Test that a WEBP thumbnail is generated."""
        data = _create_test_image()
        result = await thumbnails.generate_thumbnail(data)

        # Verify the result is a valid WEBP image
        img = PIL.Image.open(io.BytesIO(result))
        self.assertEqual(img.format, 'WEBP')

    async def test_respects_max_size(self) -> None:
        """Test that the thumbnail respects max dimensions."""
        data = _create_test_image(width=1024, height=768)
        result = await thumbnails.generate_thumbnail(data)

        img = PIL.Image.open(io.BytesIO(result))
        self.assertLessEqual(img.width, 256)
        self.assertLessEqual(img.height, 256)

    async def test_maintains_aspect_ratio(self) -> None:
        """Test that the thumbnail maintains aspect ratio."""
        data = _create_test_image(width=800, height=400)
        result = await thumbnails.generate_thumbnail(data)

        img = PIL.Image.open(io.BytesIO(result))
        # Width should be 256, height should be ~128
        self.assertLessEqual(img.width, 256)
        self.assertLess(img.height, img.width)

    async def test_small_image_not_upscaled(self) -> None:
        """Test that small images are not upscaled."""
        data = _create_test_image(width=64, height=64)
        result = await thumbnails.generate_thumbnail(data)

        img = PIL.Image.open(io.BytesIO(result))
        self.assertEqual(img.width, 64)
        self.assertEqual(img.height, 64)
