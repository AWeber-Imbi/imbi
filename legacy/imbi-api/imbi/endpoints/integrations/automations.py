from __future__ import annotations

import datetime
import enum
import typing

import psycopg2.sql
import pydantic
import sprockets_postgres
from psycopg2 import extensions

from imbi import errors, slugify
from imbi.endpoints import base


# used as a default automation action
def do_nothing(*_args, **_kwargs):
    pass


class InvalidSlugsError(errors.BadRequest):
    def __init__(self, slug_type: str, invalid_slugs: set[int | str]) -> None:
        super().__init__('Invalid %s slugs: %r',
                         slug_type,
                         invalid_slugs,
                         invalid_slugs=sorted(invalid_slugs))


async def _map_ids_and_slugs(conn: sprockets_postgres.PostgresConnector,
                             entity_type: str,
                             values: list[int | str]) -> dict[str, int]:
    slugs = tuple(s for s in values if isinstance(s, str))
    ids = tuple(i for i in values if isinstance(i, int))
    result = await conn.execute(
        f'SELECT DISTINCT slug, id'
        f'  FROM v1.{entity_type}'
        f' WHERE slug IN %(slugs)s'
        f'    OR id IN %(ids)s', {
            'slugs': slugs or (None, ),
            'ids': ids or (None, ),
        })
    mapping = {row['slug']: row['id'] for row in result}
    invalid_values: set[int | str] = set(slugs) - set(mapping.keys())
    invalid_values.update(set(ids) - set(mapping.values()))
    if invalid_values:
        raise InvalidSlugsError(entity_type, invalid_values)
    return mapping


class AutomationCategory(enum.Enum):
    CREATE_PROJECT = 'create-project'


PathIdType: typing.TypeAlias = typing.Union[int, slugify.Slug]


class AddAutomationRequest(pydantic.BaseModel):
    name: str
    categories: list[AutomationCategory] = pydantic.Field(min_items=1)
    callable: pydantic.ImportString = pydantic.Field(default=do_nothing)
    applies_to: list[PathIdType] = pydantic.Field(default_factory=list,
                                                  min_items=1)
    depends_on: list[PathIdType] = pydantic.Field(default_factory=list)


class Automation(pydantic.BaseModel):
    id: int
    name: str
    slug: slugify.Slug
    integration_name: str
    callable: pydantic.ImportString
    categories: list[AutomationCategory] = pydantic.Field(min_items=1)
    applies_to: list[slugify.Slug] = pydantic.Field(default_factory=list,
                                                    min_items=1)
    depends_on: list[slugify.Slug] = pydantic.Field(default_factory=list)
    created_by: str
    created_at: datetime.datetime
    last_modified_by: typing.Union[str, None] = None
    last_modified_at: typing.Union[datetime.datetime, None] = None

    @pydantic.field_validator('categories', mode='before')
    @classmethod
    def handle_postgres_array_syntax(cls, value) -> list[AutomationCategory]:
        if isinstance(value, str):
            return [AutomationCategory(v) for v in value[1:-1].split(',')]
        return value

    @pydantic.field_validator('applies_to', 'depends_on', mode='before')
    @classmethod
    def handle_postgres_null_arrays(cls, value) -> list[slugify.Slug]:
        return [v for v in value if v is not None]


def adapt_automation_category(category: AutomationCategory):
    return extensions.AsIs(repr(category.value))


extensions.register_adapter(AutomationCategory, adapt_automation_category)


class CollectionRequestHandler(base.PydanticHandlerMixin,
                               base.ValidatingRequestHandler):
    async def get(self, integration_name: str) -> None:
        result = await self.postgres_execute(
            'SELECT a.id, a.name, a.slug, a.callable, a.categories,'
            '       a.integration_name, a.created_at, a.created_by,'
            '       a.last_modified_at, a.last_modified_by,'
            '       array_agg(pt.slug) AS applies_to,'
            '       array_agg(d.slug) AS depends_on'
            '  FROM v1.automations AS a'
            '  LEFT JOIN v1.available_automations AS aa'
            '         ON aa.automation_id = a.id'
            '  LEFT JOIN v1.project_types AS pt ON pt.id = aa.project_type_id'
            '  LEFT JOIN v1.automations_graph AS g ON g.automation_id = a.id'
            '  LEFT JOIN v1.automations AS d ON d.id = g.dependency_id'
            ' WHERE a.integration_name = %(integration_name)s'
            ' GROUP BY a.id, a.name, a.slug, a.callable, a.categories,'
            '          a.integration_name, a.slug',
            parameters={'integration_name': integration_name})
        self.send_response([Automation.model_validate(row) for row in result])

    @base.require_permission('admin')
    async def post(self, integration_name: str) -> None:
        request = self.parse_request_body_as(AddAutomationRequest)
        slug = slugify.path_element(f'{integration_name}-{request.name}')
        if slug in request.depends_on:
            raise errors.BadRequest('Automation cannot depend on itself')

        self.logger.info('creating automation targeting %r', request.callable)

        async with self.postgres_transaction() as conn:
            conn: sprockets_postgres.PostgresConnector
            result = await conn.execute(
                'INSERT INTO v1.automations(name, slug, integration_name,'
                '                           callable, created_by, categories)'
                '     VALUES (%(name)s, %(slug)s, %(integration_name)s,'
                '             %(callable)s, %(username)s,'
                '             %(categories)s::v1.automation_category_type[])'
                '  RETURNING id, created_at',
                parameters={
                    **request.model_dump(mode='json'),
                    'integration_name': integration_name,
                    'slug': slug,
                    'username': self._current_user.username,
                })
            if not result.row_count:
                raise errors.DatabaseError('No rows returned from INSERT',
                                           title='Failed to insert record')

            automation = Automation(
                id=result.row['id'],
                name=request.name,
                slug=slug,
                callable=request.callable,
                categories=request.categories,
                integration_name=integration_name,
                created_at=result.row['created_at'],
                created_by=self._current_user.username,
            )

            if request.applies_to:
                mapping = await _map_ids_and_slugs(conn, 'project_types',
                                                   request.applies_to)
                query = psycopg2.sql.SQL(
                    'INSERT INTO v1.available_automations(automation_id,'
                    '                                     project_type_id)'
                    '     VALUES {}'.format(','.join(
                        conn.cursor.mogrify('(%s,%s)', (
                            automation.id, project_type_id)).decode()
                        for project_type_id in mapping.values())))
                await conn.execute(query)
                automation.applies_to = sorted(mapping.keys())

            if request.depends_on:
                mapping = await _map_ids_and_slugs(conn, 'automations',
                                                   request.depends_on)
                query = psycopg2.sql.SQL(
                    'INSERT INTO v1.automations_graph(automation_id,'
                    '                                 dependency_id)'
                    '     VALUES {}'.format(','.join(
                        conn.cursor.mogrify('(%s,%s)', (
                            automation.id, dependency_id)).decode()
                        for dependency_id in mapping.values())))
                await conn.execute(query)
                automation.depends_on = sorted(mapping.keys())

            self.send_response(automation)
