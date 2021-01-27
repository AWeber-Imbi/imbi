import re

from imbi.endpoints import base


class _ProjectRequestMixin:

    ITEM_NAME = 'project'
    ID_KEY = ['namespace', 'name']
    FIELDS = ['namespace', 'name', 'slug', 'description', 'data_center',
              'environments', 'project_type', 'configuration_system',
              'deployment_type', 'orchestration_system']
    TTL = 300

    GET_SQL = re.sub(r'\s+', ' ', """\
    SELECT namespace, "name", created_at, created_by, last_modified_at,
           last_modified_by, slug, description, data_center, environments,
           project_type, configuration_system, deployment_type,
           orchestration_system
      FROM v1.projects
     WHERE namespace=%(namespace)s
       AND "name"=%(name)s;""")


class CollectionRequestHandler(_ProjectRequestMixin,
                               base.CollectionRequestHandler):
    NAME = 'projects'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
      SELECT namespace, "name", created_at, created_by, last_modified_at,
             last_modified_by, slug, description, data_center, environments,
             project_type, configuration_system, deployment_type,
             orchestration_system
        FROM v1.projects
    ORDER BY namespace, "name" ASC;""")

    POST_SQL = re.sub(r'\s+', ' ', """\
    INSERT INTO v1.projects (namespace, "name", created_by, slug, description,
                             data_center, environments, project_type,
                             configuration_system, deployment_type,
                             orchestration_system)
         VALUES (%(namespace)s, %(name)s, %(username)s, %(slug)s,
                 %(description)s, %(data_center)s, %(environments)s,
                 %(project_type)s, %(configuration_system)s,
                 %(deployment_type)s, %(orchestration_system)s)
      RETURNING namespace, "name"
      """)


class RecordRequestHandler(_ProjectRequestMixin, base.CRUDRequestHandler):

    NAME = 'project'

    DELETE_SQL = re.sub(r'\s+', ' ', """\
    DELETE FROM v1.projects
          WHERE namespace=%(namespace)s
            AND "name"=%(name)s;""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
    UPDATE v1.projects
       SET namespace=%(namespace)s,
           "name"=%(name)s,
           last_modified_at=CURRENT_TIMESTAMP,
           last_modified_by=%(username)s,
           slug=%(slug)s,
           description=%(description)s,
           data_center=%(data_center)s,
           project_type=%(project_type)s,
           configuration_system=%(configuration_system)s,
           deployment_type=%(deployment_type)s,
           orchestration_system=%(orchestration_system)s,
           environments=%(environments)s
     WHERE namespace=%(current_namespace)s
       AND "name"=%(current_name)s;""")
