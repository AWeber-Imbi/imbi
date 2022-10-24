import asyncio
import dataclasses
import datetime
import decimal
import logging
import re
import typing

from imbi import common, errors
if typing.TYPE_CHECKING:
    from imbi import app

decimal.getcontext().prec = 2
LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass
class CookieCutter:
    name: str
    project_type_id: int
    url: str


@dataclasses.dataclass
class Namespace:
    id: int
    created_at: datetime.datetime
    created_by: str
    last_modified_at: str
    last_modified_by: typing.Optional[datetime.datetime]
    name: str
    slug: str
    icon_class: str
    maintained_by: typing.Optional[typing.List[str]]
    gitlab_group_name: str
    sentry_team_slug: typing.Optional[str]

    SQL: typing.ClassVar = re.sub(r'\s+', ' ', """\
        SELECT id,
               created_at,
               created_by,
               last_modified_at,
               last_modified_by,
               name,
               slug,
               icon_class,
               maintained_by,
               gitlab_group_name,
               sentry_team_slug
          FROM v1.namespaces
         WHERE id=%(id)s""")


@dataclasses.dataclass
class ProjectFact:
    id: int
    name: str
    recorded_at: datetime.datetime
    recorded_by: str
    value: typing.Union[
        bool,
        datetime.date,
        datetime.datetime,
        decimal.Decimal,
        int,
        None,
        str
    ]
    fact_type: str
    data_type: str
    description: typing.Optional[str]
    ui_options: typing.Optional[typing.List[str]]
    score: decimal.Decimal
    weight: int

    COLLECTION_SQL: typing.ClassVar = re.sub(r'\s+', ' ', """\
        WITH project_type_id AS (SELECT project_type_id AS id
                                   FROM v1.projects
                                  WHERE id = %(obj_id)s)
        SELECT a.id,
               a.name,
               b.recorded_at,
               b.recorded_by,
               b.value,
               a.fact_type,
               a.data_type,
               a.description,
               a.ui_options,
               CASE WHEN b.value IS NULL THEN 0
                    ELSE CASE WHEN a.fact_type = 'enum' THEN (
                                          SELECT score::NUMERIC(9,2)
                                            FROM v1.project_fact_type_enums
                                           WHERE fact_type_id = b.fact_type_id
                                             AND value = b.value)
                              WHEN a.fact_type = 'range' THEN (
                                          SELECT score::NUMERIC(9,2)
                                            FROM v1.project_fact_type_ranges
                                           WHERE fact_type_id = b.fact_type_id
                                             AND b.value::NUMERIC(9,2)
                                         BETWEEN min_value AND max_value)
                              ELSE 0
                          END
                END AS score,
               a.weight
          FROM v1.project_fact_types AS a
     LEFT JOIN v1.project_facts AS b
            ON b.fact_type_id = a.id
           AND b.project_id = %(obj_id)s
         WHERE (SELECT id FROM project_type_id) = ANY(a.project_type_ids)
      ORDER BY a.name""")

    def __post_init__(self):
        try:
            value = common.coerce_project_fact(self.data_type, self.value)
        except ValueError:
            pass
        else:
            self.__setattr__('value', value)


@dataclasses.dataclass
class ProjectType:
    id: int
    created_at: datetime.datetime
    created_by: str
    last_modified_at: typing.Optional[str]
    last_modified_by: typing.Optional[datetime.datetime]
    name: str
    slug: str
    plural_name: str
    description: typing.Optional[str]
    icon_class: typing.Optional[str]
    environment_urls: bool
    gitlab_project_prefix: typing.Optional[str]

    SQL: typing.ClassVar = re.sub(r'\s+', ' ', """\
        SELECT id,
               created_at,
               created_by,
               last_modified_at,
               last_modified_by,
               name,
               slug,
               plural_name,
               description,
               icon_class,
               environment_urls,
               gitlab_project_prefix
          FROM v1.project_types
         WHERE id=%(id)s""")


@dataclasses.dataclass
class ProjectLink:
    link_type_id: int
    link_type: str
    created_at: datetime.datetime
    created_by: str
    last_modified_at: typing.Optional[str]
    last_modified_by: typing.Optional[datetime.datetime]
    icon_class: typing.Optional[str]
    url: str

    COLLECTION_SQL: typing.ClassVar = re.sub(r'\s+', ' ', """\
        SELECT a.link_type_id,
               b.link_type,
               a.created_at,
               a.created_by,
               a.last_modified_at,
               a.last_modified_by,
               b.icon_class,
               a.url
          FROM v1.project_links AS a
          JOIN v1.project_link_types AS b
            ON b.id = a.link_type_id
         WHERE a.project_id = %(obj_id)s
         ORDER BY b.link_type""")


@dataclasses.dataclass
class ProjectURL:
    environment: str
    created_at: datetime.datetime
    created_by: str
    last_modified_at: typing.Optional[str]
    last_modified_by: typing.Optional[datetime.datetime]
    icon_class: typing.Optional[str]
    url: str

    COLLECTION_SQL: typing.ClassVar = re.sub(r'\s+', ' ', """\
        SELECT a.environment,
               a.created_at,
               a.created_by,
               a.last_modified_at,
               a.last_modified_by,
               b.icon_class,
               a.url
          FROM v1.project_urls AS a
          JOIN v1.environments AS b
            ON b.name = a.environment
         WHERE a.project_id = %(obj_id)s
         ORDER BY b.name""")


