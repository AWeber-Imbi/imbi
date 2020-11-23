"""
Request Handler for the options available when creating a project record

"""
from imbi.endpoints import base, settings


class RequestHandler(base.AuthenticatedRequestHandler):

    TTL = 3000

    SETTINGS = {
        'configuration_systems': settings.ConfigurationSystems.GET_SQL,
        'cookie_cutters': settings.CookieCutters.GET_SQL,
        'data_centers': settings.DataCenters.GET_SQL,
        'deployment_types': settings.DeploymentTypes.GET_SQL,
        'environments': settings.Environments.GET_SQL,
        'orchestration_systems': settings.OrchestrationSystems.GET_SQL,
        'project_link_types': settings.ProjectLinkTypes.GET_SQL,
        'project_types': settings.ProjectTypes.GET_SQL,
        'teams': settings.Teams.GET_SQL
    }

    async def get(self, *args, **kwargs):
        opts = {}
        for key, sql in self.SETTINGS.items():
            result = await self.postgres_execute(
                sql, metric_name='settings-get-{}'.format(key))
            opts[key] = result.rows
        self.send_response(opts)
