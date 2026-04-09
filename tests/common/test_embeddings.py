"""Tests for the embeddings module."""

import unittest
from unittest import mock

from imbi_common import settings
from imbi_common.graph import embeddings


class EmbeddingsRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        embeddings.close()

    def tearDown(self) -> None:
        embeddings.close()

    def test_get_dimensions(self) -> None:
        dims = embeddings.get_dimensions('text')
        self.assertEqual(384, dims)

    def test_unknown_model_raises(self) -> None:
        with self.assertRaises(KeyError):
            embeddings.get_dimensions('nonexistent')

    def test_close_clears_cache(self) -> None:
        embeddings._registry = {
            'text': settings.EmbeddingModelConfig(
                fastembed_id='test',
                dimensions=10,
            ),
        }
        embeddings.close()
        self.assertIsNone(embeddings._registry)
        self.assertEqual({}, embeddings._models)


class EmbedSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        embeddings.close()

    def tearDown(self) -> None:
        embeddings.close()

    @mock.patch('imbi_common.graph.embeddings.fastembed.TextEmbedding')
    def test_embed_calls_model(
        self,
        mock_cls: mock.MagicMock,
    ) -> None:
        import numpy as np

        fake_model = mock.MagicMock()
        fake_model.embed.return_value = [
            np.array([0.1, 0.2, 0.3]),
        ]
        mock_cls.return_value = fake_model

        result = embeddings.embed(['hello'], 'text')
        self.assertEqual(1, len(result))
        self.assertAlmostEqual(0.1, result[0][0], places=5)
        fake_model.embed.assert_called_once_with(['hello'])

    @mock.patch('imbi_common.graph.embeddings.fastembed.TextEmbedding')
    def test_embed_batch(
        self,
        mock_cls: mock.MagicMock,
    ) -> None:
        import numpy as np

        fake_model = mock.MagicMock()
        fake_model.embed.return_value = [
            np.array([0.1, 0.2]),
            np.array([0.3, 0.4]),
        ]
        mock_cls.return_value = fake_model

        result = embeddings.embed(['a', 'b'], 'text')
        self.assertEqual(2, len(result))

    def test_unknown_model_raises(self) -> None:
        with self.assertRaises(KeyError):
            embeddings.embed(['test'], 'nonexistent')

    @mock.patch('imbi_common.graph.embeddings.fastembed.TextEmbedding')
    def test_model_cached(
        self,
        mock_cls: mock.MagicMock,
    ) -> None:
        import numpy as np

        fake_model = mock.MagicMock()
        fake_model.embed.return_value = [
            np.array([0.1]),
        ]
        mock_cls.return_value = fake_model

        embeddings.embed(['a'], 'text')
        embeddings.embed(['b'], 'text')
        # TextEmbedding constructor called only once
        mock_cls.assert_called_once()


class EmbedAsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        embeddings.close()

    def tearDown(self) -> None:
        embeddings.close()

    @mock.patch('imbi_common.graph.embeddings.fastembed.TextEmbedding')
    async def test_aembed_one(
        self,
        mock_cls: mock.MagicMock,
    ) -> None:
        import numpy as np

        fake_model = mock.MagicMock()
        fake_model.embed.return_value = [
            np.array([0.5, 0.6]),
        ]
        mock_cls.return_value = fake_model

        result = await embeddings.aembed_one('test', 'text')
        self.assertEqual(2, len(result))
        self.assertAlmostEqual(0.5, result[0], places=5)
