import re

from imbi.endpoints import base


class _LinkRequestMixin:

    ID_KEY = ['namespace', 'name', 'link_type']
    ITEM_NAME = 'project-link'
    FIELDS = ['namespace', 'name', 'link_type', 'url']
    TTL = 300

    GET_SQL = re.sub(r'\s+', ' ', """\
    SELECT namespace, name, link_type, created_at, created_by,
           last_modified_at, last_modified_by, url
      FROM v1.project_links
     WHERE namespace=%(namespace)s
       AND name=%(name)s
       AND link_type=%(link_type)s""")


class CollectionRequestHandler(_LinkRequestMixin,
                               base.CollectionRequestHandler):

    NAME = 'project-links'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
      SELECT namespace, name, created_at, created_by,
             last_modified_at, last_modified_by, link_type, url
        FROM v1.project_links
       WHERE namespace=%(namespace)s
         AND name=%(name)s
    ORDER BY link_type;""")

    POST_SQL = re.sub(r'\s+', ' ', """\
    INSERT INTO v1.project_links (namespace, name, link_type, created_by, url)
         VALUES (%(namespace)s, %(name)s, %(link_type)s, %(username)s, %(url)s)
      RETURNING namespace, name, link_type""")


class RecordRequestHandler(_LinkRequestMixin, base.CRUDRequestHandler):

    NAME = 'project-link'

    DELETE_SQL = re.sub(r'\s+', ' ', """\
    DELETE FROM v1.project_links
          WHERE namespace=%(namespace)s
            AND name=%(name)s
            AND link_type=%(link_type)s""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
    UPDATE v1.project_links
       SET url=%(url)s,
           last_modified_at=CURRENT_TIMESTAMP,
           last_modified_by=%(username)s
     WHERE namespace=%(current_namespace)s
       AND name=%(current_name)s
       AND link_type=%(current_link_type)s""")
