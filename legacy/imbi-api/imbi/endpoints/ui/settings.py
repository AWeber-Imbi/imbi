from imbi.endpoints import base


class SettingsRequestHandler(base.RequestHandler):

    ENDPOINT = 'ui-settings'

    async def get(self, *args, **kwargs):
        settings = self.settings['automations']
        self.send_response({
            'integrations': {
                'grafana': {
                    'enabled': settings['grafana']['enabled'],
                    'project_link_type_id':
                        settings['grafana']['project_link_type_id']
                },
                'gitlab': {
                    'project_link_type_id':
                        settings['gitlab']['project_link_type_id']
                },
                'sentry': {
                    'enabled': settings['sentry']['enabled'],
                    'project_link_type_id':
                        settings['sentry']['project_link_type_id']
                },
                'sonarqube': {
                    'enabled': settings['sonarqube']['enabled'],
                    'project_link_type_id':
                        settings['sonarqube']['project_link_type_id']
                }
            },
            'project_url_template': self.settings['project_url_template']
        })
