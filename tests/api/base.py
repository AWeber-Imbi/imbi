from __future__ import annotations

import functools
import json
import logging
import pathlib
import typing
import uuid

import sprockets_postgres as postgres
import tornado_openapi3
from ietfparse import headers
from sprockets.http import testing
from tornado import gen, httpclient, httputil

from imbi import app, openapi, server, version

LOGGER = logging.getLogger(__name__)

JSON_HEADERS = {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
    'Correlation-Id': str(uuid.uuid4()),
    'User-Agent': 'imbi-tests/{}'.format(version)
}


@functools.lru_cache(1)
def read_config():
    top_dir = pathlib.Path(__file__).parent.parent
    settings, _ = server.load_configuration(
        (top_dir / 'build' / 'test.yaml').as_posix(), False)
    return settings


class TestCase(testing.SprocketsHttpTestCase):

    ADMIN_ACCESS = False

    USERNAME = {True: 'test', False: 'ffink'}

    SQL_INSERT_TOKEN = """\
    INSERT INTO v1.authentication_tokens (token, name, username)
         VALUES (%(token)s, %(name)s, %(username)s);"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = read_config()
        logging.getLogger('openapi_spec_validator').setLevel(logging.CRITICAL)

    def setUp(self) -> None:
        self.maxDiff = 32768
        self.headers = dict(JSON_HEADERS)
        self.postgres = None
        super().setUp()

        # Run the Tornado IOLoop until the startup_complete object
        # is created.  For some reason using the asyncio_loop does not
        # work reliably here
        while self.app.startup_complete is None:
            self.io_loop.add_future(gen.sleep(0.001),
                                    lambda _: self.io_loop.stop())
            self.io_loop.start()

        # Now we can wait for the application to finish initializing
        self.run_until_complete(self.app.startup_complete.wait())

    def run_until_complete(self, future):
        return self.io_loop.asyncio_loop.run_until_complete(future)

    def fetch(self,
              path: str,
              raise_error: bool = False,
              json_body: list | dict | None = None,
              **kwargs: typing.Any) -> httpclient.HTTPResponse:
        """Extended version of fetch that injects self.headers"""
        request_headers = httputil.HTTPHeaders(self.headers)
        request_headers.update(kwargs.pop('headers', {}))
        if json_body is not None:
            kwargs['body'] = json.dumps(json_body).encode('utf-8')
        if (kwargs.get('method') in {'PATCH', 'POST', 'PUT'}
                and not kwargs.get('body')):
            kwargs.setdefault('allow_nonstandard_methods', True)
        return super().fetch(path,
                             raise_error=raise_error,
                             headers=request_headers,
                             **kwargs)

    async def postgres_execute(self,
                               sql: str,
                               parameters: postgres.QueryParameters) \
            -> postgres.QueryResult:
        async with self.app.postgres_connector() as connector:
            return await connector.execute(sql, parameters)

    def get_app(self) -> app.Application:
        self.app = app.Application(**self.settings)
        return self.app

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
                                  expectation: str,
                                  rel: str = 'self') -> None:
        """Validate the URL in the link header matches the expectation"""
        for link in headers.parse_link(result.headers['Link']):
            if dict(link.parameters)['rel'] == rel:
                self.assertEqual(link.target, expectation)
                break

    def validate_response(self, response):
        """Validate the response using the OpenAPI expectations"""
        validator = tornado_openapi3.ResponseValidator(
            spec=openapi.create_spec(self.settings),
            custom_formatters=openapi._openapi_formatters,
            custom_media_type_deserializers=openapi._openapi_deserializers)
        validator.validate(response).raise_for_errors()


class TestCaseWithReset(TestCase):

    TRUNCATE_TABLES = []

    def setUp(self) -> None:
        super().setUp()
        self.environments: typing.Optional[typing.List[typing.Dict]] = None
        self.namespace: typing.Optional[typing.Dict] = None
        self.project_fact_type: typing.Optional[typing.Dict] = None
        self.project_type: typing.Optional[typing.Dict] = None
        self.headers['Private-Token'] = self.run_until_complete(
            self.get_token())

    def tearDown(self) -> None:
        for table in self.TRUNCATE_TABLES:
            self.run_until_complete(
                self.postgres_execute(f'TRUNCATE TABLE {table} CASCADE', {}))
        super().tearDown()

    def create_project(self) -> dict:
        if not self.environments:
            self.environments = self.create_environments()
        if not self.namespace:
            self.namespace = self.create_namespace()
        if not self.project_type:
            self.project_type = self.create_project_type()
        result = self.fetch('/projects',
                            method='POST',
                            json_body={
                                'namespace_id': self.namespace['id'],
                                'project_type_id': self.project_type['id'],
                                'name': str(uuid.uuid4()),
                                'slug': str(uuid.uuid4().hex),
                                'description': str(uuid.uuid4()),
                                'environments': self.environments,
                            })
        self.assertEqual(result.code, 200)
        return json.loads(result.body.decode('utf-8'))

    def create_environments(self) -> typing.List[dict]:
        environments = []
        for iteration in range(0, 2):
            result = self.fetch('/environments',
                                method='POST',
                                json_body={
                                    'name': str(uuid.uuid4()),
                                    'description': str(uuid.uuid4()),
                                    'icon_class': 'fas fa-blind'
                                })
            self.assertEqual(result.code, 200)
            environments.append(
                json.loads(result.body.decode('utf-8'))['name'])
        return environments

    def create_namespace(self) -> dict:
        namespace_name = str(uuid.uuid4())
        result = self.fetch('/namespaces',
                            method='POST',
                            json_body={
                                'name': namespace_name,
                                'slug': str(uuid.uuid4()),
                                'icon_class': 'fas fa-blind'
                            })
        self.assertEqual(result.code, 200)
        return json.loads(result.body.decode('utf-8'))

    def create_project_fact_type(self, **overrides) -> dict:
        if not self.project_type:
            self.project_type = self.create_project_type()
        project_fact = {
            'project_type_ids': [self.project_type['id']],
            'name': str(uuid.uuid4()),
            'fact_type': 'free-form',
            'data_type': 'string',
            'weight': 100
        }
        project_fact.update(overrides)

        result = self.fetch('/project-fact-types',
                            method='POST',
                            json_body=project_fact)
        self.assertEqual(result.code, 200)
        return json.loads(result.body.decode('utf-8'))

    def create_project_link_type(self) -> dict:
        result = self.fetch('/project-link-types',
                            method='POST',
                            json_body={
                                'link_type': str(uuid.uuid4()),
                                'icon_class': 'fas fa-blind'
                            })
        self.assertEqual(result.code, 200)
        return json.loads(result.body.decode('utf-8'))

    def create_project_type(self) -> dict:
        project_type_name = str(uuid.uuid4())
        result = self.fetch('/project-types',
                            method='POST',
                            json_body={
                                'name': project_type_name,
                                'plural_name': '{}s'.format(project_type_name),
                                'slug': str(uuid.uuid4()),
                                'description': str(uuid.uuid4()),
                                'icon_class': 'fas fa-blind',
                                'environment_urls': False
                            })
        self.assertEqual(result.code, 200)
        return json.loads(result.body.decode('utf-8'))
