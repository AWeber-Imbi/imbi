"""
Authenticated User Session

"""
import json
import logging
import uuid

from imbi import common, timestamp, user

LOGGER = logging.getLogger(__name__)

DEFAULT_POOL_SIZE = 5


class Session:
    """Session object manages session state and the user object."""

    TTL = 3600

    def __init__(self, handler):
        self._handler = handler
        self.authenticated = False
        self.id = self._get_id_from_cookie() or str(uuid.uuid4())
        self.last_save = None
        self.start = timestamp.isoformat()
        self.user = None

    async def authenticate(self, username, password):
        """Authenticate the user and attach it to the session

        :param str username: The username to authenticate with
        :param str password: The password to use when authenticating

        """
        self.user = user.User(
            self._handler.application, username, password)
        self.authenticated = await self.user.authenticate()
        if not self.authenticated:
            self.user = None
            await self.clear()
            return False
        return True

    async def initialize(self):
        """Used to initialize the data, loading the data if it is set"""
        self.user = await self._load_data()
        if not self.user:
            LOGGER.debug('Session initialized without a user')
            return

        self.authenticated = await self.user.authenticate()
        if not self.authenticated:
            self.user = None
            return

        if self.user.should_refresh:
            await self.user.refresh()
            await self.save()

    async def clear(self):
        """Clear out the currently loaded session by clearing the cookie
        and removing the data from redis.

        """
        LOGGER.debug('Deleting session %s', self.id)
        self._handler.clear_cookie('session')
        await self._redis.delete(self._redis_key)
        self.authenticated = False
        self.last_save = None
        self.start = timestamp.isoformat()
        self.user = None

    async def save(self):
        """Save session data to redis"""
        LOGGER.debug('Saving session %s', self.id)
        user_data = {} if not self.user else self.user.as_dict()
        await self._redis.set(
            self._redis_key,
            json.dumps({
                'user': user_data,
                'last_save': timestamp.isoformat(),
                'start': self.start}),
            expire=self.TTL)
        self._handler.set_secure_cookie('session', self.id)

    def _get_id_from_cookie(self):
        """Get the Session ID from the secure cookie, decoding it from
        UTF-8, if set.

        :rtype: str or None

        """
        value = self._handler.get_secure_cookie('session')
        if value:
            return value.decode('utf-8')

    async def _load_data(self):
        """Load the data from Redis, creating the user object and returning it
        if there was a previously saved user,

        :rtype: User or None
        """
        LOGGER.debug('Loading session %s', self.id)
        result = await self._redis.get(self._redis_key)
        if not result:
            LOGGER.debug('Session not found')
            return False
        data = json.loads(result.decode('utf-8'))
        self.last_save = data['last_save']
        self.start = data['start']
        if not data.get('user'):
            return

        if 'password' in data['user']:
            data['user']['password'] = common.decrypt_value(
                'password', data['user']['password']).decode('utf-8')

        user_obj = user.User(self._handler.application)
        for key, value in data['user'].items():
            setattr(user_obj, key, value)
        return user_obj

    @property
    def _redis(self):
        """Return the handle to the Redis client

        :rtype: aioredis.Redis

        """
        return self._handler.application.session_redis

    @property
    def _redis_key(self):
        """Return the properly formatted session key.

        :rtype: str

        """
        return 'session:{}'.format(self.id)
