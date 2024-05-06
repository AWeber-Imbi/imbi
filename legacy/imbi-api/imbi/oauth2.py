import dataclasses
import logging
import re
import typing

import yarl

from imbi import errors
if typing.TYPE_CHECKING:
    from imbi import app, user

LOGGER = logging.getLogger(__name__)
UNSET_URL = yarl.URL()


@dataclasses.dataclass
class IntegrationToken:
    integration: 'OAuth2Integration'
    access_token: str
    refresh_token: typing.Optional[str]
    id_token: typing.Optional[str]
    external_id: str


class OAuth2Integration:
    SQL_REFRESH = re.sub(
        r'\s+', ' ', """\
        SELECT api_endpoint, authorization_endpoint, token_endpoint,
               revoke_endpoint, client_id, client_secret, public_client,
               callback_url
          FROM v1.oauth2_integrations
         WHERE name = %(name)s""")

    SQL_UPSERT_TOKENS = re.sub(
        r'\s+', ' ', """\
        INSERT INTO v1.user_oauth2_tokens(username, integration, external_id,
                                          access_token, refresh_token,
                                          id_token)
             VALUES (%(username)s, %(integration)s, %(external_id)s,
                     %(access_token)s, %(refresh_token)s, %(id_token)s)
        ON CONFLICT (integration, external_id)
      DO UPDATE SET access_token = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    id_token = EXCLUDED.id_token""")

    SQL_UPDATE_TOKENS = re.sub(
        r'\s+', ' ', """
           UPDATE v1.user_oauth2_tokens
              SET access_token = %(access_token)s,
                  id_token = %(id_token)s,
                  username = %(username)s
            WHERE integration = %(integration)s
              AND external_id = %(external_id)s
        """)

    SQL_GET_TOKENS = re.sub(
        r'\s+', ' ', """\
        SELECT access_token, refresh_token, id_token, external_id
          FROM v1.user_oauth2_tokens
         WHERE username = %(username)s
           AND integration = %(integration)s""")

    def __init__(self, application: 'app.Application', name: str) -> None:
        self._application = application
        self.logger = LOGGER.getChild(self.__class__.__name__)
        self.name = name
        self.authorization_endpoint: yarl.URL = UNSET_URL
        self.api_endpoint: typing.Optional[yarl.URL] = None
        self.token_endpoint: yarl.URL = UNSET_URL
        self.revoke_endpoint: typing.Optional[yarl.URL] = None
        self.client_id: str = ''
        self.client_secret: str = ''
        self.public_client: bool = True
        self.callback_url: typing.Optional[yarl.URL] = UNSET_URL

    @classmethod
    async def by_name(cls, application: 'app.Application',
                      name: str) -> typing.Optional['OAuth2Integration']:
        instance = cls(application, name)
        await instance.refresh()
        return instance if instance.is_valid else None

    async def refresh(self) -> None:
        async with self._application.postgres_connector(
                on_error=self._on_postgres_error) as conn:
            result = await conn.execute(self.SQL_REFRESH, {'name': self.name})

        if result:
            self.authorization_endpoint = yarl.URL(
                result.row['authorization_endpoint'])
            self.token_endpoint = yarl.URL(result.row['token_endpoint'])
            self.client_id = result.row['client_id']
            self.client_secret = result.row['client_secret']
            self.public_client = result.row['public_client']

            if result.row['api_endpoint']:
                self.api_endpoint = yarl.URL(result.row['api_endpoint'])
            else:
                self.api_endpoint = None

            if result.row['revoke_endpoint']:
                self.revoke_endpoint = yarl.URL(result.row['revoke_endpoint'])
            else:
                self.revoke_endpoint = None

            if result.row['callback_url']:
                self.callback_url = yarl.URL(result.row['callback_url'])
            else:
                self.callback_url = None
        else:
            self._reset()

    async def upsert_user_tokens(
            self,
            username: str,
            external_id: str,
            access_token: str,
            refresh_token: typing.Optional[str] = None,
            id_token: typing.Optional[str] = None) -> None:
        async with self._application.postgres_connector(
                on_error=self._on_postgres_error) as conn:
            if refresh_token:
                await conn.execute(
                    self.SQL_UPSERT_TOKENS, {
                        'integration': self.name,
                        'username': username,
                        'external_id': external_id,
                        'access_token': access_token,
                        'refresh_token': refresh_token,
                        'id_token': id_token
                    })
            else:
                await conn.execute(
                    self.SQL_UPDATE_TOKENS, {
                        'integration': self.name,
                        'username': username,
                        'external_id': external_id,
                        'access_token': access_token,
                        'id_token': id_token
                    })

    async def get_user_tokens(self, user_info: 'user.User') \
            -> list[IntegrationToken]:
        async with self._application.postgres_connector(
                on_error=self._on_postgres_error) as conn:
            result = await conn.execute(self.SQL_GET_TOKENS, {
                'integration': self.name,
                'username': user_info.username
            })
        return [
            IntegrationToken(self, row['access_token'], row['refresh_token'],
                             row['id_token'], row['external_id'])
            for row in result
        ]

    @property
    def is_valid(self) -> bool:
        return (self.authorization_endpoint != UNSET_URL
                and self.token_endpoint != UNSET_URL and self.client_id
                and (self.client_secret or self.public_client))

    @staticmethod
    def _on_postgres_error(_metric_name: str, exc: Exception) -> None:
        raise errors.DatabaseError(error=exc)

    def _reset(self) -> None:
        self.api_endpoint = None
        self.authorization_endpoint = UNSET_URL
        self.callback_url = UNSET_URL
        self.token_endpoint = UNSET_URL
        self.revoke_endpoint = None
        self.client_id = ''
        self.client_secret = ''
        self.public_client = True
