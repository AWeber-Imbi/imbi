import re

from imbi.endpoints import base, projects


class _RequestMixin:

    ID_KEY = ['project_id', 'environment']
    ITEM_NAME = 'project-url'
    FIELDS = ['project_id', 'environment', 'url']
    TTL = 300

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT project_id,
               environment,
               created_at,
               created_by,
               last_modified_at,
               last_modified_by,
               url
          FROM v1.project_urls
         WHERE project_id = %(project_id)s
           AND environment = %(environment)s""")


class CollectionRequestHandler(projects.ProjectAttributeCollectionMixin,
                               _RequestMixin,
                               base.CollectionRequestHandler):

    NAME = 'project-urls'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT project_id,
               environment,
               created_at,
               created_by,
               last_modified_at,
               last_modified_by,
               url
          FROM v1.project_urls
         WHERE project_id = %(project_id)s
         ORDER BY environment""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.project_urls
                    (project_id, environment, created_by, url)
             VALUES (%(project_id)s, %(environment)s, %(username)s, %(url)s)
          RETURNING project_id, environment""")


class RecordRequestHandler(projects.ProjectAttributeCRUDMixin,
                           _RequestMixin, base.CRUDRequestHandler):

    NAME = 'project-url'

    DELETE_SQL = re.sub(r'\s+', ' ', """\
        DELETE FROM v1.project_urls
              WHERE project_id = %(project_id)s
                AND environment = %(environment)s""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.project_urls
           SET url=%(url)s,
               last_modified_at=CURRENT_TIMESTAMP,
               last_modified_by=%(username)s
         WHERE project_id = %(project_id)s
           AND environment = %(environment)s""")
