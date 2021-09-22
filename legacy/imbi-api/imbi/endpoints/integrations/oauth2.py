import re

from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):

    NAME = 'integrations'
    ITEM_NAME = 'integration'
    ID_KEY = 'name'
    FIELDS = ['name', 'api_endpoint', 'callback_url', 'authirization_endpoint',
              'token_endpoint', 'revoke_endpoint', 'client_id',
              'client_secret', 'public_client']

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT name, api_endpoint, callback_url, authorization_endpoint,
               token_endpoint, revoke_endpoint, client_id
          FROM v1.oauth2_integrations
         ORDER BY "name" ASC""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.oauth2_integrations
                    (name, api_endpoint, callback_url, authorization_endpoint,
                     token_endpoint, revoke_endpoint, client_id, client_secret,
                     public_client)
             VALUES (%(name)s, %(api_endpoint)s, %(callback_url)s,
                     %(authorization_endpoint)s, %(token_endpoint)s,
                     %(revoke_endpoint)s, %(client_id)s, %(client_secret)s,
                     %(public_client)s)
          RETURNING name""")

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT name, api_endpoint, callback_url, authorization_endpoint,
               token_endpoint, revoke_endpoint, client_id
          FROM v1.oauth2_integrations
         WHERE name = %(name)s""")


class RecordRequestHandler(base.CRUDRequestHandler):

    NAME = 'integration'
    ID_KEY = 'name'

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT name, api_endpoint, callback_url, authorization_endpoint,
               token_endpoint, revoke_endpoint, client_id
          FROM v1.oauth2_integrations
         WHERE name = %(name)s""")

    DELETE_SQL = re.sub(r'\s+', ' ', """\
        DELETE FROM v1.oauth2_integrations WHERE name = %(name)s""")
