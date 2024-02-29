from __future__ import annotations

import datetime
import enum
import typing

import pydantic
import sprockets_postgres
from psycopg2 import extensions

from imbi import errors, postgres, slugify
from imbi.endpoints import base


# used as a default automation action
def do_nothing(*_args, **_kwargs):
    pass


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
                mapping = await slugify.IdSlugMapping.from_database(
                    conn, 'v1', 'project_types', request.applies_to)
                await postgres.insert_values(
                    conn, 'v1', 'available_automations',
                    ['automation_id', 'project_type_id'],
                    [(automation.id, value) for value in mapping.ids])
                automation.applies_to = sorted(mapping.slugs)

            if request.depends_on:
                mapping = await slugify.IdSlugMapping.from_database(
                    conn, 'v1', 'automations', request.depends_on)
                await postgres.insert_values(
                    conn, 'v1', 'automations_graph',
                    ['automation_id', 'dependency_id'],
                    [(automation.id, value) for value in mapping.ids])
                automation.depends_on = sorted(mapping.slugs)

            self.send_response(automation)


class RecordRequestHandler(base.PydanticHandlerMixin,
                           base.ValidatingRequestHandler):
    async def get(self, integration_name: str, slug: str) -> None:
        automation_id, automation_slug = slugify.decode_path_slug(slug)
        del slug  # use either automation_id or automation_slug

        self.logger.debug('looking for %r or %r', automation_id,
                          automation_slug)

        result = await self.postgres_execute(
            'SELECT a.id, a.name, a.callable, a.categories, a.slug,'
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
            '   AND (a.slug = %(slug)s OR a.id = %(automation_id)s)'
            ' GROUP BY a.id, a.name, a.callable, a.categories, a.slug,'
            '          a.integration_name', {
                'automation_id': automation_id,
                'slug': automation_slug,
                'integration_name': integration_name,
            })
        if not result:
            raise errors.ItemNotFound(instance=self.request.uri)

        self.send_response(Automation.model_validate(result.row))

    @base.require_permission('admin')
    async def delete(self, integration_name: str, slug: str) -> None:
        automation_id, automation_slug = slugify.decode_path_slug(slug)
        del slug  # use either automation_id or automation_slug

        result = await self.postgres_execute(
            'DELETE FROM v1.automations'
            ' WHERE integration_name = %(integration_name)s'
            '   AND (id = %(automation_id)s OR slug = %(automation_slug)s)', {
                'automation_id': automation_id,
                'automation_slug': automation_slug,
                'integration_name': integration_name,
            })
        if not result.row_count:
            raise errors.ItemNotFound(instance=self.request.uri)
        self.set_status(204, reason='Item Deleted')
