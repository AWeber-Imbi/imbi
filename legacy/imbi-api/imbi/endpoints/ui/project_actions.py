import logging

from imbi import errors, models
from imbi.endpoints import base

LOGGER = logging.getLogger(__name__)


class AvailableActionsHandler(base.AuthenticatedRequestHandler):
    """Handler for fetching available actions for a project"""

    NAME = 'ui-project-actions'

    async def get(self, project_id: str) -> None:
        """Return list of available actions for the project

        Actions are filtered based on:
        - Configuration toggles
        - User has required integration tokens
        - Project has required identifiers
        """
        try:
            project_id_int = int(project_id)
        except ValueError:
            raise errors.BadRequest('Invalid project ID')

        # Load project to verify it exists
        project = await models.project(project_id_int, self.application)
        if project is None:
            raise errors.ItemNotFound(instance=self.request.uri)

        actions = []

        # Check GitHub deployment action
        github_action_config = self.application.settings.get(
            'actions', {}).get('github_deployment', {})
        github_action_enabled = github_action_config.get('enabled', False)

        if github_action_enabled:
            user_has_github = await self._user_has_integration_token('github')
            project_has_github = 'github' in project.identifiers
            integration_enabled = self.application.settings.get(
                'automations', {}).get('github', {}).get('enabled', False)

            LOGGER.debug(
                'GitHub action checks: enabled=%s, user_has_github=%s, '
                'project_has_github=%s, integration_enabled=%s, '
                'project.identifiers=%s', github_action_enabled,
                user_has_github, project_has_github, integration_enabled,
                project.identifiers)

            if user_has_github and project_has_github and integration_enabled:
                actions.append({
                    'id': 'github_deployment',
                    'name': 'Create GitHub Deployment',
                    'integration': 'github'
                })

        self.send_response(actions)

    async def _user_has_integration_token(self, integration_name: str) -> bool:
        """Check if the current user has an OAuth token for the integration"""
        result = await self.postgres_execute(
            'SELECT 1 FROM v1.user_oauth2_tokens '
            'WHERE username = %(username)s AND integration = %(integration)s',
            {
                'username': self._current_user.username,
                'integration': integration_name
            },
            metric_name='check-user-oauth-token')
        return result.row_count > 0
