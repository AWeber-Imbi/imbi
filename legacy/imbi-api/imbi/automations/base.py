import logging
import typing

import sprockets_postgres

from imbi import models, oauth2
if typing.TYPE_CHECKING:
    from imbi import app, user


class Automation:

    def __init__(self,
                 application: 'app.Application',
                 current_user: 'user.User',
                 db: sprockets_postgres.PostgresConnector):
        self.application = application
        self.automation_settings = self.application.settings['automations']
        self.db = db
        self.errors: typing.List[str] = []
        self.logger = logging.getLogger(__package__).getChild(
            self.__class__.__name__)
        self.user = current_user

    def _add_error(self, msg_format, *args):
        message = msg_format.format(*args)
        self.logger.warning('%s', message)
        self.errors.append(message)

    def _has_error(self) -> bool:
        return len(self.errors) > 0

    async def _get_project(self, project_id: int) \
            -> typing.Optional[models.Project]:
        project = await models.project(project_id, self.application)
        if not project:
            self._add_error('project not found for {}', project_id)
        return None if self._has_error() else project

    async def _get_gitlab_token(self) \
            -> typing.Optional[oauth2.IntegrationToken]:
        tokens = await self.user.fetch_integration_tokens('gitlab')
        if not tokens:
            self._add_error('GitLab token not found for current user')
            return None
        return tokens[0]
