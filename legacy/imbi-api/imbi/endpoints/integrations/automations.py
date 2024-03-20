from __future__ import annotations

import datetime
import enum
import http.client
import inspect
import typing

import jsonpatch
import psycopg2.errors
import pydantic
import sprockets_postgres
from psycopg2 import extensions

from imbi import automations, errors, postgres, slugify
from imbi.endpoints import base


class AutomationCategory(enum.Enum):
    CREATE_PROJECT = 'create-project'


def verify_legal_callable(v):
    if not inspect.iscoroutinefunction(v):
        name = getattr(v, '__name__', repr(v))
        raise ValueError(f'{name} is not a coroutine function')

    mod_name = inspect.getmodule(v).__name__
    allow_list = {'imbi.automations'}
    if (mod_name in allow_list
            or any(mod_name.startswith(a + '.') for a in allow_list)):
        return v
    raise ValueError(f'{mod_name!r} is not an allowed implementation module')


CallableType = typing.Annotated[pydantic.ImportString,
                                pydantic.AfterValidator(verify_legal_callable),
                                pydantic.Field(default=automations.do_nothing)]
PathIdType: typing.TypeAlias = typing.Union[int, slugify.Slug]


class AddAutomationRequest(pydantic.BaseModel):
    name: str
    categories: list[AutomationCategory] = pydantic.Field(min_length=1)
    callable: CallableType
    applies_to: list[PathIdType] = pydantic.Field(default_factory=list,
                                                  min_length=1)
    depends_on: list[PathIdType] = pydantic.Field(default_factory=list)


