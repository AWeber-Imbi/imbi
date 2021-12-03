import re

from imbi.endpoints import base, projects


class _LinkRequestMixin:

    ID_KEY = ['project_id', 'link_type_id']
    ITEM_NAME = 'project-link'
    FIELDS = ['project_id', 'link_type_id', 'url']
    TTL = 300

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT a.project_id,
               a.link_type_id,
               a.created_at,
               a.created_by,
               a.last_modified_at,
               a.last_modified_by,
               b.link_type,
               b.icon_class,
               a.url
          FROM v1.project_links AS a
          JOIN v1.project_link_types AS b
            ON b.id = a.link_type_id
         WHERE a.project_id = %(project_id)s
           AND a.link_type_id = %(link_type_id)s""")


class CollectionRequestHandler(projects.ProjectAttributeCollectionMixin,
                               _LinkRequestMixin,
                               base.CollectionRequestHandler):

    NAME = 'project-links'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT a.project_id,
               a.link_type_id,
               a.created_at,
               a.created_by,
               a.last_modified_at,
               a.last_modified_by,
               b.link_type,
               b.icon_class,
               a.url
          FROM v1.project_links AS a
          JOIN v1.project_link_types AS b
            ON b.id = a.link_type_id
         WHERE a.project_id = %(project_id)s
         ORDER BY b.link_type""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.project_links
                    (project_id, link_type_id, created_by, url)
             VALUES (%(project_id)s, %(link_type_id)s, %(username)s, %(url)s)
          RETURNING project_id, link_type_id""")


class RecordRequestHandler(projects.ProjectAttributeCRUDMixin,
                           _LinkRequestMixin, base.CRUDRequestHandler):

    NAME = 'project-link'

    DELETE_SQL = re.sub(r'\s+', ' ', """\
        DELETE FROM v1.project_links
              WHERE project_id = %(project_id)s
                AND link_type_id = %(link_type_id)s""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.project_links
           SET url=%(url)s,
               last_modified_at=CURRENT_TIMESTAMP,
               last_modified_by=%(username)s
         WHERE project_id = %(project_id)s
           AND link_type_id = %(current_link_type_id)s""")
