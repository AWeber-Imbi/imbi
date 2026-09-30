"""Tests for ``imbi.common.db.repository``."""

import pydantic
from psycopg import sql

from imbi.common.db import repository
from libraries.common.tests.db import support


class Tag(pydantic.BaseModel):
    id: str
    organization_id: str
    name: str
    slug: str


class TagRepository(repository.Repository):
    async def create(self, tag: Tag) -> int:
        return await self._execute(
            'INSERT INTO tags (id, organization_id, name, slug)'
            ' VALUES (%(id)s, %(organization_id)s, %(name)s, %(slug)s)',
            tag.model_dump(),
        )

    async def get(self, slug: str) -> Tag | None:
        return await self._one(
            Tag,
            'SELECT id, organization_id, name, slug FROM tags WHERE slug = %s',
            (slug,),
        )

    async def list_tags(self, order_by: str) -> list[Tag]:
        query = sql.SQL(
            'SELECT id, organization_id, name, slug FROM tags'
            ' WHERE organization_id = %s ORDER BY {}'
        ).format(sql.Identifier(order_by))
        return await self._many(
            Tag, query, (self._transaction.organization_id,)
        )

    async def delete(self, slug: str) -> int:
        return await self._execute('DELETE FROM tags WHERE slug = %s', (slug,))


class RepositoryTestCase(support.DatabaseTestCase):
    def tag(self, name: str) -> Tag:
        return Tag(
            id=support.new_id('tag'),
            organization_id=self.seed.org_a,
            name=name,
            slug=name.lower(),
        )

    async def test_round_trip(self) -> None:
        beta, alpha = self.tag('Beta'), self.tag('Alpha')
        async with self.database.transaction(self.seed.org_a) as tx:
            tags = TagRepository(tx)
            self.assertEqual(1, await tags.create(beta))
            self.assertEqual(1, await tags.create(alpha))
            await tx.commit()

        async with self.database.transaction(self.seed.org_a) as tx:
            tags = TagRepository(tx)
            self.assertEqual(alpha, await tags.get('alpha'))
            self.assertIsNone(await tags.get('gamma'))
            self.assertEqual([alpha, beta], await tags.list_tags('name'))
            self.assertEqual(1, await tags.delete('beta'))
            self.assertEqual(0, await tags.delete('beta'))

    async def test_other_organization_sees_nothing(self) -> None:
        async with self.database.transaction(self.seed.org_a) as tx:
            await TagRepository(tx).create(self.tag('Alpha'))
            await tx.commit()
        async with self.database.transaction(self.seed.org_b) as tx:
            tags = TagRepository(tx)
            self.assertIsNone(await tags.get('alpha'))
            self.assertEqual([], await tags.list_tags('name'))
