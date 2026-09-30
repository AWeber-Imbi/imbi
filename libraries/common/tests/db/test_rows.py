"""Tests for ``imbi.common.db.rows``."""

import datetime
import enum
import typing

import pydantic

from imbi.common.db import rows
from libraries.common.tests.db import support


class Analytics(enum.StrEnum):
    enabled = 'enabled'
    authors_only = 'authors_only'
    disabled = 'disabled'


class TagFormat(pydantic.BaseModel):
    label: str
    pattern: str


class Owner(pydantic.BaseModel):
    team: str
    contacts: list[str]


class Attributes(pydantic.BaseModel):
    owner: Owner
    tier: int


class Organization(pydantic.BaseModel):
    id: str
    slug: str
    tag_formats: list[TagFormat]
    attributes: Attributes
    document_analytics_identities: Analytics
    created_at: datetime.datetime
    updated_at: datetime.datetime | None


_SELECT: typing.LiteralString = (
    'SELECT id, slug, tag_formats, attributes,'
    ' document_analytics_identities, created_at, updated_at'
    ' FROM organizations WHERE id = %s'
)


class RowToModelTestCase(support.DatabaseTestCase):
    """A row of ``organizations``, read as ``imbi_app``, into a model."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with await support.maintenance() as conn:
            await conn.execute(
                'UPDATE organizations SET tag_formats = %s::jsonb,'
                ' attributes = %s::jsonb,'
                " document_analytics_identities = 'disabled'"
                ' WHERE id = %s',
                (
                    '[{"label": "Semver", "pattern": "^v"}]',
                    '{"owner": {"team": "core", "contacts": ["a", "b"]},'
                    ' "tier": 2}',
                    self.seed.org_a,
                ),
            )

    async def fetch_row(self) -> dict[str, typing.Any]:
        async with self.database.transaction(self.seed.org_a) as tx:
            cursor = await tx.connection.execute(_SELECT, (self.seed.org_a,))
            row = await cursor.fetchone()
        assert row is not None
        return row

    async def test_nested_jsonb(self) -> None:
        model = rows.row_to_model(Organization, await self.fetch_row())
        self.assertEqual(
            [TagFormat(label='Semver', pattern='^v')], model.tag_formats
        )
        self.assertEqual(
            Owner(team='core', contacts=['a', 'b']), model.attributes.owner
        )
        self.assertEqual(2, model.attributes.tier)

    async def test_timestamps(self) -> None:
        model = rows.row_to_model(Organization, await self.fetch_row())
        self.assertIsNotNone(model.created_at.tzinfo)
        self.assertLess(
            abs(datetime.datetime.now(datetime.UTC) - model.created_at),
            datetime.timedelta(minutes=5),
        )
        # The UPDATE fired the set_updated_at trigger.
        self.assertIsNotNone(model.updated_at)
        assert model.updated_at is not None
        self.assertGreaterEqual(model.updated_at, model.created_at)

    async def test_enum(self) -> None:
        model = rows.row_to_model(Organization, await self.fetch_row())
        self.assertIs(Analytics.disabled, model.document_analytics_identities)

    async def test_invalid_row_raises(self) -> None:
        # No model_construct fallback: a value that the model does not
        # accept is an error.
        class Narrow(pydantic.BaseModel):
            document_analytics_identities: typing.Literal['enabled']

        with self.assertRaises(pydantic.ValidationError):
            rows.row_to_model(Narrow, await self.fetch_row())
