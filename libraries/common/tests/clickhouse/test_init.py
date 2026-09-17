import enum
import unittest
from unittest import mock

import pydantic

from imbi.common import clickhouse


class SampleModel(pydantic.BaseModel):
    """Sample model for insert operations."""

    id: int
    name: str
    active: bool


class SampleModelWithNested(pydantic.BaseModel):
    """Sample model with nested list fields."""

    id: int
    evidence: list[dict]


class SampleModelWithAlias(pydantic.BaseModel):
    """Model exercising Pydantic field aliases."""

    model_config = pydantic.ConfigDict(populate_by_name=True)

    id: int
    row_version: int = pydantic.Field(default=1, alias='_row_version')


class SampleEvidence(pydantic.BaseModel):
    """Nested Pydantic model for Nested-column tests."""

    type: str
    snippet: str


class SampleModelWithNestedModels(pydantic.BaseModel):
    """Model with list[BaseModel] targeting a ClickHouse Nested column."""

    id: int
    evidence: list[SampleEvidence]


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


class DumpRowShapeTestCase(unittest.TestCase):
    """`_dump` renders the row the Iggy payload and the sink rely on."""

    def test_uses_field_aliases(self) -> None:
        row = clickhouse._dump(SampleModelWithAlias(id=1, row_version=7))
        self.assertEqual({'id': 1, '_row_version': 7}, row)

    def test_flattens_nested_models(self) -> None:
        row = clickhouse._dump(
            SampleModelWithNestedModels(
                id=1,
                evidence=[
                    SampleEvidence(type='text', snippet='hello'),
                    SampleEvidence(type='link', snippet='world'),
                ],
            )
        )
        self.assertNotIn('evidence', row)
        self.assertEqual(['text', 'link'], row['evidence.type'])
        self.assertEqual(['hello', 'world'], row['evidence.snippet'])


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
