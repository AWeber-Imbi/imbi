import re

from imbi.endpoints import base


class _RequestHandlerMixin:

    ID_KEY = 'id'
    FIELDS = ['id', 'role_arn', 'environment', 'namespace_id']

    GET_SQL = re.sub(
        r'\s+', ' ', """\
            SELECT id, role_arn, environment, namespace_id,
                   created_at, created_by
              FROM v1.aws_roles
             WHERE id = %(id)s""")


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):

    NAME = 'aws-roles'
    ITEM_NAME = 'aws-role'

    COLLECTION_SQL = re.sub(
        r'\s+', ' ', """ \
        SELECT id, role_arn, environment, namespace_id, created_at, created_by
          FROM v1.aws_roles
      ORDER BY id""")

    POST_SQL = re.sub(
        r'\s+', ' ', """\
    INSERT INTO v1.aws_roles
                (role_arn, environment, namespace_id, created_by)
         VALUES (%(role_arn)s, %(environment)s, %(namespace_id)s,
                 %(username)s)
      RETURNING id""")


class RecordRequestHandler(_RequestHandlerMixin, base.AdminCRUDRequestHandler):

    NAME = 'aws-role'

    DELETE_SQL = re.sub(
        r'\s+', ' ', """\
        DELETE FROM v1.aws_roles
         WHERE id = %(id)s""")

    PATCH_SQL = re.sub(
        r'\s+', ' ', """\
        UPDATE v1.aws_roles
           SET role_arn = %(role_arn)s,
               environment = %(environment)s,
               namespace_id = %(namespace_id)s
         WHERE id = %(id)s""")
