import re

from imbi.endpoints import base


class _RequestHandlerMixin:

    ITEM_NAME = 'project'
    ID_KEY = ['id']
    FIELDS = ['id', 'namespace_id', 'project_type_id', 'name', 'slug',
              'description', 'data_center', 'environments', 'deployment_type',
              'configuration_system', 'orchestration_system']
    TTL = 300

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT a.id,
               a.created_at,
               a.created_by,
               a.last_modified_at,
               a.last_modified_by,
               a.namespace_id,
               b.name AS namespace,
               a.project_type_id,
               c.name AS project_type,
               a.name,
               a.slug,
               a.description,
               a.data_center,
               a.environments,
               a.configuration_system,
               a.deployment_type,
               a.orchestration_system
          FROM v1.projects AS a
          JOIN v1.namespaces AS b ON b.id = a.namespace_id
          JOIN v1.project_types AS c ON c.id = a.project_type_id
         WHERE a.id=%(id)s""")


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):
    NAME = 'projects'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT a.id,
               a.created_at,
               a.created_by,
               a.last_modified_at,
               a.last_modified_by,
               a.namespace_id,
               b.name AS namespace,
               a.project_type_id,
               c.name AS project_type,
               a.name,
               a.slug,
               a.description,
               a.data_center,
               a.environments,
               a.configuration_system,
               a.deployment_type,
               a.orchestration_system
          FROM v1.projects AS a
          JOIN v1.namespaces AS b ON b.id = a.namespace_id
          JOIN v1.project_types AS c ON c.id = a.project_type_id
         ORDER BY b.name, c.name, a.name""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.projects
                    (namespace_id, project_type_id, created_by,  "name", slug,
                     description, data_center, environments, deployment_type,
                     configuration_system, orchestration_system)
             VALUES (%(namespace_id)s, %(project_type_id)s, %(username)s,
                     %(name)s, %(slug)s, %(description)s, %(data_center)s,
                     %(environments)s, %(deployment_type)s,
                     %(configuration_system)s, %(orchestration_system)s)
          RETURNING id""")


class RecordRequestHandler(_RequestHandlerMixin, base.CRUDRequestHandler):

    NAME = 'project'

    DELETE_SQL = 'DELETE FROM v1.projects WHERE id=%(id)s'

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.projects
           SET namespace_id=%(namespace_id)s,
               project_type_id=%(project_type_id)s,
               last_modified_at=CURRENT_TIMESTAMP,
               last_modified_by=%(username)s,
               "name"=%(name)s,
               slug=%(slug)s,
               description=%(description)s,
               data_center=%(data_center)s,
               configuration_system=%(configuration_system)s,
               deployment_type=%(deployment_type)s,
               orchestration_system=%(orchestration_system)s,
               environments=%(environments)s
         WHERE id=%(id)s""")