@dataclasses.dataclass
class Project:
    id: int
    created_at: datetime.datetime
    created_by: str
    last_modified_at: typing.Optional[datetime.datetime]
    last_modified_by: typing.Optional[str]
    namespace: Namespace
    project_type: ProjectType
    name: str
    slug: str
    description: typing.Optional[str]
    environments: typing.Optional[typing.List[str]]
    archived: bool
    gitlab_project_id: typing.Optional[int]
    sentry_project_slug: typing.Optional[str]
    sonarqube_project_key: typing.Optional[str]
    pagerduty_service_id: typing.Optional[str]
    facts: typing.Dict[str, str]
    links: typing.Dict[str, str]
    urls: typing.Dict[str, str]
    project_score: int

    SQL: typing.ClassVar = re.sub(r'\s+', ' ', """\
        SELECT id,
               created_at,
               created_by,
               last_modified_at,
               last_modified_by,
               namespace_id,
               project_type_id,
               name,
               slug,
               description,
               environments,
               archived,
               gitlab_project_id,
               sentry_project_slug,
               sonarqube_project_key,
               pagerduty_service_id,
               v1.project_score(id) AS project_score
          FROM v1.projects
         WHERE id=%(id)s""")


@dataclasses.dataclass
class OperationsLog:
    id: int
    recorded_at: datetime.datetime
    recorded_by: str
    completed_at: typing.Optional[datetime.datetime]
    project_id: typing.Optional[int]
    project_name: typing.Optional[str]
    environment: str
    change_type: str
    description: typing.Optional[str]
    link: typing.Optional[str]
    notes: typing.Optional[str]
    ticket_slug: typing.Optional[str]
    version: typing.Optional[str]

    SQL: typing.ClassVar = re.sub(r'\s+', ' ', """\
        SELECT a.id,
               a.recorded_at,
               a.recorded_by,
               a.completed_at,
               a.project_id,
               b.name AS project_name,
               a.environment,
               a.change_type,
               a.description,
               a.link,
               a.notes,
               a.ticket_slug,
               a.version
          FROM v1.operations_log AS a
     LEFT JOIN v1.projects AS b
            ON a.project_id = b.id
         WHERE a.id=%(id)s""")


async def _load(model: dataclasses.dataclass, obj_id: int,
                application: 'app.Application') -> dataclasses.dataclass:

    def on_postgres_error(_metric_name: str, exc: Exception) -> None:
        LOGGER.error('Failed to execute query for project %s: %s',
                     obj_id, exc)
        raise errors.DatabaseError(
            f'Error loading {model.__class__.__name__}', error=exc)

    async with application.postgres_connector(
            on_error=on_postgres_error) as conn:
        result = await conn.execute(
            model.SQL, {'id': obj_id}, 'model-load')
        if result.row_count:
            return model(**result.row)


async def _load_collection(model: dataclasses.dataclass,
                           obj_id: int,
                           application: 'app.Application') \
        -> typing.List[dataclasses.dataclass]:

    def on_postgres_error(_metric_name: str, exc: Exception) -> None:
        LOGGER.error('Failed to execute query for collection %s: %s',
                     obj_id, exc)
        raise errors.DatabaseError(
            f'Error loading {model.__class__.__name__} '
            f'collection for {obj_id}', error=exc)

    async with application.postgres_connector(
            on_error=on_postgres_error) as conn:
        result = await conn.execute(
            model.COLLECTION_SQL, {'obj_id': obj_id},
            'collection-load')
        return [model(**row) for row in result.rows]


async def namespace(namespace_id: int,
                    application: 'app.Application') -> Namespace:
    return await _load(Namespace, namespace_id, application)


async def operations_log(ops_log_id: int,
                         application: 'app.Application') -> OperationsLog:
    return await _load(OperationsLog, ops_log_id, application)


async def project(project_id: int,
                  application: 'app.Application') -> Project:

    def on_postgres_error(_metric_name: str, exc: Exception) -> None:
        LOGGER.error('Failed to execute query for project %s: %s',
                     project_id, exc)
        raise errors.DatabaseError(
            f'Error loading Project {project_id}', error=exc)

    async with application.postgres_connector(
            on_error=on_postgres_error) as conn:
        result = await conn.execute(
            Project.SQL, {'id': project_id}, 'project-model-load')
        if result.row_count:
            values = dict(result.row)
            result = await asyncio.gather(
                namespace(values['namespace_id'], application),
                project_type(values['project_type_id'], application),
                project_facts(project_id, application),
                project_links(project_id, application),
                project_urls(project_id, application))
            del values['namespace_id']
            del values['project_type_id']
            values.update({
                'namespace': result[0],
                'project_type': result[1],
                'facts': {value.name: value.value for value in result[2]},
                'links': {value.link_type: value.url for value in result[3]},
                'urls': {value.environment: value.url for value in result[4]}})
            return Project(**values)


async def project_facts(project_id: int,
                        application: 'app.Application') \
        -> typing.List[ProjectFact]:
    return await _load_collection(ProjectFact, project_id, application)


async def project_links(project_id: int,
                        application: 'app.Application') \
        -> typing.List[ProjectLink]:
    return await _load_collection(ProjectLink, project_id, application)


async def project_type(project_type_id: int,
                       application: 'app.Application') -> ProjectType:
    return await _load(ProjectType, project_type_id, application)


async def project_urls(project_id: int,
                       application: 'app.Application') \
        -> typing.List[ProjectURL]:
    return await _load_collection(ProjectURL, project_id, application)
