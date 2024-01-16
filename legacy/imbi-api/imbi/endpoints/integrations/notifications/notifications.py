from __future__ import annotations

import re

from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):
    NAME = 'notifications'
    ITEM_NAME = 'notification'
    ID_KEY = ['integration_name', 'name']
    FIELDS = []

    COLLECTION_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT notification_name AS name, integration_name, id_pattern,
               documentation, default_action, created_at, created_by,
               last_modified_at, last_modified_by
          FROM v1.integration_notifications
         WHERE integration_name = %(integration_name)s
         ORDER BY name
        """)

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT notification_name AS name, integration_name, id_pattern,
               documentation, default_action, created_at, created_by,
               last_modified_at, last_modified_by
          FROM v1.integration_notifications
         WHERE integration_name = %(integration_name)s
           AND notification_name = %(name)s
        """)

    POST_SQL = re.sub(
        r'\s+', ' ', """\
        INSERT INTO v1.integration_notifications
                    (notification_name, integration_name, id_pattern,
                     documentation, default_action, verification_token,
                     created_at, created_by)
             VALUES (%(name)s, %(integration_name)s, %(id_pattern)s,
                     %(documentation)s, %(default_action)s,
                     %(verification_token)s, CURRENT_TIMESTAMP, %(username)s)
          RETURNING notification_name AS name, integration_name, id_pattern,
                    documentation, default_action
        """)

    @base.require_permission('admin')
    async def post(self, *args, **kwargs) -> None:
        await super().post(*args, **kwargs)


class RecordRequestHandler(base.CRUDRequestHandler):
    NAME = 'notification'
    ID_KEY = ['integration_name', 'name']
    OMIT_FIELDS = ['verification_token']

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT notification_name AS name, integration_name, id_pattern,
               documentation, verification_token, default_action,
               created_at, created_by, last_modified_at, last_modified_by
          FROM v1.integration_notifications
         WHERE notification_name = %(name)s
           AND integration_name = %(integration_name)s
        """)

    PATCH_SQL = re.sub(
        r'\s+', ' ', """\
        UPDATE v1.integration_notifications
           SET default_action = %(default_action)s,
               documentation = %(documentation)s,
               id_pattern = %(id_pattern)s,
               last_modified_at = CURRENT_TIMESTAMP,
               last_modified_by = %(username)s,
               notification_name = %(name)s,
               verification_token = %(verification_token)s
         WHERE notification_name = %(current_name)s
           AND integration_name = %(integration_name)s
        """)

    DELETE_SQL = re.sub(
        r'\s+', ' ', """\
        DELETE FROM v1.integration_notifications
         WHERE notification_name = %(name)s
           AND integration_name = %(integration_name)s
        """)

    @base.require_permission('admin')
    async def delete(self, *args, **kwargs) -> None:
        await super().delete(*args, **kwargs)

    @base.require_permission('admin')
    async def patch(self, *args, **kwargs) -> None:
        await super().patch(*args, **kwargs)
