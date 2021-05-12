from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):
    NAME = 'integrations'
    ITEM_NAME = 'integration'

    COLLECTION_SQL = """\
        SELECT name, api_endpoint, callback_url, authorization_endpoint,
               token_endpoint, revoke_endpoint, client_id
          FROM v1.oauth_integrations
         ORDER BY "name" ASC"""


class RecordRequestHandler(base.CRUDRequestHandler):
    NAME = 'integration'
    ID_KEY = 'name'

    GET_SQL = """\
        SELECT name, api_endpoint, callback_url, authorization_endpoint,
               token_endpoint, revoke_endpoint, client_id
          FROM v1.oauth_integrations
         WHERE name = %(name)s"""
