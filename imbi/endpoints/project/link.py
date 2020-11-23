"""
Request Handler for an individual project

"""
from imbi.endpoints import base


class RequestHandler(base.CRUDRequestHandler):

    NAME = 'project-link'
    ITEM_SCHEMA = 'project/link.yaml'
    ID_KEY = ['project_id', 'link_type']
    FIELDS = ['project_id', 'link_type', 'url']
    TTL = 300

    DELETE_SQL = """\
    DELETE FROM v1.project_links
          WHERE project_id=%(project_id)s
            AND link_type=%(link_type)s"""

    GET_SQL = """\
    SELECT project_id, created_at, modified_at, link_type, url
      FROM v1.project_links
     WHERE project_id=%(project_id)s
       AND link_type=%(link_type)s"""

    PATCH_SQL = """\
    UPDATE v1.project_links
       SET link_type=%(link_type)s,
           url=%(url)s,
           modified_at=CURRENT_TIMESTAMP
     WHERE project_id=%(project_id)s;"""

    POST_SQL = """\
    INSERT INTO v1.project_links (project_id, link_type, url)
         VALUES (%(project_id)s, %(link_type)s, %(url)s)
      RETURNING project_id, link_type;"""
