import re

import celpy

from imbi import errors
from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):
    NAME = 'notification-rules'
    ITEM_NAME = 'notification-rule'
    ID_KEY = ['integration_name', 'notification_name', 'fact_type_id']
    FIELDS = []

    COLLECTION_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT fact_type_id, integration_name, notification_name, pattern,
               filter_expression, created_at, created_by, last_modified_at,
               last_modified_by
          FROM v1.notification_rules
         WHERE integration_name = %(integration_name)s
           AND notification_name = %(notification_name)s
         ORDER BY fact_type_id
        """)

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT fact_type_id, integration_name, notification_name, pattern,
               filter_expression, created_at, created_by, last_modified_at,
               last_modified_by
          FROM v1.notification_rules
         WHERE integration_name = %(integration_name)s
           AND notification_name = %(notification_name)s
           AND fact_type_id = %(fact_type_id)s
        """)

    POST_SQL = re.sub(
        r'\s+', ' ', """\
    INSERT INTO v1.notification_rules
                (fact_type_id, integration_name, notification_name, pattern,
                 filter_expression, created_at, created_by)
         VALUES (%(fact_type_id)s, %(integration_name)s,
                 %(notification_name)s, %(pattern)s, %(filter_expression)s,
                 CURRENT_TIMESTAMP, %(username)s)
      RETURNING fact_type_id, integration_name, notification_name, pattern,
                filter_expression
    """)

    @base.require_permission('admin')
    async def post(self, *args, **kwargs) -> None:
        body = self.get_request_body()

        # Validate CEL expression if provided
        if body.get('filter_expression'):
            try:
                env = celpy.Environment()
                env.compile(body['filter_expression'])
            except Exception as error:
                raise errors.BadRequest('Invalid CEL expression: %s',
                                        str(error))

        await super().post(*args, **kwargs)


class RecordRequestHandler(base.CRUDRequestHandler):
    NAME = 'notification-rule'
    ID_KEY = ['integration_name', 'notification_name', 'fact_type_id']

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT fact_type_id, integration_name, notification_name, pattern,
               filter_expression, created_at, created_by, last_modified_at,
               last_modified_by
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
               filter_expression = %(filter_expression)s,
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
        body = self.get_request_body()

        if body.get('filter_expression'):
            try:
                env = celpy.Environment()
                env.compile(body['filter_expression'])
            except Exception as error:
                raise errors.BadRequest('Invalid CEL expression: %s',
                                        str(error))

        await super().patch(*args, **kwargs)
