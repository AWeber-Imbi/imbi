"""
Request Handlers for the Configuration System Endpoints

"""
import re

from tornado import web

from . import base


class ConfigurationSystems(base.CollectionRequestHandler):

    NAME = 'settings-configuration-systems'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
    SELECT "name", description, icon_class
      FROM v1.configuration_systems
     ORDER BY "name" ASC;""")


class CookieCutters(base.CollectionRequestHandler):

    NAME = 'settings-cookie-cutters'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
    SELECT "name", "type", project_type, description, url
      FROM v1.cookie_cutters
     ORDER BY "name" ASC;""")


class DataCenters(base.CollectionRequestHandler):

    NAME = 'settings-data-centers'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
    SELECT "name", description, icon_class
      FROM v1.data_centers
     ORDER BY "name" ASC;""")


class DeploymentTypes(base.CollectionRequestHandler):

    NAME = 'settings-deployment-types'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
    SELECT "name", description, icon_class
      FROM v1.deployment_types
     ORDER BY "name" ASC;""")


class Environments(base.CollectionRequestHandler):

    NAME = 'settings-environments'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
    SELECT "name", description, icon_class
      FROM v1.environments
     ORDER BY "name" ASC;""")


class Groups(base.CollectionRequestHandler):

    NAME = 'settings-groups'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
    SELECT "name", group_type, external_id, permissions
      FROM v1.groups
     ORDER BY "name" ASC;""")


class OrchestrationSystems(base.CollectionRequestHandler):

    NAME = 'settings-orchestration-systems'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
    SELECT "name", description, icon_class
      FROM v1.orchestration_systems
     ORDER BY "name" ASC;""")


class Permissions(base.AuthenticatedRequestHandler):

    NAME = 'settings-permissions'

    @base.require_permission('admin')
    async def get(self):
        self.send_response(list(self.settings['permissions']))


class ProjectLinkTypes(base.CollectionRequestHandler):

    NAME = 'settings-project-link-types'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
    SELECT link_type icon_class
      FROM v1.project_link_types
     ORDER BY link_type ASC;""")


class ProjectFactTypes(base.CollectionRequestHandler):

    NAME = 'settings-project-fact-types'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
    SELECT id, "name" project_type, weight
      FROM v1.project_fact_types
     ORDER BY "name" ASC;""")


class ProjectTypes(base.CollectionRequestHandler):

    NAME = 'settings-project-types'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
    SELECT "name", description, slug, icon_class
      FROM v1.project_types
     ORDER BY "name" ASC;""")


class Namespaces(base.CollectionRequestHandler):

    NAME = 'settings-namespaces'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
    SELECT "name", slug, icon_class, maintained_by
      FROM v1.namespaces ORDER BY "name" ASC;""")


URLS = [
    web.url('/settings/configuration_systems', ConfigurationSystems),
    web.url('/settings/cookie_cutters', CookieCutters),
    web.url('/settings/data_centers', DataCenters),
    web.url('/settings/deployment_types', DeploymentTypes),
    web.url('/settings/environments', Environments),
    web.url('/settings/groups', Groups),
    web.url('/settings/namespaces', Namespaces),
    web.url('/settings/orchestration_systems', OrchestrationSystems),
    web.url('/settings/permissions', Permissions),
    web.url('/settings/project_fact_types', ProjectFactTypes),
    web.url('/settings/project_link_types', ProjectLinkTypes),
    web.url('/settings/project_types', ProjectTypes)
]
