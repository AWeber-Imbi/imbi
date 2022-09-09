import asyncio
import dataclasses
import logging
import typing

from imbi import errors, models
from imbi.clients import opensearch
if typing.TYPE_CHECKING:
    from imbi import app

LOGGER = logging.getLogger(__name__)

FACT_DATA_TYPES = {
    'boolean': 'boolean',
    'date': 'date',
    'decimal': 'float',
    'integer': 'integer',
    'string': 'text',
    'timestamp': 'date'
}

PROJECT = {
    'id': {'type': 'integer'},
    'created_at': {'type': 'date'},
    'created_by': {'type': 'text'},
    'last_modified_at': {'type': 'date'},
    'last_modified_by': {'type': 'text'},
    'namespace': {'type': 'text'},
    'namespace_slug': {'type': 'text'},
    'project_type': {'type': 'text'},
    'project_type_slug': {'type': 'text'},
    'name': {'type': 'text'},
    'slug': {'type': 'text'},
    'description': {'type': 'text'},
    'environments': {'type': 'text'},
    'archived': {'type': 'boolean'},
    'gitlab_project_id': {'type': 'text'},
    'sentry_project_slug': {'type': 'text'},
    'sonarqube_project_key': {'type': 'text'},
    'pagerduty_service_id': {'type': 'text'},
    'project_score': {'type': 'integer'}
}


class ProjectIndex:
    """Class for interacting with the OpenSearch Project index"""

    INDEX = 'projects'

    def __init__(self, application: 'app.Application'):
        self.application = application

    async def create_index(self):
        LOGGER.debug('Creating projects index in OpenSearch')
        await self.application.opensearch.create_index(self.INDEX)

    async def create_mapping(self):
        await self.application.opensearch.create_mapping(
            self.INDEX, await self._build_mappings())

    async def delete_document(self, project_id: typing.Union[int, str]):
        await self.application.opensearch.delete_document(
                self.INDEX, str(project_id))

    async def index_document(self, project: models.Project):
        await self.application.opensearch.index_document(
            self.INDEX, str(project.id), self._project_to_dict(project))

    async def search(self, query: str, max_results: int = 1000) \
            -> typing.Dict[str, typing.List[dict]]:
        return await self.application.opensearch.search(
            self.INDEX, query, max_results)

    async def searchable_fields(self) -> typing.List[typing.Dict]:
        fields = []
        index_mappings = await self._build_mappings()
        for key, defn in index_mappings.items():
            try:
                fields.append({
                    'name': key,
                    'type': defn['type'],
                    'count': 0,
                    'scripted': False,
                    'searchable': True,
                    'aggregatable': True,
                    'readFromDocValues': True
                })
            except KeyError:
                pass

        async with self.application.postgres_connector(
                on_error=self._on_postgres_error) as cursor:
            result = await cursor.execute(
                'SELECT name, data_type FROM v1.project_fact_types;')
            for row in result:
                fields.append({
                    'name': row['name'].lower().replace(' ', '_'),
                    'type': FACT_DATA_TYPES[row['data_type']],
                    'count': 0,
                    'scripted': False,
                    'searchable': True,
                    'aggregatable': True,
                    'readFromDocValues': True
                })
        return fields

    async def _build_mappings(self) -> dict:
        defn = dict(PROJECT)
        async with self.application.postgres_connector(
                on_error=self._on_postgres_error) as cursor:
            result = await cursor.execute(
                        'SELECT name, data_type FROM v1.project_fact_types;')
            for row in result:
                defn[f'facts.{opensearch.sanitize_key(row["name"])}'] = {
                    'type': FACT_DATA_TYPES[row['data_type']]
                }
            result = await cursor.execute(
                        'SELECT link_type FROM v1.project_link_types;')
            for row in result:
                defn[f'links.{opensearch.sanitize_key(row["link_type"])}'] = {
                    'type': 'text'
                }
            result = await cursor.execute('SELECT name FROM v1.environments;')
            for row in result:
                defn[f'urls.{opensearch.sanitize_key(row["name"])}'] = {
                    'type': 'text'
                }
        return defn

    @staticmethod
    def _on_postgres_error(metric_name: str, exc: Exception) -> None:
        LOGGER.error('Failed to execute query for collection %s: %s',
                     metric_name, exc)
        raise errors.DatabaseError(
            f'Error executing {metric_name}', error=exc)

    @staticmethod
    def _project_to_dict(value: models.Project) -> dict:
        output = dataclasses.asdict(value)
        for key in ['namespace', 'project_type']:
            output[f'{key}_slug'] = output[key]['slug']
            output[key] = output[key]['name']
        return output


class RequestHandlerMixin:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_index = ProjectIndex(self.application)

    async def index_document(self, project_id: typing.Union[int, str]) -> None:
        value = await models.project(project_id, self.application)
        await self.search_index.index_document(value)


async def initialize(application: 'app.Application', build=False):
    index = ProjectIndex(application)
    LOGGER.info('Creating the project index')
    await index.create_index()
    LOGGER.info('Creating the project index mappings')
    await index.create_mapping()

    if build:
        async with application.postgres_connector() as conn:
            result = await conn.execute(
                'SELECT id FROM v1.projects ORDER BY id', {},
                'build-project-index')
            ids = [row['id'] for row in result]
            LOGGER.info('Queueing %i projects for indexing', len(ids))
            for project_id in ids:
                value = await models.project(project_id, application)
                await index.index_document(value)
            LOGGER.info('Queued %i projects for indexing', len(ids))
            while True:
                pending = \
                    await index.application.opensearch.documents_pending()
                if not pending:
                    break
                LOGGER.info('Waiting for %i projects to index', pending)
                await asyncio.sleep(2)
            LOGGER.info('Indexing complete')
