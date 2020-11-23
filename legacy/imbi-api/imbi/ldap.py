"""
LDAP Client
===========

"""
import logging
import os
from concurrent import futures

import ldap3
from ldap3.core import exceptions

from imbi import common

LOGGER = logging.getLogger(__name__)

DEFAULT_GROUP_DN = 'cn=groups,cn=accounts,dc=imbi,dc=tld'
DEFAULT_GROUP_OT = 'groupOfNames'
DEFAULT_MEMBER_ATTR = 'member'
DEFAULT_USER_DN = 'cn=groups,cn=accounts,dc=imbi,dc=tld'
DEFAULT_USER_OT = 'inetOrgPerson'
DEFAULT_USERNAME = 'uid'
DEFAULT_POOL_SIZE = 5


class Client:
    """LDAP Client used for authenticating users. Respects the following
    environment variables for configuration:

    - ``LDAP_ENABLED``: Enables / Disables LDAP lookup
    - ``LDAP_HOST``: The hostname of the server to connect to
    - ``LDAP_PORT``: The port to connect on
    - ``LDAP_SSL``: Indicates whether SSL is enabled for connecting
    - ``LDAP_GROUP_OT``: The object type to use for groups
    - ``LDAP_GROUPS_DN``: The base DN to use for group searching
    - ``LDAP_MEMBER_ATTR``: The group membership attribute used in searching
    - ``LDAP_USER_OT``: The object type to use for users
    - ``LDAP_USERS_DN``: The base DN to use for user searching
    - ``LDAP_USERNAME``: The username attribute used in user searching
    - ``LDAP_POOL_SIZE``: The size to allocate for the ThreadPoolExecutor

    """
    def __init__(self):
        self._enabled = common.ldap_enabled()
        self._executor = futures.ThreadPoolExecutor(
            max_workers=int(os.environ.get(
                'LDAP_POOL_SIZE', DEFAULT_POOL_SIZE)))
        self._host = os.environ.get('LDAP_HOST', 'localhost')
        self._port = int(os.environ.get('LDAP_PORT', '386'))
        self._ssl = os.environ.get('LDAP_SSL', 'FALSE').lower() == 'true'
        self._group_dn = os.environ.get('LDAP_GROUPS_DN', DEFAULT_GROUP_DN)
        self._user_dn = os.environ.get('LDAP_USERS_DN', DEFAULT_USER_DN)
        self._username = os.environ.get('LDAP_USERNAME', DEFAULT_USERNAME)
        self._server = ldap3.Server(self._host, self._port, self._ssl)

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        """Shutdown the executor when the class is destroyed"""
        self._executor.shutdown()

    @property
    def is_enabled(self):
        """Returns a boolean indicating if LDAP is enabled.

        :rtype: bool

        """
        return self._enabled

    async def connect(self, username, password):
        """Connect to the LDAP server with the specified username
        and password. Returns a LDAP connection object for use with
        other methods.

        :param str username: The username to connect with
        :param str password: The password to use
        :rtype: ldap3.Connection or None
        :raises: RuntimeError

        """
        if not self._enabled:
            raise RuntimeError('LDAP not enabled')
        future = self._executor.submit(self._connect, username, password)
        conn = future.result()
        LOGGER.debug('Connected to %s', conn)
        return conn

    async def attributes(self, conn, dn):
        """Return the attributes for the specified dn on the given
        connection.

        :param ldap3.Connection conn: The connection to use
        :param str dn: The DN of the user to return the groups for
        :rtype: ldap3.abstract.cursor.Cursor
        :raises: RuntimeError

        """
        if not self._enabled:
            raise RuntimeError('LDAP not enabled')

        future = self._executor.submit(self._attributes, conn, dn)
        return future.result()

    async def groups(self, conn, dn):
        """Return the names of the groups for the specified username.

        :param ldap3.Connection conn: The connection to use
        :param str dn: The DN of the user to return the groups for
        :rtype: list
        :raises: RuntimeError

        """
        if not self._enabled:
            raise RuntimeError('LDAP not enabled')
        future = self._executor.submit(self._groups, conn, dn)
        return future.result()

    def _connect(self, username, password):
        """Connect to the LDAP server with the specified username and password.

        @TODO I'd like to see this done more cleanly

        :param str username: The username to connect as
        :param str password: The password to use
        :rtype: ldap3.Connection or None
        :raises: RuntimeError

        """
        if not self._enabled:
            raise RuntimeError('LDAP not enabled')
        dn = ','.join(['{}={}'.format(self._username, username),
                       self._user_dn])
        LOGGER.debug('Connecting to %s://%s:%s as %s',
                     'ldaps' if self._ssl else 'ldap',
                     self._host, self._port, dn)
        try:
            return ldap3.Connection(
                self._server, dn, password, auto_bind=True)
        except exceptions.LDAPException as error:
            LOGGER.warning('Authentication error for %s: %s', username, error)

    def _attributes(self, conn, dn):
        """Return the attributes for the specified username.

        :param ldap3.Connection conn: The connection to use
        :param str dn: The DN of the user to return the groups for
        :rtype: dict

        """
        conn.search(
            dn, '(objectClass={})'.format(
                os.environ.get('LDAP_USER_OT', DEFAULT_USER_OT)),
            attributes=[ldap3.ALL_ATTRIBUTES,
                        ldap3.ALL_OPERATIONAL_ATTRIBUTES])
        return {k: v[0] if isinstance(v, list) and len(v) == 1 else v
                for k, v in conn.response[0]['attributes'].items()}

    def _groups(self, conn, dn):
        """Return the attributes for the specified username.

        :param ldap3.Connection conn: The connection to use
        :param str dn: The DN of the user to return the groups for
        :rtype: list

        """
        query = '(&(objectClass={})({}={}))'.format(
            os.environ.get('LDAP_GROUP_OT', DEFAULT_GROUP_OT),
            os.environ.get('LDAP_MEMBER_ATTR', DEFAULT_MEMBER_ATTR), dn)
        LOGGER.debug('User groups query: %r', query)
        conn.search(self._group_dn, query)
        groups = set({})
        for entry in conn.response:
            groups.add(str(entry['dn']))
        return sorted(groups)
