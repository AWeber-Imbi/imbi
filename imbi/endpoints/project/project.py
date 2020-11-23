"""
Request Handler for an individual project

"""
from imbi.endpoints import base


class RequestHandler(base.CRUDRequestHandler):

    NAME = 'project'
    ITEM_SCHEMA = 'project/project.yaml'
    FIELDS = ['id', 'name', 'slug', 'description', 'owned_by', 'data_center',
              'project_type', 'configuration_system', 'deployment_type',
              'orchestration_system']
    TTL = 300

    DELETE_SQL = 'DELETE FROM v1.projects WHERE id=%(id)s'

    GET_SQL = """\
    SELECT id, created_at, modified_at, "name", slug, description, owned_by,
           data_center, project_type, configuration_system, deployment_type,
           orchestration_system
      FROM v1.projects
     WHERE id = %(id)s"""

    PATCH_SQL = """\
    UPDATE v1.projects
       SET "name"=%(name)s,
           modified_at=CURRENT_TIMESTAMP,
           slug=%(slug)s,
           description=%(description)s,
           owned_by=%(owned_by)s,
           data_center=%(data_center)s,
           project_type=%(project_type)s,
           configuration_system=%(configuration_system)s,
           deployment_type=%(deployment_type)s,
           orchestration_system=%(orchestration_system)s
     WHERE id=%(id)s;"""

    POST_SQL = """\
    INSERT INTO v1.projects (id, "name", slug, description, owned_by,
                             data_center, project_type, configuration_system,
                             deployment_type, orchestration_system)
         VALUES (%(id)s, %(name)s, %(slug)s, %(description)s, %(owned_by)s,
                 %(data_center)s, %(project_type)s, %(configuration_system)s,
                 %(deployment_type)s, %(orchestration_system)s)
      RETURNING id;"""
