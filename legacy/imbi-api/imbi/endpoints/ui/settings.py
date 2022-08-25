import asyncio

from imbi.endpoints import base, cookie_cutters, environments, groups, \
    namespaces, fact_types, project_link_types, project_types
from imbi.endpoints.integrations import oauth2


class RequestHandler(base.RequestHandler):

    NAME = 'metadata'

    async def get(self) -> None:
        """Return all metadata in a single request"""
        results = await asyncio.gather(
            self.postgres_execute(
                cookie_cutters.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='cookie-cutters'),
            self.postgres_execute(
                environments.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='environments'),
            self.postgres_execute(
                groups.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='groups'),
            self.postgres_execute(
                namespaces.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='namespaces'),
            self.postgres_execute(
                fact_types.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='project-fact-types'),
            self.postgres_execute(
                project_link_types.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='project-link-types'),
            self.postgres_execute(
                project_types.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='project-types'),
            self.application.opensearch.search_fields(),
            self.postgres_execute(
                oauth2.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='integrations'),
        )

        automations = self.settings['automations']

        oauth_details = results[8].rows
        gitlab = {'enabled': False}
        cfg = automations.get('gitlab')
        if cfg:
            gitlab['project_link_type_id'] = cfg.get('project_link_type_id')
            gitlab_auth = [r for r in oauth_details if r['name'] == 'gitlab']
            if gitlab_auth:
                gitlab_auth = gitlab_auth[0]
                gitlab.update({
                    'authorizationEndpoint':
                        gitlab_auth['authorization_endpoint'],
                    'clientId': gitlab_auth['client_id'],
                    'redirectURI': gitlab_auth['callback_url'],
                })
            gitlab['enabled'] = (
                gitlab['project_link_type_id'] is not None and
                gitlab['clientId'] is not None
            )

        self.send_response({
            'integrations': {
                'grafana': {
                    'enabled': automations['grafana']['enabled'],
                    'project_link_type_id':
                        automations['grafana']['project_link_type_id']
                },
                'gitlab': gitlab,
                'sentry': {
                    'enabled': automations['sentry']['enabled'],
                    'project_link_type_id':
                        automations['sentry']['project_link_type_id']
                },
                'sonarqube': {
                    'enabled': automations['sonarqube']['enabled'],
                    'project_link_type_id':
                        automations['sonarqube']['project_link_type_id']
                }
            },
            'metadata': {
                'cookie_cutters': results[0].rows,
                'environments': results[1].rows,
                'groups': results[2].rows,
                'namespaces': results[3].rows,
                'project_fact_types': results[4].rows,
                'project_link_types': results[5].rows,
                'project_types': results[6].rows
            },
            'opensearch': {
                'fields': results[7]
            },
            'project_url_template': self.settings['project_url_template']
        })
