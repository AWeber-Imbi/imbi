import unittest
import uuid

from tornado import testing

from imbi import timestamp, user
from tests import base


class GroupTestCase(unittest.TestCase):
    def test_as_dict(self):
        name = str(uuid.uuid4())
        permissions = [str(uuid.uuid4()), str(uuid.uuid4())]
        self.assertDictEqual(dict(user.Group(name, permissions)), {
            'name': name,
            'permissions': sorted(permissions)
        })

    def test_repr(self):
        name = str(uuid.uuid4())
        permissions = [str(uuid.uuid4()), str(uuid.uuid4())]
        group = user.Group(name, permissions)
        self.assertEqual(
            repr(group),
            '<Group name={} permissions={}>'.format(name, sorted(permissions)))


class InternalTestCase(base.TestCase):

    SQL_INSERT_GROUP = """\
    INSERT INTO v1.groups ("name", permissions)
         VALUES (%(name)s, %(permissions)s)"""

    SQL_INSERT_GROUP_MEMBERSHIP = """\
    INSERT INTO v1.group_members ("group", username)
         VALUES (%(group)s, %(username)s)"""

    SQL_INSERT_USER = """\
    INSERT INTO v1.users (username, display_name, email_address, password,
                          last_seen_at)
         VALUES (%(username)s, %(display_name)s, %(email_address)s,
                 %(password)s, %(last_seen_at)s)"""

    SQL_UPDATE_DISPLAY_NAME = """\
    UPDATE v1.users SET display_name = %(display_name)s
     WHERE username = %(username)s"""

    async def setup_group(self, values=None):
        if not values:
            values = {}
        values.setdefault('name', str(uuid.uuid4()))
        values.setdefault('permissions',
                          sorted([str(uuid.uuid4()),
                                  str(uuid.uuid4())]))
        await self.postgres_execute(self.SQL_INSERT_GROUP, values)
        return values

    async def setup_group_membership(self, username, group):
        await self.postgres_execute(self.SQL_INSERT_GROUP_MEMBERSHIP, {
            'group': group,
            'username': username
        })

    async def setup_user(self, values=None):
        if not values:
            values = {}
        values.setdefault('username', str(uuid.uuid4()))
        values.setdefault('display_name', str(uuid.uuid4()))
        values.setdefault('email_address',
                          '{}@{}'.format(str(uuid.uuid4()), str(uuid.uuid4())))
        values.setdefault('last_seen_at', timestamp.utcnow())
        password = values.get('password', str(uuid.uuid4()))
        values['password'] = self._app.hash_password(password)
        await self.postgres_execute(self.SQL_INSERT_USER, values)
        values['password'] = password
        return values

    @testing.gen_test
    async def test_authenticate_happy_path(self):
        user_value = await self.setup_user()
        group_value = await self.setup_group()
        await self.setup_group_membership(user_value['username'],
                                          group_value['name'])

        obj = user.User(self._app, user_value['username'],
                        user_value['password'])
        self.assertTrue(await obj.authenticate())

        values = obj.as_dict()
        for key in {
                'created_at', 'last_refreshed_at', 'last_seen_at', 'password'
        }:
            self.assertIn(key, values)
            del values[key]

        expectation = {
            'username': user_value['username'],
            'user_type': 'internal',
            'external_id': None,
            'google_user': False,
            'display_name': user_value['display_name'],
            'email_address': user_value['email_address'],
            'groups': [group_value['name']],
            'permissions': sorted(set(group_value['permissions'])),
            'integrations': [],
        }
        self.assertDictEqual(values, expectation)

        for role in group_value['permissions']:
            self.assertTrue(obj.has_permission(role))
        self.assertFalse(obj.has_permission('other'))

    @testing.gen_test
    async def test_refresh(self):
        user_value = await self.setup_user()
        group_value = await self.setup_group()
        await self.setup_group_membership(user_value['username'],
                                          group_value['name'])

        obj = user.User(self._app, user_value['username'],
                        user_value['password'])
        self.assertTrue(await obj.authenticate())

        display_name = str(uuid.uuid4())
        self.assertNotEqual(display_name, user_value['display_name'])

        await self.postgres_execute(self.SQL_UPDATE_DISPLAY_NAME, {
            'display_name': display_name,
            'username': user_value['username']
        })

        await obj.refresh()

        values = obj.as_dict()
        for key in {
                'created_at', 'last_refreshed_at', 'last_seen_at', 'password'
        }:
            self.assertIn(key, values)
            del values[key]

        expectation = {
            'username': user_value['username'],
            'user_type': 'internal',
            'external_id': None,
            'google_user': False,
            'display_name': display_name,
            'email_address': user_value['email_address'],
            'groups': [group_value['name']],
            'permissions': sorted(set(group_value['permissions'])),
            'integrations': [],
        }
        self.assertDictEqual(values, expectation)

    @testing.gen_test
    async def test_reset_on_authentication_failure(self):
        user_value = await self.setup_user()
        obj = user.User(self._app, user_value['username'],
                        user_value['password'])
        self.assertTrue(await obj.authenticate())
        for key in {'display_name', 'email_address'}:
            self.assertEqual(user_value[key], getattr(obj, key))
        obj._password = str(uuid.uuid4())
        self.assertFalse(await obj.authenticate())
        for key in {'display_name', 'email_address'}:
            self.assertIsNone(getattr(obj, key))

    @testing.gen_test
    async def test_token_authentication(self):
        user_value = await self.setup_user()
        token = await self.get_token(user_value['username'])
        obj = user.User(self._app, None, None, token)
        self.assertTrue(await obj.authenticate())
        for key in {'display_name', 'email_address'}:
            self.assertEqual(user_value[key], getattr(obj, key))

    @testing.gen_test
    async def test_token_authentication_failure(self):
        obj = user.User(self._app, 'foo', None, str(uuid.uuid4()))
        self.assertFalse(await obj.authenticate())

    @testing.gen_test
    async def test_garbage_token_fails(self):
        obj = user.User(self._app, 'foo', None, 'ohno')
        self.assertFalse(await obj.authenticate())

    @testing.gen_test
    async def test_should_refresh_false(self):
        user_value = await self.setup_user()
        obj = user.User(self._app, user_value['username'],
                        user_value['password'])
        self.assertTrue(await obj.authenticate())
        self.assertFalse(obj.should_refresh)

    @testing.gen_test
    async def test_should_refresh_true(self):
        user_value = await self.setup_user()
        obj = user.User(self._app, user_value['username'],
                        user_value['password'])
        self.assertTrue(await obj.authenticate())
        self.assertFalse(obj.should_refresh)
        obj.last_refreshed_at = timestamp.utcnow() - (obj.REFRESH_AFTER * 2)
        self.assertTrue(obj.should_refresh)

    @testing.gen_test
    async def test_update_last_seen_at(self):
        user_value = await self.setup_user()
        obj = user.User(self._app, user_value['username'],
                        user_value['password'])
        self.assertTrue(await obj.authenticate())
        last_seen_at = obj.last_seen_at
        await obj.update_last_seen_at()
        self.assertGreater(obj.last_seen_at, last_seen_at)


