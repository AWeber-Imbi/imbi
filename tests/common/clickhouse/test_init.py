import enum
import unittest
from unittest import mock

import pydantic

from imbi_common import clickhouse


class SampleModel(pydantic.BaseModel):
    """Sample model for insert operations."""

    id: int
    name: str
    active: bool


class SampleModelWithNested(pydantic.BaseModel):
    """Sample model with nested list fields."""

    id: int
    evidence: list[dict]


class SampleModelDifferent(pydantic.BaseModel):
    """Different sample model for type validation."""

    value: str


class SampleEnum(enum.Enum):
    """Sample enum for value extraction."""

    OPTION_A = 'a'
    OPTION_B = 'b'


class DumpTestCase(unittest.TestCase):
    def test_dump_simple_model(self) -> None:
        """Test dumping a simple model."""
        model = SampleModel(id=1, name='test', active=True)
        result = clickhouse._dump(model)

        self.assertEqual(result, {'id': 1, 'name': 'test', 'active': True})

    def test_dump_model_with_enum(self) -> None:
        """Test dumping model with enum value."""

        class ModelWithEnum(pydantic.BaseModel):
            id: int
            status: SampleEnum

        model = ModelWithEnum(id=1, status=SampleEnum.OPTION_A)
        result = clickhouse._dump(model)

        self.assertEqual(result, {'id': 1, 'status': 'a'})

    def test_dump_model_with_nested_dicts(self) -> None:
        """Test dumping model with nested dictionaries."""
        model = SampleModelWithNested(
            id=1,
            evidence=[
                {'type': 'text', 'snippet': 'hello'},
                {'type': 'link', 'snippet': 'world'},
            ],
        )
        result = clickhouse._dump(model)

        self.assertEqual(result['id'], 1)
        self.assertEqual(result['evidence.type'], ['text', 'link'])
        self.assertEqual(result['evidence.snippet'], ['hello', 'world'])

    def test_dump_model_with_empty_list(self) -> None:
        """Test dumping model with empty list."""
        model = SampleModelWithNested(id=1, evidence=[])
        result = clickhouse._dump(model)

        self.assertEqual(result, {'id': 1, 'evidence': []})

    def test_dump_model_with_simple_list(self) -> None:
        """Test dumping model with simple list."""

        class ModelWithList(pydantic.BaseModel):
            id: int
            tags: list[str]

        model = ModelWithList(id=1, tags=['tag1', 'tag2', 'tag3'])
        result = clickhouse._dump(model)

        self.assertEqual(result, {'id': 1, 'tags': ['tag1', 'tag2', 'tag3']})


class DumpsTestCase(unittest.TestCase):
    def test_dumps_returns_json_string(self) -> None:
        """Test dumps returns JSON string."""
        model = SampleModel(id=1, name='test', active=True)
        result = clickhouse._dumps(model)

        self.assertIsInstance(result, str)
        self.assertIn('"id":1', result)
        self.assertIn('"name":"test"', result)
        self.assertIn('"active":true', result)


class ProcessNestedDictsTestCase(unittest.TestCase):
    def test_process_nested_dicts_basic(self) -> None:
        """Test processing nested dictionaries."""
        result = {}
        field_value = [
            {'type': 'text', 'snippet': 'hello'},
            {'type': 'link', 'snippet': 'world'},
        ]

        clickhouse._process_nested_dicts(result, 'evidence', field_value)

        self.assertEqual(result['evidence.type'], ['text', 'link'])
        self.assertEqual(result['evidence.snippet'], ['hello', 'world'])

    def test_process_nested_dicts_with_missing_keys(self) -> None:
        """Test processing nested dicts with missing keys in some items."""
        result = {}
        field_value = [
            {'type': 'text', 'snippet': 'hello', 'extra': 'data'},
            {'type': 'link', 'snippet': 'world'},  # Missing 'extra'
        ]

        clickhouse._process_nested_dicts(result, 'evidence', field_value)

        self.assertEqual(result['evidence.type'], ['text', 'link'])
        self.assertEqual(result['evidence.snippet'], ['hello', 'world'])
        self.assertEqual(
            result['evidence.extra'], ['data', '']
        )  # Default empty string

    def test_process_nested_dicts_with_enum_values(self) -> None:
        """Test processing nested dicts with enum values."""
        result = {}
        field_value = [
            {'status': SampleEnum.OPTION_A},
            {'status': SampleEnum.OPTION_B},
        ]

        clickhouse._process_nested_dicts(result, 'items', field_value)

        self.assertEqual(result['items.status'], ['a', 'b'])


class InitializeTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        clickhouse.client.Clickhouse._instance = None

    async def test_initialize(self) -> None:
        """Test initialize calls client initialize."""
        mock_ch = mock.AsyncMock()
        mock_ch.initialize.return_value = True

        with mock.patch.object(
            clickhouse.client.Clickhouse,
            'get_instance',
            return_value=mock_ch,
        ):
            result = await clickhouse.initialize()

        self.assertTrue(result)
        mock_ch.initialize.assert_called_once()


class AcloseTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        clickhouse.client.Clickhouse._instance = None

    async def test_aclose(self) -> None:
        """Test aclose calls client aclose."""
        mock_ch = mock.AsyncMock()

        with mock.patch.object(
            clickhouse.client.Clickhouse,
            'get_instance',
            return_value=mock_ch,
        ):
            await clickhouse.aclose()

        mock_ch.aclose.assert_called_once()


class InsertTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        clickhouse.client.Clickhouse._instance = None

    async def test_insert_success(self) -> None:
        """Test successful insert operation."""
        mock_ch = mock.AsyncMock()
        mock_summary = mock.MagicMock()
        mock_ch.insert.return_value = mock_summary

        data = [
            SampleModel(id=1, name='test1', active=True),
            SampleModel(id=2, name='test2', active=False),
        ]

        with mock.patch.object(
            clickhouse.client.Clickhouse,
            'get_instance',
            return_value=mock_ch,
        ):
            result = await clickhouse.insert('test_table', data)

        self.assertEqual(result, mock_summary)
        mock_ch.insert.assert_called_once()

        call_args = mock_ch.insert.call_args
        self.assertEqual(call_args[0][0], 'test_table')
        self.assertEqual(
            call_args[0][1], [[1, 'test1', True], [2, 'test2', False]]
        )
        self.assertEqual(call_args[0][2], ['id', 'name', 'active'])

    async def test_insert_empty_data(self) -> None:
        """Test insert with empty data list raises ValueError."""
        mock_ch = mock.AsyncMock()

        with mock.patch.object(
            clickhouse.client.Clickhouse,
            'get_instance',
            return_value=mock_ch,
        ):
            with self.assertRaises(ValueError) as cm:
                await clickhouse.insert('test_table', [])

        self.assertIn('cannot be empty', str(cm.exception))

    async def test_insert_mixed_types(self) -> None:
        """Test insert with mixed model types raises ValueError."""
        mock_ch = mock.AsyncMock()

        data = [
            SampleModel(id=1, name='test', active=True),
            SampleModelDifferent(value='different'),
        ]

        with mock.patch.object(
            clickhouse.client.Clickhouse,
            'get_instance',
            return_value=mock_ch,
        ):
            with self.assertRaises(ValueError) as cm:
                await clickhouse.insert('test_table', data)

        self.assertIn('same type', str(cm.exception))
        self.assertIn('SampleModel', str(cm.exception))

    async def test_insert_single_model(self) -> None:
        """Test insert with single model."""
        mock_ch = mock.AsyncMock()
        mock_summary = mock.MagicMock()
        mock_ch.insert.return_value = mock_summary

        data = [SampleModel(id=1, name='test', active=True)]

        with mock.patch.object(
            clickhouse.client.Clickhouse,
            'get_instance',
            return_value=mock_ch,
        ):
            result = await clickhouse.insert('test_table', data)

        self.assertEqual(result, mock_summary)
        call_args = mock_ch.insert.call_args
        self.assertEqual(call_args[0][1], [[1, 'test', True]])


class QueryTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        clickhouse.client.Clickhouse._instance = None

    async def test_query_success(self) -> None:
        """Test successful query operation."""
        mock_ch = mock.AsyncMock()
        expected_result = [
            {'id': 1, 'name': 'test1'},
            {'id': 2, 'name': 'test2'},
        ]
        mock_ch.query.return_value = expected_result

        with mock.patch.object(
            clickhouse.client.Clickhouse,
            'get_instance',
            return_value=mock_ch,
        ):
            result = await clickhouse.query(
                'SELECT * FROM test WHERE id = {id}', {'id': 123}
            )

        self.assertEqual(result, expected_result)
        mock_ch.query.assert_called_once_with(
            'SELECT * FROM test WHERE id = {id}', parameters={'id': 123}
        )

    async def test_query_without_parameters(self) -> None:
        """Test query without parameters."""
        mock_ch = mock.AsyncMock()
        expected_result = [{'count': 42}]
        mock_ch.query.return_value = expected_result

        with mock.patch.object(
            clickhouse.client.Clickhouse,
            'get_instance',
            return_value=mock_ch,
        ):
            result = await clickhouse.query(
                'SELECT COUNT(*) as count FROM test'
            )

        self.assertEqual(result, expected_result)
        mock_ch.query.assert_called_once_with(
            'SELECT COUNT(*) as count FROM test', parameters=None
        )


class SchemataQueryModelTestCase(unittest.TestCase):
    def test_schemata_query_model(self) -> None:
        """Test SchemataQuery model is accessible from module."""
        query = clickhouse.SchemataQuery(
            name='test', query='SELECT 1', enabled=True
        )
        self.assertEqual(query.name, 'test')
        self.assertEqual(query.query, 'SELECT 1')
        self.assertTrue(query.enabled)
