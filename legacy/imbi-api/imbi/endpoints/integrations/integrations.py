import re

from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):
    NAME = 'integrations'
    ITEM_NAME = 'integration'
    ID_KEY = 'name'
    FIELDS = ['api_endpoint', 'api_secret']

    COLLECTION_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT name, api_endpoint,
               CASE api_secret
                    WHEN NULL THEN NULL
                    ELSE LEFT(api_secret, 3) || '...' || RIGHT(api_secret, 3)
               END AS api_secret
          FROM v1.integrations
         ORDER BY name
        """)

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT name, api_endpoint,
               CASE api_secret
                    WHEN NULL THEN NULL
                    ELSE LEFT(api_secret, 3) || '...' || RIGHT(api_secret, 3)
               END AS api_secret
          FROM v1.integrations
         WHERE name = %(name)s
        """)

    POST_SQL = re.sub(
        r'\s+', ' ', """\
        INSERT INTO v1.integrations
                    (name, api_endpoint, api_secret, created_at, created_by)
             VALUES (%(name)s, %(api_endpoint)s, %(api_secret)s,
                     CURRENT_TIMESTAMP, %(username)s)
          RETURNING name, api_endpoint
        """)

    @base.require_permission('admin')
    async def post(self, *args, **kwargs) -> None:
        await super().post(*args, **kwargs)


class RecordRequestHandler(base.CRUDRequestHandler):
    NAME = 'integration'
    ID_KEY = 'name'

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT name, api_endpoint, created_at, created_by,
               last_modified_at, last_modified_by,
               CASE api_secret
                    WHEN NULL THEN NULL
                    ELSE LEFT(api_secret, 3) || '...' || RIGHT(api_secret, 3)
               END AS api_secret
          FROM v1.integrations
         WHERE name = %(name)s
        """)

    PATCH_SQL = re.sub(
        r'\s+', ' ', """\
        UPDATE v1.integrations
           SET api_endpoint = %(api_endpoint)s,
               api_secret = %(api_secret)s,
               last_modified_by = %(username)s,
               last_modified_at = CURRENT_TIMESTAMP
         WHERE name = %(name)s
           AND name = %(current_name)s
        RETURNING api_endpoint
        """)

    DELETE_SQL = re.sub(
        r'\s+', ' ', """\
           DELETE FROM v1.integrations
                 WHERE name = %(name)s
           """)

    @base.require_permission('admin')
    async def delete(self, *args, **kwargs) -> None:
        await super().delete(*args, **kwargs)

    @base.require_permission('admin')
    async def patch(self, *args, **kwargs) -> None:
        await super().patch(*args, **kwargs)