class LDAPTestCase(base.TestCase):

    LDAP_USERNAME = 'test'
    LDAP_PASSWORD = 'password'

    @staticmethod
    def get_user_dn(conn):
        result = conn.extend.standard.who_am_i()
        return result[3:]

    @testing.gen_test
    async def test_authenticate(self):
        obj = user.User(self._app, self.LDAP_USERNAME, self.LDAP_PASSWORD)
        self.assertTrue(await obj.authenticate())

        await obj.refresh()

        values = obj.as_dict()
        for key in {
                'created_at', 'last_refreshed_at', 'last_seen_at', 'password'
        }:
            self.assertIn(key, values)
            del values[key]

        expectation = {
            'username': 'test',
            'user_type': 'ldap',
            'external_id': 'cn=test,ou=users,dc=example,dc=org',
            'google_user': False,
            'display_name': 'Its Imbi',
            'email_address': 'imbi@example.org',
            'groups': ['admin', 'imbi'],
            'permissions': ['admin', 'reader'],
            'integrations': [],
        }
        self.assertDictEqual(values, expectation)
        self.assertTrue(obj.has_permission('admin'))
        self.assertFalse(obj.has_permission('other'))

    @testing.gen_test
    async def test_authentication_failure_without_password(self):
        obj = user.User(self._app, self.LDAP_USERNAME)
        self.assertFalse(await obj.authenticate())

    @testing.gen_test
    async def test_reset_on_authentication_failure(self):
        obj = user.User(self._app, self.LDAP_USERNAME, self.LDAP_PASSWORD)
        self.assertTrue(await obj.authenticate())
        for key in {'display_name', 'email_address', 'external_id'}:
            self.assertIsNotNone(getattr(obj, key))
        obj = user.User(self._app, self.LDAP_USERNAME, str(uuid.uuid4()))
        self.assertFalse(await obj.authenticate())
        for key in {'display_name', 'email_address', 'external_id'}:
            self.assertIsNone(getattr(obj, key))

    @testing.gen_test
    async def test_token_authentication(self):
        obj1 = user.User(self._app, self.LDAP_USERNAME, self.LDAP_PASSWORD)
        self.assertTrue(await obj1.authenticate())
        token = await self.get_token(self.LDAP_USERNAME)
        obj2 = user.User(self._app, None, None, token)
        self.assertTrue(await obj2.authenticate())
        self.assertEqual(obj1.username, obj2.username)

    @testing.gen_test
    async def test_should_refresh_false(self):
        obj = user.User(self._app, self.LDAP_USERNAME, self.LDAP_PASSWORD)
        self.assertTrue(await obj.authenticate())
        self.assertFalse(obj.should_refresh)

    @testing.gen_test
    async def test_should_refresh_true(self):
        obj = user.User(self._app, self.LDAP_USERNAME, self.LDAP_PASSWORD)
        self.assertTrue(await obj.authenticate())
        self.assertFalse(obj.should_refresh)
        obj.last_refreshed_at = timestamp.utcnow() - (obj.REFRESH_AFTER * 2)
        self.assertTrue(obj.should_refresh)
