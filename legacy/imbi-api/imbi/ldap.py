"""
LDAP Client
===========

"""
import dataclasses
import logging
import typing
from concurrent import futures

import ldap3
from ldap3.core import exceptions

LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass
class Settings:
    enabled: bool
    host: str
    port: int
    ssl: bool
    group_member_attr: str
    group_object_type: str
    groups_dn: str
    user_object_type: str
    users_dn: str
    username: str
    pool_size: int


class Client:
    """LDAP Client used for authenticating users. Expects the following
    configuration in the settings dict:

    - ``enabled``: Enables / Disables LDAP lookup
    - ``host``: The hostname of the server to connect to
    - ``port``: The port to connect on
    - ``ssl``: Indicates whether SSL is enabled for connecting
    - ``group_object_type``: The object type to use for groups
    - ``groups_dn``: The base DN to use for group searching
    - ``group_member_attr``: The group membership attribute used in searching
    - ``user_object_type``: The object type to use for users
    - ``users_dn``: The base DN to use for user searching
    - ``username``: The username attribute used in user searching
    - ``pool_size``: The size to allocate for the ThreadPoolExecutor

    """
    def __init__(self, settings: dict):
        self._settings = Settings(**settings)
        self._executor = futures.ThreadPoolExecutor(
            max_workers=self._settings.pool_size)
        self._server = ldap3.Server(
            self._settings.host, self._settings.port, self._settings.ssl)

    def __exit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        """Shutdown the executor when the class is destroyed"""
        self._executor.shutdown()

    @property
    def is_enabled(self) -> bool:
        """Returns a boolean indicating if LDAP is enabled"""
        return self._settings.enabled

    async def connect(self, username: str, password: str) -> ldap3.Connection:
        """Connect to the LDAP server with the specified username
        and password. Returns a LDAP connection object for use with
        other methods.

        :param username: The username to connect with
        :param password: The password to use
        :raises: RuntimeError

        """
        if not self._settings.enabled:
            raise RuntimeError('LDAP not enabled')
        future = self._executor.submit(self._connect, username, password)
        conn = future.result()
        LOGGER.debug('Connected to %s', conn)
        return conn

    async def attributes(self, conn: ldap3.Connection, dn: str) -> dict:
        """Return the attributes for the specified dn on the given
        connection.

        :param conn: The connection to use
        :param dn: The DN of the user to return the attributes for
        :raises: RuntimeError

        """
        if not self._settings.enabled:
            raise RuntimeError('LDAP not enabled')
        future = self._executor.submit(self._attributes, conn, dn)
        return future.result()

    async def groups(self, conn: ldap3.Connection, dn: str) -> list:
        """Return the names of the groups for the specified username.

        :param conn: The connection to use
        :param dn: The DN of the user to return the groups for
        :raises: RuntimeError

        """
        if not self._settings.enabled:
            raise RuntimeError('LDAP not enabled')
        future = self._executor.submit(self._groups, conn, dn)
        return future.result()

    def _connect(self, username: str, password: str) -> ldap3.Connection:
        """Connect to the LDAP server with the specified username and password.

        :param username: The username to connect as
        :param password: The password to use
        :raises: RuntimeError

        """
        if not self._settings.enabled:
            raise RuntimeError('LDAP not enabled')
        dn = ','.join(['{}={}'.format(self._settings.username, username),
                       self._settings.users_dn])
        LOGGER.debug(
            'Connecting to %s://%s:%s as %s',
            'ldaps' if self._settings.ssl else 'ldap',
            self._settings.host, self._settings.port, dn)
        try:
            return ldap3.Connection(
                self._server, dn, password, auto_bind=True)
        except exceptions.LDAPException as error:
            LOGGER.warning('Authentication error for %s: %s', username, error)

    def _attributes(self, conn: ldap3.Connection, dn: str) -> dict:
        """Return the attributes for the specified username.

        :param conn: The connection to use
        :param dn: The DN of the user to return the groups for

        """
        conn.search(
            dn, '(objectClass={})'.format(self._settings.user_object_type),
            attributes=[ldap3.ALL_ATTRIBUTES,
                        ldap3.ALL_OPERATIONAL_ATTRIBUTES])
        return {k: v[0] if isinstance(v, list) and len(v) == 1 else v
                for k, v in conn.response[0]['attributes'].items()}

    def _groups(self, conn: ldap3.Connection, dn: str) -> typing.List[str]:
        """Return the groups for the specified username.

        :param conn: The connection to use
        :param dn: The DN of the user to return the groups for

        """
        query = '(&(objectClass={})({}={}))'.format(
            self._settings.group_object_type,
            self._settings.group_member_attr, dn)
        LOGGER.debug('User groups query: %r', query)
        conn.search(self._settings.groups_dn, query)
        groups = set({})
        for entry in conn.response:
            groups.add(str(entry['dn']))
        return sorted(groups)
