import re

from imbi import errors
from imbi.endpoints import base, projects


class CollectionRequestHandler(projects.ProjectAttributeCollectionMixin,
                               base.CollectionRequestHandler):
    NAME = 'project-identifiers'
    ITEM_NAME = 'project-identifier'
    ID_KEY = ['project_id', 'integration_name']
    FIELDS = ['external_id', 'integration_name']

    COLLECTION_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT external_id, integration_name, project_id, created_at,
               created_by, last_modified_at, last_modified_by
          FROM v1.project_identifiers
         WHERE project_id = %(project_id)s
         ORDER BY project_id, integration_name
        """)

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT external_id, integration_name, project_id,
               created_at, created_by, last_modified_at, last_modified_by
          FROM v1.project_identifiers
         WHERE project_id = %(project_id)s
           AND integration_name = %(integration_name)s
        """)

    POST_SQL = re.sub(
        r'\s+', ' ', """\
        INSERT INTO v1.project_identifiers
                    (external_id, integration_name, project_id,
                     created_at, created_by)
             VALUES (%(external_id)s, %(integration_name)s, %(project_id)s,
                     CURRENT_TIMESTAMP, %(username)s)
          RETURNING external_id, integration_name, project_id
        """)

    async def get(self, *args, **kwargs) -> None:
        result = await self.postgres_execute(
            'SELECT id FROM v1.projects WHERE id = %(project_id)s', kwargs,
            'get-project-id')
        if not result:
            raise errors.ItemNotFound()
        await super().get(*args, **kwargs)


class RecordRequestHandler(projects.ProjectAttributeCRUDMixin,
                           base.CRUDRequestHandler):
    NAME = 'project-identifier'
    ID_KEY = ['project_id', 'integration_name']

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT project_id, integration_name, external_id,
               created_at, created_by,
               last_modified_at, last_modified_by
          FROM v1.project_identifiers
         WHERE project_id = %(project_id)s
           AND integration_name = %(integration_name)s
        """)
    PATCH_SQL = re.sub(
        r'\s+', ' ', """\
        UPDATE v1.project_identifiers
           SET external_id = %(external_id)s,
               integration_name = %(integration_name)s,
               last_modified_by = %(username)s,
               last_modified_at = CURRENT_TIMESTAMP
         WHERE project_id = %(current_project_id)s
           AND project_id = %(project_id)s
           AND integration_name = %(current_integration_name)s
        RETURNING external_id
        """)
    DELETE_SQL = re.sub(
        r'\s+', ' ', """\
        DELETE FROM v1.project_identifiers
              WHERE project_id = %(project_id)s
                AND integration_name = %(integration_name)s
        """)
