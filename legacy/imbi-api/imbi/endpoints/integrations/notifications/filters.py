import re

from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):
    NAME = 'notification-filters'
    ITEM_NAME = 'notification-filter'
    ID_KEY = ['integration_name', 'notification_name', 'name']
    FIELDS = []

    COLLECTION_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT filter_name AS name, integration_name, notification_name,
               pattern, operation, value, action, created_at, created_by,
               last_modified_at, last_modified_by
          FROM v1.notification_filters
         WHERE integration_name = %(integration_name)s
           AND notification_name = %(notification_name)s
         ORDER BY name
        """)

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT filter_name AS name, integration_name, notification_name,
               pattern, operation, value, action, created_at, created_by,
               last_modified_at, last_modified_by
          FROM v1.notification_filters
         WHERE integration_name = %(integration_name)s
           AND notification_name = %(notification_name)s
           AND filter_name = %(name)s
        """)

    POST_SQL = re.sub(
        r'\s+', ' ', """\
    INSERT INTO v1.notification_filters
                (filter_name, integration_name, notification_name, pattern,
                 operation, value, action, created_at, created_by)
         VALUES (%(name)s, %(integration_name)s, %(notification_name)s,
                 %(pattern)s, %(operation)s, %(value)s, %(action)s,
                 CURRENT_TIMESTAMP, %(username)s)
      RETURNING filter_name AS name, integration_name, notification_name,
                pattern, operation, value, action
    """)

    @base.require_permission('admin')
    async def post(self, *args, **kwargs) -> None:
        await super().post(*args, **kwargs)


class RecordRequestHandler(base.CRUDRequestHandler):
    NAME = 'notification-filter'
    ID_KEY = ['integration_name', 'notification_name', 'name']

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT filter_name AS name, integration_name, notification_name,
               pattern, operation, value, action, created_at, created_by,
               last_modified_at, last_modified_by
          FROM v1.notification_filters
         WHERE integration_name = %(integration_name)s
           AND notification_name = %(notification_name)s
           AND filter_name = %(name)s
        """)

    PATCH_SQL = re.sub(
        r'\s+', ' ', """\
        UPDATE v1.notification_filters
           SET filter_name = %(name)s,
               integration_name = %(integration_name)s,
               notification_name = %(notification_name)s,
               pattern = %(pattern)s,
               operation = %(operation)s,
               value = %(value)s,
               action = %(action)s,
               last_modified_at = CURRENT_TIMESTAMP,
               last_modified_by = %(username)s
         WHERE filter_name = %(current_name)s
           AND integration_name = %(integration_name)s
           AND notification_name = %(notification_name)s
        """)

    DELETE_SQL = re.sub(
        r'\s+', ' ', """\
        DELETE FROM v1.notification_filters
         WHERE filter_name = %(name)s
           AND integration_name = %(integration_name)s
           AND notification_name = %(notification_name)s
        """)

    @base.require_permission('admin')
    async def delete(self, *args, **kwargs) -> None:
        await super().delete(*args, **kwargs)

    @base.require_permission('admin')
    async def patch(self, *args, **kwargs) -> None:
        await super().patch(*args, **kwargs)
