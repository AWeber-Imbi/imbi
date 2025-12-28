import re

from imbi.endpoints import base


class _RequestHandlerMixin:

    ID_KEY = 'id'
    FIELDS = [
        'id', 'fact_type_id', 'integration_name', 'notification_name',
        'input_value', 'output_value'
    ]


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):
    NAME = 'notification-rule-transformations'
    ITEM_NAME = 'notification-rule-transformation'
    ID_KEY = ['integration_name', 'notification_name', 'fact_type_id']

    COLLECTION_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT fact_type_id, integration_name, notification_name, input_value,
               output_value, created_at, created_by, last_modified_at,
               last_modified_by
          FROM v1.notification_rule_transformations
         WHERE integration_name = %(integration_name)s
           AND notification_name = %(notification_name)s
           AND fact_type_id = %(fact_type_id)s
         ORDER BY input_value
        """)

    POST_SQL = re.sub(
        r'\s+', ' ', """\
    INSERT INTO v1.notification_rule_transformations
                (fact_type_id, integration_name, notification_name,
                 input_value, output_value, created_at, created_by)
         VALUES (%(fact_type_id)s, %(integration_name)s, %(notification_name)s,
                 %(input_value)s, %(output_value)s, CURRENT_TIMESTAMP,
                 %(username)s)
      RETURNING fact_type_id, integration_name, notification_name, input_value,
                output_value, created_at, created_by
    """)

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT id, fact_type_id, integration_name, notification_name,
               input_value, output_value, created_at, created_by,
               last_modified_at, last_modified_by
          FROM v1.notification_rule_transformations
         WHERE fact_type_id = %(fact_type_id)s
           AND integration_name = %(integration_name)s
           AND notification_name = %(notification_name)s
           AND input_value = %(input_value)s
        """)

    @base.require_permission('admin')
    async def post(self, *args, **kwargs) -> None:
        await super().post(*args, **kwargs)


class RecordRequestHandler(_RequestHandlerMixin, base.CRUDRequestHandler):
    NAME = 'notification-rule-transformation'

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT id, fact_type_id, integration_name, notification_name,
               input_value, output_value, created_at, created_by,
               last_modified_at, last_modified_by
          FROM v1.notification_rule_transformations
         WHERE id = %(id)s
        """)

    PATCH_SQL = re.sub(
        r'\s+', ' ', """\
        UPDATE v1.notification_rule_transformations
           SET output_value = %(output_value)s,
               last_modified_at = CURRENT_TIMESTAMP,
               last_modified_by = %(username)s
         WHERE id = %(id)s
        """)

    DELETE_SQL = re.sub(
        r'\s+', ' ', """\
        DELETE FROM v1.notification_rule_transformations
         WHERE id = %(id)s
        """)

    @base.require_permission('admin')
    async def delete(self, *args, **kwargs) -> None:
        await super().delete(*args, **kwargs)

    @base.require_permission('admin')
    async def patch(self, *args, **kwargs) -> None:
        await super().patch(*args, **kwargs)
