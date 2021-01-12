import asyncio
import contextlib
import logging
import typing
import uuid
from logging import config

import aiopg
from ietfparse import headers
from psycopg2 import extensions, extras
from tornado import httpclient, testing

from imbi import app, openapi, server, version

LOGGER = logging.getLogger(__name__)

JSON_HEADERS = {'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Correlation-Id': str(uuid.uuid4()),
                'User-Agent': 'imbi-tests/{}'.format(version)}

TABLES = [
    'v1.authentication_tokens',
    'v1.configuration_systems',
    'v1.data_centers',
    'v1.deployment_types',
    'v1.environments',
    'v1.group_members',
    'v1.groups',
    'v1.orchestration_systems',
    'v1.projects',
    'v1.project_link_types',
    'v1.project_types',
    'v1.teams',
    'v1.users'
]

GROUP_SQL = """\
INSERT INTO v1.groups ("name", group_type, external_id, permissions)
     VALUES (%(name)s, %(group_type)s, %(external_id)s, %(permissions)s)
ON CONFLICT DO NOTHING;"""

GROUPS = [
    {
        'name': 'admin',
        'group_type': 'ldap',
        'external_id': 'cn=admin,ou=groups,dc=example,dc=org',
        'permissions': ['admin']
    },
    {
        'name': 'imbi',
        'group_type': 'ldap',
        'external_id': 'cn=imbi,ou=groups,dc=example,dc=org',
        'permissions': ['reader']
    }
]

USER_GROUP = {
    'test': {'group': 'admin', 'username': 'test'},
    'ffink': {'group': 'imbi', 'username': 'ffink'}
}

USER_GROUP_SQL = """\
INSERT INTO v1.group_members("group", username)
     VALUES (%(group)s, %(username)s) ON CONFLICT DO NOTHING;"""


USER_SQL = """\
INSERT INTO v1.users (username, user_type, external_id,
                      email_address, display_name)
    VALUES (%(username)s, %(user_type)s, %(external_id)s,
            %(email_address)s, %(display_name)s)
ON CONFLICT DO NOTHING;"""

USERS = [
    {
        'username': 'test',
        'user_type': 'ldap',
        'external_id': 'cn=test,ou=users,dc=example,dc=org',
        'email_address': 'imbi@example.org',
        'display_name': 'Its Imbi'
    },
    {
        'username': 'ffink',
        'user_type': 'ldap',
        'external_id': 'cn=ffink,ou=users,dc=example,dc=org',
        'email_address': 'ffink@frank-jewelry.com',
        'display_name': 'Frank',
    }
]


class TestCase(testing.AsyncHTTPTestCase):

    ADMIN_ACCESS = False

    USERNAME = {
        True: 'test',
        False: 'ffink'
    }

    SQL_INSERT_TOKEN = """\
    INSERT INTO v1.authentication_tokens (token, username)
         VALUES (%(token)s, %(username)s);"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.settings, logging_config = server.load_configuration(
            'build/test.yaml', False)
        config.dictConfig(logging_config)

    def setUp(self) -> None:
        self.headers = dict(JSON_HEADERS)
        self.postgres = None
        super().setUp()
        self.loop = asyncio.get_event_loop()
        self.loop.run_until_complete(self.async_setup())

    def tearDown(self) -> None:
        self.loop.run_until_complete(self.async_tear_down())
        super().tearDown()

    async def async_setup(self) -> None:
        self.postgres = await aiopg.connect(
            dsn=self.settings['postgres_url'],
            enable_hstore=False,
            enable_json=True,
            enable_uuid=True)
        for callback in self._app.runner_callbacks.get('on_start', []):
            await callback(self._app, self.loop)
        while self._app.startup_complete is None:
            await asyncio.sleep(0.01)
        await self._app.startup_complete.wait()

    async def async_tear_down(self) -> None:
        for callback in self._app.runner_callbacks.get('shutdown', []):
            await callback(self.loop)
        self.postgres.close()

    @contextlib.asynccontextmanager
    async def cursor(self) -> extensions.cursor:
        cursor = await self.postgres.cursor(
            cursor_factory=extras.RealDictCursor)
        yield cursor
        cursor.close()

    def fetch(self, *args, **kwargs):
        response = super().fetch(*args, **kwargs)
        if ';' in response.headers.get('content-type', ''):
            response.headers['content-type'] = \
                response.headers['content-type'].split(';')[0]
        return response

    def get_app(self) -> app.Application:
        return app.Application(**self.settings)

    async def get_token(self, username: typing.Optional[str] = None) -> str:
        values = {
            'token': str(uuid.uuid4()),
            'username': username or self.USERNAME[self.ADMIN_ACCESS]
        }
        async with self.cursor() as cursor:
            await cursor.execute(self.SQL_INSERT_TOKEN, values)
            self.assertEqual(cursor.rowcount, 1)
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

    async def async_setup(self) -> None:
        await super().async_setup()
        await self._truncate_tables()
        await self._setup_groups()
        await self._setup_users()
        self.headers['Private-Token'] = await self.get_token()

    async def _setup_groups(self):
        async with self.cursor() as cursor:
            for group in GROUPS:
                await cursor.execute(GROUP_SQL, group)

    async def _setup_users(self):
        async with self.cursor() as cursor:
            for user in USERS:
                await cursor.execute(USER_SQL, user)
                await cursor.execute(
                    USER_GROUP_SQL, USER_GROUP[user['username']])

    async def _truncate_tables(self):
        async with self.cursor() as cursor:
            for table in TABLES:
                await cursor.execute('TRUNCATE TABLE {} CASCADE'.format(table))