class Automation(pydantic.BaseModel):
    id: int
    name: str
    slug: slugify.Slug
    integration_name: str
    callable: CallableType
    categories: list[AutomationCategory] = pydantic.Field(min_length=1)
    applies_to: list[slugify.Slug] = pydantic.Field(default_factory=list,
                                                    min_length=1)
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
    NAME = 'automations'  # used in metrics

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
            parameters={'integration_name': integration_name},
            metric_name='get-automations')
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
                },
                metric_name='create-automation')
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
    NAME = 'automation'  # used in metrics

    def _add_self_link(self, _path: str) -> None:
        pass  # this stops base.RequestHandler from making assumptions

    async def get(self, integration_name: str, slug: str) -> None:
        automation = await self._find_automation(integration_name, slug)
        if not automation:
            raise errors.ItemNotFound(instance=self.request.uri)

        path = self.reverse_url('automation', automation.integration_name,
                                automation.slug)
        self.add_header(
            'link',
            f'<{self.request.protocol}://{self.request.host}{path}>;'
            f' rel="self"',
        )
        self.send_response(automation)

    @base.require_permission('admin')
    async def delete(self, integration_name: str, slug: str) -> None:
        automation_id, automation_slug = slugify.decode_path_slug(slug)
        del slug  # use either automation_id or automation_slug

        result = await self.postgres_execute(
            'DELETE FROM v1.automations'
            ' WHERE integration_name = %(integration_name)s'
            '   AND (id = %(automation_id)s'
            '        OR slug = %(automation_slug)s'
            '        OR name = %(automation_slug)s)', {
                'automation_id': automation_id,
                'automation_slug': automation_slug,
                'integration_name': integration_name,
            },
            metric_name='delete-automation')
        if not result.row_count:
            raise errors.ItemNotFound(instance=self.request.uri)
        self.set_status(204, reason='Item Deleted')

    @base.require_permission('admin')
    async def patch(self, integration_name: str, slug: str) -> None:
        patch = jsonpatch.JsonPatch(self.get_request_body())
        automation = await self._find_automation(integration_name, slug)
        if not automation:
            raise errors.ItemNotFound(instance=self.request.uri)

        original = automation.model_dump(mode='json')
        updated = patch.apply(original)
        if updated['id'] != original['id']:
            raise errors.BadRequest('Automation ID is immutable')

        project_type_map, automations_map = await self._get_maps(
            automation, updated)

        # map any IDs into slugs first since that is the real data model
        updated.update({
            'applies_to': project_type_map.to_slugs(updated['applies_to']),
            'depends_on': automations_map.to_slugs(updated['depends_on']),
            'last_modified_at': datetime.datetime.now(datetime.timezone.utc),
            'last_modified_by': self._current_user.username,
        })
        try:
            new_automation = Automation.model_validate(updated)
        except pydantic.ValidationError as error:
            raise errors.PydanticValidationError(
                error, 'Failed to validate new Automation') from None

        entity_updated = any(updated[column] != original[column]
                             for column in ('name', 'slug', 'integration_name',
                                            'callable', 'categories'))

        # figure out which association values we are adding and/or
        # removing... and map them to IDs while we are in there
        added_types, removed_types = _partition_map_and_set_changes(
            automation.applies_to, new_automation.applies_to, project_type_map)
        added_deps, removed_deps = _partition_map_and_set_changes(
            automation.depends_on, new_automation.depends_on, automations_map)

        # and now we can finally figure out if anything has changed
        if not any((entity_updated, added_types, removed_types, added_deps,
                    removed_deps)):
            self.set_status(http.client.NOT_MODIFIED)
            return

        async with self.postgres_transaction() as txn:
            txn: sprockets_postgres.PostgresConnector
            if entity_updated:
                await postgres.update_entity(
                    txn, 'v1', 'automations', original, updated,
                    ('name', 'slug', 'integration_name', 'callable',
                     'categories', 'last_modified_at', 'last_modified_by'))
            if added_deps:
                await postgres.insert_values(
                    txn, 'v1', 'automations_graph',
                    ['automation_id', 'dependency_id'],
                    [(automation.id, dependency) for dependency in added_deps])
            if removed_deps:
                await txn.execute(
                    'DELETE FROM v1.automations_graph'
                    '      WHERE automation_id = %(automation_id)s'
                    '        AND dependency_id IN %(removed_deps)s', {
                        'automation_id': automation.id,
                        'removed_deps': tuple(removed_deps)
                    },
                    metric_name='delete-automations_graph')
            if added_types:
                await postgres.insert_values(
                    txn, 'v1', 'available_automations',
                    ['automation_id', 'project_type_id'],
                    [(automation.id, pt_id) for pt_id in added_types])
            if removed_types:
                await txn.execute(
                    'DELETE FROM v1.available_automations'
                    '      WHERE automation_id = %(automation_id)s'
                    '        AND project_type_id IN %(removed_types)s', {
                        'automation_id': automation.id,
                        'removed_types': tuple(removed_types)
                    },
                    metric_name='delete-available_automations')

        automation = await self._find_automation(integration_name, slug)
        self.send_response(automation)

    def on_postgres_error(self, metric_name: str,
                          exc: Exception) -> typing.Optional[Exception]:
        """Handle postgres exceptions

        Stop exceptions that are not handled in sprockets_postgres
        from becoming "internal server errors". we don't want a bad
        patch to be retried by a client.

        """
        self.logger.exception('unexpected error')
        if isinstance(exc, psycopg2.errors.NotNullViolation):
            sanitized = exc.pgerror.removeprefix('ERROR:').splitlines()[0]
            return errors.BadRequest(
                'Request generated an invalid result: %s',
                str(exc).replace('\n', ' '),
                title='Invalid update',
                reason='Bad Request',
                detail=sanitized.strip(),
                sqlstate=exc.pgcode,
            )
        if isinstance(exc, psycopg2.errors.CheckViolation):
            sanitized = exc.pgerror.removeprefix('ERROR:').splitlines()[0]
            return errors.ApplicationError(
                http.HTTPStatus.CONFLICT,
                'conflict',
                'Request violated relationship constraint: %s',
                str(exc).replace('\n', ' '),
                title='Invalid update',
                reason='Conflict',
                detail=sanitized.strip(),
                sqlstate=exc.pgcode,
            )
        return super().on_postgres_error(metric_name, exc)

    async def _find_automation(self, integration_name: str,
                               slug: str) -> Automation | None:
        """Retrieve a single automation from the DB

        The `slug` can be a slug, the name of the automation,
        or the automation's surrogate ID.

        """
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
            '   AND (a.slug = %(slug)s'
            '        OR a.id = %(automation_id)s'
            '        OR a.name = %(slug)s)'
            ' GROUP BY a.id, a.name, a.callable, a.categories, a.slug,'
            '          a.integration_name', {
                'automation_id': automation_id,
                'slug': automation_slug,
                'integration_name': integration_name,
            },
            metric_name='get-automation')
        if result.row:
            try:
                automation = Automation.model_validate(result.row)
            except pydantic.ValidationError as error:
                raise errors.PydanticValidationError(
                    error,
                    'Database contains an invalid automation with id %r: %s',
                    result.row['id'],
                    error,
                    status_code=500)
            self.logger.debug('found %s (%s)', automation.slug, automation.id)
            return automation
        return None

    async def _get_maps(
            self, automation: Automation, updated: dict
    ) -> tuple[slugify.IdSlugMapping, slugify.IdSlugMapping]:
        async with self.application.postgres_connector(
                self.on_postgres_error, self.on_postgres_timing) as conn:
            values = set(automation.applies_to)
            values.update(updated.get('applies_to', []))
            project_type_map = await slugify.IdSlugMapping.from_database(
                conn, 'v1', 'project_types', values)

            values = set(automation.depends_on)
            values.update(updated.get('depends_on', []))
            automations_map = await slugify.IdSlugMapping.from_database(
                conn, 'v1', 'automations', values)

        return project_type_map, automations_map


def _partition_map_and_set_changes(
        start_data: list[str], final_data: list[str],
        mapping: slugify.IdSlugMapping) -> tuple[list[int], list[int]]:
    """Take original & changed collections and return added & removed sets"""
    start_set, final_set = set(start_data), set(final_data)
    return (mapping.to_ids(final_set - start_set),
            mapping.to_ids(start_set - final_set))
