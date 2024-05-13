from __future__ import annotations

import datetime
import enum
import inspect
import logging
import typing

import pydantic

from . import do_nothing
from imbi import errors, slugify

if typing.TYPE_CHECKING:
    from imbi import app

__all__ = [
    'Automation',
    'AutomationCategory',
    'automation',
    'Integration',
    'integration',
]

LOGGER = logging.getLogger(__name__)


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
                                pydantic.Field(default=do_nothing)]
PathIdType: typing.TypeAlias = typing.Union[int, slugify.Slug]


class AutomationCategory(enum.Enum):
    CREATE_PROJECT = 'create-project'


class Automation(pydantic.BaseModel):
    id: int
    name: str
    slug: slugify.Slug
    integration_name: str
    callable: CallableType
    categories: list[AutomationCategory] = pydantic.Field(min_length=1)
    applies_to: list[slugify.Slug] = pydantic.Field(default_factory=list,
                                                    min_length=1)
    applies_to_ids: list[int] = pydantic.Field(default_factory=list,
                                               min_length=1,
                                               exclude=True)
    depends_on: list[slugify.Slug] = pydantic.Field(default_factory=list)
    depends_on_ids: list[int] = pydantic.Field(default_factory=list,
                                               exclude=True)
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

    @pydantic.field_validator('applies_to',
                              'applies_to_ids',
                              'depends_on',
                              'depends_on_ids',
                              mode='before')
    @classmethod
    def handle_postgres_null_arrays(cls,
                                    value) -> list[slugify.Slug] | list[int]:
        """Adjust for postgres array values...

        The `array_agg()` function has some interesting behavior
        when mixed with `LEFT JOIN` like returning an array of
        `NULL` values when there is not a match. Other references
        can cause the array itself to be `NULL`. In our specific
        use case, we always want an array, and it should never
        contain `None`.

        """
        return [v for v in value if v is not None and v is not None]


class Integration(pydantic.BaseModel):
    name: str
    api_endpoint: pydantic.HttpUrl
    api_secret: typing.Union[str, None] = None
    created_at: datetime.datetime
    created_by: str
    last_modified_at: typing.Union[datetime.datetime, None] = None
    last_modified_by: typing.Union[str, None] = None


async def automation(automation_slug: str,
                     application: 'app.Application') -> Automation | None:
    def on_postgres_error(_metric_name: str, exc: Exception) -> None:
        LOGGER.error('Failed to execute query for automation %s: %s',
                     automation_slug, exc)
        raise errors.DatabaseError('Error loading Automation', error=exc)

    async with application.postgres_connector(
            on_error=on_postgres_error) as conn:
        result = await conn.execute(
            'SELECT a.id, a.name, a.slug, a.integration_name, a.callable,'
            '       a.categories, a.created_at, a.created_by,'
            '       a.last_modified_at, a.last_modified_by,'
            '       array_agg(DISTINCT pt.slug) AS applies_to,'
            '       array_agg(DISTINCT d.slug) AS depends_on,'
            '       array_agg(DISTINCT pt.id) AS applies_to_ids,'
            '       array_agg(DISTINCT d.id) AS depends_on_ids'
            '  FROM      v1.automations AS a'
            '  LEFT JOIN v1.available_automations AS aa'
            '         ON aa.automation_id = a.id'
            '  LEFT JOIN v1.project_types AS pt ON pt.id = aa.project_type_id'
            '  LEFT JOIN v1.automations_graph AS g ON g.automation_id = a.id'
            '  LEFT JOIN v1.automations AS d ON d.id = g.dependency_id'
            ' WHERE a.slug = %(automation_slug)s'
            ' GROUP BY a.id, a.name, a.callable, a.categories, a.slug,'
            '          a.integration_name, a.created_at, a.created_by,'
            '          a.last_modified_at, a.last_modified_by',
            {'automation_slug': automation_slug})
        if result.row_count:
            return Automation.model_validate(result.row)


async def integration(integration_name: str,
                      application: 'app.Application') -> Integration | None:
    def on_postgres_error(_metric_name: str, exc: Exception) -> None:
        LOGGER.error('Failed to execute query for integration %s: %s',
                     integration_name, exc)
        raise errors.DatabaseError('Error loading Integration', error=exc)

    async with application.postgres_connector(
            on_error=on_postgres_error) as conn:
        result = await conn.execute(
            'SELECT i.name, i.api_endpoint, i.api_secret, i.created_at,'
            '       i.created_by, i.last_modified_at, i.last_modified_by'
            '  FROM v1.integrations AS i'
            ' WHERE i.name = %(integration_name)s',
            {'integration_name': integration_name},
            metric_name='get-integration')
        if result.row_count:
            return Integration.model_validate(result.row)
