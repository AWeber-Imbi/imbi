import re

from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):
    NAME = 'notification-rules'
    ITEM_NAME = 'notification-rule'
    ID_KEY = ['integration_name', 'notification_name', 'fact_type_id']
    FIELDS = []

    COLLECTION_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT fact_type_id, integration_name, notification_name, pattern,
               created_at, created_by, last_modified_at, last_modified_by
          FROM v1.notification_rules
         WHERE integration_name = %(integration_name)s
           AND notification_name = %(notification_name)s
         ORDER BY fact_type_id
        """)

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT fact_type_id, integration_name, notification_name, pattern,
               created_at, created_by, last_modified_at, last_modified_by
          FROM v1.notification_rules
         WHERE integration_name = %(integration_name)s
           AND notification_name = %(notification_name)s
           AND fact_type_id = %(fact_type_id)s
        """)

    POST_SQL = re.sub(
        r'\s+', ' ', """\
    INSERT INTO v1.notification_rules
                (fact_type_id, integration_name, notification_name, pattern,
                 created_at, created_by)
         VALUES (%(fact_type_id)s, %(integration_name)s, %(notification_name)s,
                 %(pattern)s, CURRENT_TIMESTAMP, %(username)s)
      RETURNING fact_type_id, integration_name, notification_name, pattern
    """)

    @base.require_permission('admin')
    async def post(self, *args, **kwargs) -> None:
        await super().post(*args, **kwargs)


class RecordRequestHandler(base.CRUDRequestHandler):
    NAME = 'notification-rule'
    ID_KEY = ['integration_name', 'notification_name', 'fact_type_id']

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT fact_type_id, integration_name, notification_name, pattern,
               created_at, created_by, last_modified_at, last_modified_by
          FROM v1.notification_rules
         WHERE integration_name = %(integration_name)s
           AND notification_name = %(notification_name)s
           AND fact_type_id = %(fact_type_id)s
        """)

    PATCH_SQL = re.sub(
        r'\s+', ' ', """\
        UPDATE v1.notification_rules
           SET fact_type_id = %(fact_type_id)s,
               integration_name = %(integration_name)s,
               notification_name = %(notification_name)s,
               pattern = %(pattern)s,
               last_modified_at = CURRENT_TIMESTAMP,
               last_modified_by = %(username)s
         WHERE fact_type_id = %(current_fact_type_id)s
           AND integration_name = %(current_integration_name)s
           AND notification_name = %(current_notification_name)s
        """)

    DELETE_SQL = re.sub(
        r'\s+', ' ', """\
        DELETE FROM v1.notification_rules
         WHERE fact_type_id = %(fact_type_id)s
           AND integration_name = %(integration_name)s
           AND notification_name = %(notification_name)s
        """)

    @base.require_permission('admin')
    async def delete(self, *args, **kwargs) -> None:
        await super().delete(*args, **kwargs)

    @base.require_permission('admin')
    async def patch(self, *args, **kwargs) -> None:
        await super().patch(*args, **kwargs)
