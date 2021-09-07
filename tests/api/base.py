import asyncio
import json
import logging
import typing
import uuid

import sprockets_postgres as postgres
from ietfparse import headers
from tornado import httpclient, testing

from imbi import app, openapi, server, version

LOGGER = logging.getLogger(__name__)

JSON_HEADERS = {'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Correlation-Id': str(uuid.uuid4()),
                'User-Agent': 'imbi-tests/{}'.format(version)}


class TestCase(testing.AsyncHTTPTestCase):

    ADMIN_ACCESS = False

    USERNAME = {
        True: 'test',
        False: 'ffink'
    }

    SQL_INSERT_TOKEN = """\
    INSERT INTO v1.authentication_tokens (token, name, username)
         VALUES (%(token)s, %(name)s, %(username)s);"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.settings, logging_config = server.load_configuration(
            'build/test.yaml', False)
        logging.getLogger('openapi_spec_validator').setLevel(logging.CRITICAL)

    def setUp(self) -> None:
        self.maxDiff = 32768
        self.headers = dict(JSON_HEADERS)
        self.postgres = None
        super().setUp()
        self.loop = asyncio.get_event_loop()
        self.loop.run_until_complete(self.async_setup())

    def tearDown(self) -> None:
        self.loop.run_until_complete(self.async_tear_down())
        super().tearDown()

    async def async_setup(self) -> None:
        LOGGER.info('async_setup start')
        await asyncio.wait(
            [asyncio.create_task(callback(self._app, self.loop))
             for callback in self._app.on_start_callbacks])
        while self._app.startup_complete is None:
            await asyncio.sleep(0.001)
        await self._app.startup_complete.wait()
        LOGGER.info('async_setup end')

    async def async_tear_down(self) -> None:
        for callback in self._app.runner_callbacks.get('shutdown', []):
            await callback(self.loop)

    async def postgres_execute(self,
                               sql: str,
                               parameters: postgres.QueryParameters) \
            -> postgres.QueryResult:
        async with self._app.postgres_connector() as connector:
            return await connector.execute(sql, parameters)

    def get_app(self) -> app.Application:
        return app.Application(**self.settings)

    async def get_token(self, username: typing.Optional[str] = None) -> str:
        token_value = str(uuid.uuid4())
        values = {
            'token': token_value,
            'name': token_value,
            'username': username or self.USERNAME[self.ADMIN_ACCESS]
        }
        result = await self.postgres_execute(self.SQL_INSERT_TOKEN, values)
        self.assertEqual(len(result), 1)
        return values['token']

    def assert_link_header_equals(self,
                                  result: httpclient.HTTPResponse,
                                  expectation: str, rel: str = 'self') -> None:
        """Validate the URL in the link header matches the expectation"""
        for link in headers.parse_link(result.headers['Link']):
            if dict(link.parameters)['rel'] == rel:
                self.assertEqual(link.target, expectation)
                break

    def validate_response(self, response):
        """Validate the response using the OpenAPI expectations"""
        openapi.response_validator(
            self.settings).validate(response).raise_for_errors()


class TestCaseWithReset(TestCase):

    TRUNCATE_TABLES = []

    def setUp(self) -> None:
        super().setUp()
        self.environments: typing.Optional[typing.List[typing.Dict]] = None
        self.namespace: typing.Optional[typing.Dict] = None
        self.project_fact_type: typing.Optional[typing.Dict] = None
        self.project_type: typing.Optional[typing.Dict] = None

    async def async_setup(self) -> None:
        await super().async_setup()
        self.headers['Private-Token'] = await self.get_token()

    async def async_tear_down(self) -> None:
        for table in self.TRUNCATE_TABLES:
            await self.postgres_execute(
                'TRUNCATE TABLE {} CASCADE'.format(table), {})
        await super().async_tear_down()

    def create_project(self) -> dict:
        if not self.namespace:
            self.namespace = self.create_namespace()
        if not self.project_type:
            self.project_type = self.create_project_type()
        result = self.fetch(
            '/projects', method='POST', headers=self.headers,
            body=json.dumps({
                'namespace_id': self.namespace['id'],
                'project_type_id': self.project_type['id'],
                'name': str(uuid.uuid4()),
                'slug': str(uuid.uuid4().hex),
                'description': str(uuid.uuid4()),
                'environments': self.environments,
            }).encode('utf-8'))
        self.assertEqual(result.code, 200)
        return json.loads(result.body.decode('utf-8'))

    def create_environments(self) -> typing.List[dict]:
        environments = []
        for iteration in range(0, 2):
            result = self.fetch(
                '/environments', method='POST', headers=self.headers,
                body=json.dumps({
                    'name': str(uuid.uuid4()),
                    'description': str(uuid.uuid4()),
                    'icon_class': 'fas fa-blind'
                }).encode('utf-8'))
            self.assertEqual(result.code, 200)
            environments.append(
                json.loads(result.body.decode('utf-8'))['name'])
        return environments

    def create_namespace(self) -> dict:
        namespace_name = str(uuid.uuid4())
        result = self.fetch(
            '/namespaces', method='POST', headers=self.headers,
            body=json.dumps({
                'name': namespace_name,
                'slug': str(uuid.uuid4()),
                'icon_class': 'fas fa-blind'
            }).encode('utf-8'))
        self.assertEqual(result.code, 200)
        return json.loads(result.body.decode('utf-8'))

    def create_project_fact_type(self) -> dict:
        if not self.project_type:
            self.project_type = self.create_project_type()
        print(self.project_type['id'])
        result = self.fetch(
            '/project-fact-types', method='POST', headers=self.headers,
            body=json.dumps({
                'project_type_ids': [self.project_type['id']],
                'name': str(uuid.uuid4()),
                'fact_type': 'free-form',
                'data_type': 'string',
                'weight': 100
            }).encode('utf-8'))
        self.assertEqual(result.code, 200)
        return json.loads(result.body.decode('utf-8'))

    def create_project_link_type(self) -> dict:
        result = self.fetch(
            '/project-link-types', method='POST', headers=self.headers,
            body=json.dumps({
                'link_type': str(uuid.uuid4()),
                'icon_class': 'fas fa-blind'
            }).encode('utf-8'))
        self.assertEqual(result.code, 200)
        return json.loads(result.body.decode('utf-8'))

    def create_project_type(self) -> dict:
        project_type_name = str(uuid.uuid4())
        result = self.fetch(
            '/project-types', method='POST', headers=self.headers,
            body=json.dumps({
                'name': project_type_name,
                'plural_name': '{}s'.format(project_type_name),
                'slug': str(uuid.uuid4()),
                'description': str(uuid.uuid4()),
                'icon_class': 'fas fa-blind',
                'environment_urls': False
            }).encode('utf-8'))
        self.assertEqual(result.code, 200)
        return json.loads(result.body.decode('utf-8'))
