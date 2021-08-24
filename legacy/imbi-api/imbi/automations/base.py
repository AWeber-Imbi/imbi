import logging
import re
import typing

import sprockets_postgres

from imbi import oauth2
from imbi.automations import models
if typing.TYPE_CHECKING:
    from imbi import app, user


class Automation:

    GET_PROJECT_SQL = re.sub(r'\s+', ' ', """\
        SELECT p.name AS project_name,
               p.description AS project_description,
               p.gitlab_project_id,
               p.slug AS project_slug,
               t.environment_urls,
               t.id AS project_type_id,
               t.gitlab_project_prefix,
               t.name AS project_type_name,
               t.slug AS project_type_slug,
               n.gitlab_group_name,
               n.name AS namespace_name,
               n.slug AS namespace_slug
          FROM v1.projects AS p
          JOIN v1.project_types AS t ON t.id = p.project_type_id
          JOIN v1.namespaces AS n ON n.id = p.namespace_id
         WHERE p.id = %(project_id)s""")

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
        result = await self.db.execute(
            self.GET_PROJECT_SQL, {'project_id': project_id})
        if result.row_count == 0:
            self._add_error('project not found for {}', project_id)
        else:
            if result.row['gitlab_group_name'] is None:
                self._add_error('missing GitLab group for namespace {}',
                                result.row['namespace_slug'])
            if result.row['gitlab_project_prefix'] is None:
                self._add_error('missing no GitLab prefix for project type {}',
                                result.row['project_type_slug'])

        if not self._has_error():
            return models.Project(
                description=result.row['project_description'],
                gitlab_project_id=result.row['gitlab_project_id'],
                id=project_id,
                name=result.row['project_name'],
                namespace=models.Namespace(
                    gitlab_group_name=result.row['gitlab_group_name'],
                    name=result.row['namespace_name'],
                    slug=result.row['namespace_slug']),
                project_type=models.ProjectType(
                    environment_urls=result.row['environment_urls'],
                    gitlab_project_prefix=result.row['gitlab_project_prefix'],
                    id=result.row['project_type_id'],
                    name=result.row['project_type_name'],
                    slug=result.row['project_type_slug']),
                slug=result.row['project_slug'])

    async def _get_gitlab_token(self) \
            -> typing.Optional[oauth2.IntegrationToken]:
        tokens = await self.user.fetch_integration_tokens('gitlab')
        if not tokens:
            self._add_error('GitLab token not found for current user')
            return None
        return tokens[0]
