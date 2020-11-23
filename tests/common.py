import asyncio
import contextlib
import logging
import os
import uuid
import warnings

import psycopg2
from ietfparse import headers
from psycopg2 import extras
from tornado import httpclient, testing

from imbi import __version__, app

LOGGER = logging.getLogger(__name__)

JSON_HEADERS = {'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Correlation-Id': str(uuid.uuid4()),
                'User-Agent': 'imbi-tests/{}'.format(__version__)}

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
    'admin': {'group': 'admin', 'username': 'admin'},
    'test': {'group': 'imbi', 'username': 'test'}
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
        'username': 'admin',
        'user_type': 'ldap',
        'external_id': 'cn=admin,ou=users,dc=example,dc=org',
        'email_address': 'admin@example.org',
        'display_name': 'Admin User'
    }
]


class AsyncHTTPTestCase(testing.AsyncHTTPTestCase):
    """Mimics what sprockets.http.run does under the covers."""

    ADMIN = False

    def setUp(self) -> None:
        super().setUp()
        warnings.simplefilter('ignore')
        logging.basicConfig(level=logging.ERROR)
        self._truncate_tables()
        self._setup_groups()
        self._setup_users()
        self.headers = dict(JSON_HEADERS)
        self.headers['Private-Token'] = self._get_token()
        for cb in self._app.runner_callbacks.get('before_run', []):
            cb(self._app, self.io_loop)
        self.wait_until_ready()
        self.io_loop.start()

    def tearDown(self) -> None:
        self.wait_until_done()
        self.io_loop.start()
        super().tearDown()

    def get_app(self) -> app.Application:
        return app.make_application(debug=0)

    @testing.gen_test
    async def wait_until_ready(self):
        for cb in self._app.runner_callbacks.get('on_start', []):
            await cb(self._app, self.io_loop)
        while not self._app.ready_to_serve:
            await asyncio.sleep(0.1)
        self.io_loop.stop()

    @testing.gen_test
    async def wait_until_done(self):
        for cb in self._app.runner_callbacks.get('shutdown', []):
            await cb(self.io_loop)
        self.io_loop.stop()

    def assert_link_header_equals(self,
                                  result: httpclient.HTTPResponse,
                                  expectation: str, rel: str = 'self') -> None:
        """Validate the URL in the link header matches the expectation"""
        for link in headers.parse_link(result.headers['Link']):
            if dict(link.parameters)['rel'] == rel:
                self.assertEqual(link.target, expectation)
                break

    def _get_token(self):
        token = str(uuid.uuid4())
        with self._postgres_cursor() as cursor:
            cursor.execute(
                """INSERT INTO v1.authentication_tokens (username, token)
                     VALUES (%(username)s, %(token)s);""",
                {'username': 'admin' if self.ADMIN else 'test',
                 'token': token})
        return token

    def _setup_groups(self):
        with self._postgres_cursor() as cursor:
            for group in GROUPS:
                cursor.execute(GROUP_SQL, group)

    def _setup_users(self):
        with self._postgres_cursor() as cursor:
            for user in USERS:
                cursor.execute(USER_SQL, user)
                cursor.execute(USER_GROUP_SQL, USER_GROUP[user['username']])

    @contextlib.contextmanager
    def _postgres_cursor(self):
        conn = psycopg2.connect(os.environ.get(
            'POSTGRES_URL',
            'postgres://postgres@localhost:5432/postgres'))
        conn.autocommit = True
        try:
            yield conn.cursor(cursor_factory=extras.RealDictCursor)
        finally:
            conn.close()

    def _truncate_tables(self):
        with self._postgres_cursor() as cursor:
            for table in TABLES:
                cursor.execute('TRUNCATE TABLE {} CASCADE'.format(table))
