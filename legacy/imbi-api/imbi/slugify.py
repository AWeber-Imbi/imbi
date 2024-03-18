from __future__ import annotations

import collections.abc
import re
import typing

import pydantic
import sprockets_postgres
from psycopg2 import sql

from imbi import errors

Slug = typing.Annotated[str,
                        pydantic.StringConstraints(
                            pattern=r'^[a-z0-9][-_a-z0-9]*[a-z0-9]?$',
                            min_length=1,
                        )]


class InvalidSlugError(errors.BadRequest):
    def __init__(self, slug_type: str, invalid_slugs: set[int | str]) -> None:
        super().__init__('Invalid %s slug(s): %r',
                         slug_type,
                         invalid_slugs,
                         invalid_slugs=sorted(invalid_slugs))


def path_element(value: str) -> str:
    """Generate a slug for an arbitrary string"""
    value = re.sub(r'[\s_]+', '-', value)
    value = re.sub(r'[^-a-z0-9]', '', value.lower())
    return Slug(value.strip('-_'))


def decode_path_slug(slug_or_id: str) -> tuple[int | None] | tuple[None | str]:
    """Decode a path parameter as either an integer or a slug

    :returns: a tuple of (int, str) where only one of the values
        is not `None`

    """
    id_value: int | None = None
    slug_value: str | None = slug_or_id
    try:
        id_value = int(slug_or_id, 10)
        slug_value = None
    except ValueError:
        pass
    return id_value, slug_value


class IdSlugMapping:
    """Maps between IDs and slugs"""
    def __init__(self, slug_to_id: dict[str, int] | None = None) -> None:
        self._slug_to_id: dict[str, int] = {}
        if slug_to_id:
            self._slug_to_id.update(slug_to_id)
        self._id_to_slug = {v: k for k, v in self._slug_to_id.items()}

    def to_ids(self, values: collections.abc.Iterable[str | int]) -> list[int]:
        """Map `values` to IDs

        This maps non-ID values to their associated ID while
        maintaining any IDs in `values`.

        """
        return [self._slug_to_id.get(v, v) for v in values]

    def to_slugs(self,
                 values: collections.abc.Iterable[str | int]) -> list[str]:
        """Map `values` to slugs

        This maps non-slug values to their associated slug
        while maintaining any slugs in `values`.

        """
        return [self._id_to_slug.get(v, v) for v in values]

    @property
    def ids(self) -> list[int]:
        """List of IDs"""
        return list(self._id_to_slug)

    @property
    def slugs(self) -> list[str]:
        """List of slugs"""
        return list(self._slug_to_id)

    @classmethod
    async def from_database(
            cls, conn: sprockets_postgres.PostgresConnector, schema: str,
            entity_table: str,
            filter_values: collections.abc.Collection[int | str]
    ) -> typing.Self:
        """Build a mapping based on the slug & id values in a table."""
        ids: tuple[int, ...] = ()
        slugs: tuple[str, ...] = ()
        params = {}
        query = sql.SQL('SELECT DISTINCT slug, id FROM {}').format(
            sql.Identifier(schema, entity_table))
        if filter_values:
            empty = (None, )
            ids = tuple(i for i in filter_values if isinstance(i, int))
            slugs = tuple(s for s in filter_values if isinstance(s, str))
            params.update({'ids': ids or empty, 'slugs': slugs or empty})
            query += sql.SQL('WHERE slug IN {} OR id IN {}').format(
                sql.Placeholder('slugs'), sql.Placeholder('ids'))
        result = await conn.execute(query,
                                    params,
                                    metric_name=f'fetch-{entity_table}-slugs')

        mapping = {row['slug']: row['id'] for row in result}
        invalid_values: set[int | str] = set(slugs) - set(mapping.keys())
        invalid_values.update(set(ids) - set(mapping.values()))
        if invalid_values:
            raise InvalidSlugError(entity_table, invalid_values)

        return cls(mapping)
