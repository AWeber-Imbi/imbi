"""
Request Handlers for the Configuration System Endpoints

"""
from tornado import web

from . import base


class SettingsRequestHandler(base.ItemsRequestHandler):

    async def get(self, *args, **kwargs):
        await super().get(*args, **kwargs)


class ConfigurationSystems(SettingsRequestHandler):

    ENDPOINT = 'settings-configuration-systems'
    GET_SQL = """\
    SELECT "name", created_at, modified_at, description, icon_class
      FROM v1.configuration_systems
     ORDER BY "name" ASC;"""


class CookieCutters(SettingsRequestHandler):

    ENDPOINT = 'settings-cookie-cutters'
    GET_SQL = """\
    SELECT "name", created_at, modified_at, "type", project_type,
           description, url
      FROM v1.cookie_cutters
     ORDER BY "name" ASC;"""


class DataCenters(SettingsRequestHandler):

    ENDPOINT = 'settings-data-centers'
    GET_SQL = """\
    SELECT "name", created_at, modified_at, description, icon_class
      FROM v1.data_centers
     ORDER BY "name" ASC;"""


class DeploymentTypes(SettingsRequestHandler):

    ENDPOINT = 'settings-deployment-types'
    GET_SQL = """\
    SELECT "name", created_at, modified_at, description, icon_class
      FROM v1.deployment_types
     ORDER BY "name" ASC;"""


class Environments(SettingsRequestHandler):

    ENDPOINT = 'settings-environments'
    GET_SQL = """\
    SELECT "name", created_at, modified_at, description, icon_class
      FROM v1.environments
     ORDER BY "name" ASC;"""


class Groups(SettingsRequestHandler):

    ENDPOINT = 'settings-groups'
    GET_SQL = """\
    SELECT "name", created_at, modified_at, group_type,
           external_id, permissions
      FROM v1.groups
     ORDER BY "name" ASC;"""


class OrchestrationSystems(SettingsRequestHandler):

    ENDPOINT = 'settings-orchestration-systems'
    GET_SQL = """\
    SELECT "name", created_at, modified_at, description, icon_class
      FROM v1.orchestration_systems
     ORDER BY "name" ASC;"""


class Permissions(base.AuthenticatedRequestHandler):

    ENDPOINT = 'settings-permissions'

    @base.require_permission('admin')
    async def get(self):
        self.send_response(list(self.settings['permissions']))


class ProjectLinkTypes(SettingsRequestHandler):

    ENDPOINT = 'settings-project-link-types'
    GET_SQL = """\
    SELECT link_type, created_at, modified_at, icon_class
      FROM v1.project_link_types
     ORDER BY link_type ASC;"""


class ProjectFactTypes(SettingsRequestHandler):

    ENDPOINT = 'settings-project-fact-types'
    GET_SQL = """\
    SELECT id, "name", created_at, modified_at, project_type, weight
      FROM v1.project_fact_types
     ORDER BY "name" ASC;"""


class ProjectTypes(SettingsRequestHandler):

    ENDPOINT = 'settings-project-types'
    GET_SQL = """\
    SELECT "name", created_at, modified_at, description, slug, icon_class
      FROM v1.project_types
     ORDER BY "name" ASC;"""


class Teams(SettingsRequestHandler):

    ENDPOINT = 'settings-teams'
    GET_SQL = """\
    SELECT created_at, modified_at, "name", slug, icon_class, "group"
      FROM v1.teams ORDER BY "name" ASC;"""


URLS = [
    web.url('/settings/configuration_systems', ConfigurationSystems),
    web.url('/settings/cookie_cutters', CookieCutters),
    web.url('/settings/data_centers', DataCenters),
    web.url('/settings/deployment_types', DeploymentTypes),
    web.url('/settings/environments', Environments),
    web.url('/settings/groups', Groups),
    web.url('/settings/orchestration_systems', OrchestrationSystems),
    web.url('/settings/permissions', Permissions),
    web.url('/settings/project_fact_types', ProjectFactTypes),
    web.url('/settings/project_link_types', ProjectLinkTypes),
    web.url('/settings/project_types', ProjectTypes),
    web.url('/settings/teams', Teams),
]
