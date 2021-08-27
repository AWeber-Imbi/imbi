"""
User Model supporting both LDAP and PostgreSQL data sources

"""
import dataclasses
import datetime
import logging
import re
import typing
from itertools import chain

import ldap3
import psycopg2.errors
from tornado import web

from imbi import ldap, oauth2, timestamp

LOGGER = logging.getLogger(__name__)


class Group:
    """Group class to represent a single group a user is a member of"""
    __slots__ = ['name', 'permissions']

    def __init__(self, name: str, permissions: typing.List[str]):
        self.name = name
        self.permissions = sorted(permissions or [])

    def __iter__(self):
        return iter([('name', self.name), ('permissions', self.permissions)])

    def __repr__(self):
        return '<Group name={} permissions={}>'.format(
            self.name, self.permissions)


@dataclasses.dataclass
class ConnectedIntegration:
    """The connection between a user and a specific integration."""
    name: str
    external_id: str


class User:
    """Holds the user attributes and interfaces with the directory server"""

    REFRESH_AFTER = datetime.timedelta(minutes=5)

    SQL_AUTHENTICATE = re.sub(r'\s+', ' ', """\
           UPDATE v1.users
              SET last_seen_at = CURRENT_TIMESTAMP
            WHERE username = %(username)s
              AND password = %(password)s
              AND user_type = 'internal'
        RETURNING username""")

    SQL_AUTHENTICATE_TOKEN = re.sub(r'\s+', ' ', """\
           UPDATE v1.users
              SET last_seen_at = CURRENT_TIMESTAMP
            WHERE username IN (
                    SELECT username
                      FROM v1.authentication_tokens
                     WHERE token = %(token)s
                       AND expires_at > CURRENT_TIMESTAMP)
        RETURNING username, user_type, external_id""")  # nosec

    SQL_GROUPS = re.sub(r'\s+', ' ', """\
        SELECT a.name, a.permissions
          FROM v1.groups AS a
          JOIN v1.group_members AS b ON b.group = a.name
         WHERE b.username = %(username)s""")

    SQL_INTEGRATIONS = re.sub(r'\s+', ' ', """\
        SELECT integration AS name, external_id
          FROM v1.user_oauth2_tokens
         WHERE username = %(username)s""")

    SQL_REFRESH = re.sub(r'\s+', ' ', """\
        SELECT username, created_at, last_seen_at, user_type, external_id,
               email_address, display_name
          FROM v1.users
         WHERE username = %(username)s""")

    SQL_UPDATE_GROUP_MEMBERSHIPS_FROM_LDAP = re.sub(r'\s+', ' ', """\
        SELECT maintain_group_membership_from_ldap_groups AS groups
          FROM maintain_group_membership_from_ldap_groups(%(username)s,
                                                          %(groups)s)""")

    SQL_UPDATE_LAST_SEEN_AT = re.sub(r'\s+', ' ', """\
            UPDATE v1.users
               SET last_seen_at = CURRENT_TIMESTAMP
             WHERE username = %(username)s
         RETURNING last_seen_at""")

    SQL_UPDATE_USER_FROM_LDAP = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.users (username, user_type, external_id,
                              display_name, email_address, last_seen_at)
             VALUES (%(username)s,
                     %(user_type)s,
                     %(external_id)s,
                     %(display_name)s,
                     %(email_address)s,
                     CURRENT_TIMESTAMP)
        ON CONFLICT (username)
                 DO UPDATE SET email_address = EXCLUDED.email_address,
                                 external_id = EXCLUDED.external_id,
                                   user_type = EXCLUDED.user_type,
                                    password = NULL,
                                last_seen_at = CURRENT_TIMESTAMP
                        WHERE users.username = EXCLUDED.username
          RETURNING last_seen_at""")

    def __init__(self, application,
                 username: typing.Optional[str] = None,
                 password: typing.Optional[str] = None,
                 token: typing.Optional[str] = None) -> None:
        self._application = application
        self._ldap = ldap.Client(application.settings['ldap'])
        self._ldap_conn: typing.Optional[ldap3.Connection] = None
        self.username = username
        self.created_at: typing.Optional[datetime.datetime] = None
        self.last_refreshed_at: typing.Optional[datetime.datetime] = None
        self.last_seen_at: typing.Optional[datetime.datetime] = None
        self.user_type = 'internal'
        self.external_id: typing.Optional[str] = None
        self.email_address: typing.Optional[str] = None
        self.display_name: typing.Optional[str] = None
        self._password = password
        self.token = token
        self.connected_integrations: typing.List[ConnectedIntegration] = []
        self.groups: typing.List[Group] = []
        self.permissions: typing.List[str] = []

    @property
    def password(self):
        return self._password

    def __del__(self):
        if self._ldap_conn is not None:
            self._ldap_conn.strategy.close()
            self._ldap_conn = None

    def __repr__(self):
        return '<User username={} user_type={} permissions={}>'.format(
            self.username, self.user_type, self.permissions)

    def as_dict(self) -> dict:
        """Return a representation of the user data as a dict"""
        return {
            'username': self.username,
            'user_type': self.user_type,
            'external_id': self.external_id,
            'created_at': timestamp.isoformat(self.created_at),
            'last_seen_at': timestamp.isoformat(self.last_seen_at),
            'email_address': self.email_address,
            'display_name': self.display_name,
            'groups': [g.name for g in self.groups],
            'password': self._application.encrypt_value(
                '' if self.password is None else self.password),
            'permissions': self.permissions,
            'last_refreshed_at': timestamp.isoformat(self.last_refreshed_at),
            'integrations': sorted({
                app.name for app in self.connected_integrations}),
        }

    async def authenticate(self) -> bool:
        """Validate that the current session is valid. Returns boolean
        if successful.

        """
        if self.token:
            return await self._token_auth()
        result = await self._db_auth()
        if not result and self._ldap.is_enabled:
            return await self._ldap_auth()
        return result

    def has_permission(self, value: str) -> bool:
        """Check all of the permissions assigned to the user, returning
        `True` if the role is assigned through any group memberships

        :param value: The role to check for

        """
        return value in self.permissions

    @staticmethod
    def on_postgres_error(_metric_name: str, exc: Exception) -> None:
        raise web.HTTPError(500, 'System error')

    @classmethod
    def on_token_postgres_error(cls, metric_name: str, exc: Exception) -> None:
        """Pass InvalidTextRepresentation exceptions through."""
        if isinstance(exc, psycopg2.errors.InvalidTextRepresentation):
            raise exc
        return cls.on_postgres_error(metric_name, exc)

    async def refresh(self) -> None:
        """Update the attributes from LDAP"""
        if self.external_id and self._ldap.is_enabled:
            await self._ldap_refresh()
        else:
            await self._db_refresh()

    @property
    def should_refresh(self) -> bool:
        """Returns True if the amount of time that has passed since the last
        refresh has exceeded the threshold.

        """
        age = timestamp.age(self.last_refreshed_at)
        LOGGER.debug('Last refresh: %s < %s == %s, %s < %s == %s',
                     self.REFRESH_AFTER, age, self.REFRESH_AFTER < age,
                     self.last_refreshed_at, self.last_seen_at,
                     self.last_refreshed_at < self.last_seen_at)
        return ((self.REFRESH_AFTER < age) or
                (self.last_refreshed_at < self.last_seen_at))

    async def update_last_seen_at(self) -> None:
        """Update the last_seen_at column in the database for the user"""
        async with self._application.postgres_connector(
                on_error=self.on_postgres_error) as conn:
            result = await conn.execute(
                self.SQL_UPDATE_LAST_SEEN_AT,
                {'username': self.username},
                'user-update-last-seen-at')
            self.last_seen_at = result.row['last_seen_at']

    async def fetch_integration_tokens(self, integration: str) \
            -> typing.List[oauth2.IntegrationToken]:
        """Retrieve access tokens for the specified integration."""
        obj = await oauth2.OAuth2Integration.by_name(
            self._application, integration)
        return await obj.get_user_tokens(self)

    def _assign_values(self, data: dict) -> None:
        """Assign values from the cursor row to the instance"""
        for key, value in data.items():
            setattr(self, key, value)

    async def _db_auth(self) -> bool:
        """Validate via the v1.users table in the database"""
        LOGGER.debug('Authenticating with the database')
        async with self._application.postgres_connector(
                on_error=self.on_postgres_error) as conn:
            password = None
            if self.password is not None:
                password = self._application.hash_password(self.password)
            result = await conn.execute(
                self.SQL_AUTHENTICATE,
                {'username': self.username, 'password': password},
                'user-authenticate')
            if not result.row_count:
                self._reset()
                return False
        await self._db_refresh()
        return True

    async def _db_groups(self) -> typing.List[Group]:
        """Return the groups for the user as a list of group objects"""
        async with self._application.postgres_connector(
                on_error=self.on_postgres_error) as conn:
            result = await conn.execute(
                self.SQL_GROUPS, {'username': self.username},
                'user-groups')
            return [Group(**r) for r in result]

    async def _db_refresh(self) -> None:
        """Fetch the latest values from the database"""
        async with self._application.postgres_connector(
                on_error=self.on_postgres_error) as conn:
            result = await conn.execute(
                self.SQL_REFRESH, {'username': self.username},
                'user-refresh')
        if result:
            self._assign_values(result.row)
            self.groups = await self._db_groups()
            self.permissions = sorted(set(
                chain.from_iterable([g.permissions for g in self.groups])))
            self.connected_integrations = await self._refresh_integrations()
            self.last_refreshed_at = max(
                timestamp.utcnow(), self.last_seen_at or timestamp.utcnow())
        else:
            self._reset()

    async def _ldap_auth(self) -> bool:
        """Authenticate via LDAP"""
        if not self.password:
            LOGGER.debug('Can not LDAP authenticate without a password')
            return False
        LOGGER.debug('Authenticating via LDAP')
        if not self._ldap_conn:
            self._ldap_conn = await self._ldap.connect(self.username,
                                                       self.password)
        if self._ldap_conn:
            LOGGER.debug('Authenticated as %s', self.username)
            self.user_type = 'ldap'
            result = self._ldap_conn.extend.standard.who_am_i()
            self.external_id = result[3:].strip()
            await self._ldap_refresh()
            return True
        self._reset()
        return False

    async def _ldap_refresh(self) -> None:
        """Update the attributes from LDAP"""
        LOGGER.debug('Refreshing attributes from LDAP server')
        attrs = await self._ldap.attributes(self._ldap_conn, self.external_id)
        LOGGER.debug('Attributes: %r', attrs)
        self.display_name = attrs.get('displayName', attrs['cn'])
        self.email_address = attrs.get('mail')

        async with self._application.postgres_connector(
                on_error=self.on_postgres_error) as conn:
            result = await conn.execute(
                self.SQL_UPDATE_USER_FROM_LDAP,
                {
                    'username': self.username,
                    'user_type': 'ldap',
                    'external_id': self.external_id,
                    'display_name': self.display_name,
                    'email_address': self.email_address
                }, 'user-update')
            self.last_seen_at = result.row['last_seen_at']

        # Update the groups in the database and get the group names
        ldap_groups = await self._ldap.groups(self._ldap_conn,
                                              self.external_id)
        async with self._application.postgres_connector(
                on_error=self.on_postgres_error) as conn:
            await conn.callproc(
                'v1.maintain_group_membership_from_ldap_groups',
                (self.username, ldap_groups),
                'user-maintain-groups')

        # Update the groups attribute
        self.groups = await self._db_groups()
        self.permissions = sorted(set(
            chain.from_iterable([g.permissions for g in self.groups])))
        self.connected_integrations = await self._refresh_integrations()
        self.last_refreshed_at = max(timestamp.utcnow(), self.last_seen_at)

    async def _refresh_integrations(self) -> typing.Sequence[
            ConnectedIntegration]:
        """Fetch connected integration details from the DB."""
        async with self._application.postgres_connector(
                on_error=self.on_postgres_error) as conn:
            result = await conn.execute(
                self.SQL_INTEGRATIONS, {'username': self.username})
            return [ConnectedIntegration(**r) for r in result]

    def _reset(self) -> None:
        """Reset the internally assigned values associated with this user
        object.

        """
        self._ldap_conn = None
        self.created_at = None
        self.last_seen_at = None
        self.user_type = 'internal'
        self.external_id = None
        self.email_address = None
        self.display_name = None
        self.groups = []
        self.permissions = []
        self.last_refreshed_at = None
        self.connected_integrations = []

    async def _token_auth(self) -> bool:
        """Validate via v1.authentication_tokens table"""
        LOGGER.debug('Authenticating with token: %s', self.token)
        async with self._application.postgres_connector(
                on_error=self.on_token_postgres_error) as conn:
            try:
                result = await conn.execute(
                    self.SQL_AUTHENTICATE_TOKEN, {'token': self.token},
                    'user-token-auth')
            except psycopg2.errors.InvalidTextRepresentation:
                return False
            if not result.row_count:
                return False
            self._assign_values(result.row)
        await self._db_refresh()
        return True
