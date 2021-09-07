import re
import typing

import sprockets_postgres
import yarl

from imbi import models
from imbi.automations import base
from imbi.clients import gitlab, sonarqube
if typing.TYPE_CHECKING:
    from imbi import app, user


class SonarCreateProject(base.Automation):

    INSERT_SQL = re.sub(
        r'\s+', ' ', """\
        INSERT INTO v1.project_links
                    (project_id, link_type_id, created_by, url)
             VALUES (%(project_id)s, %(link_type_id)s,
                     %(username)s, %(url)s)""")
    UPDATE_SQL = re.sub(
        r'\s+', ' ', """
        UPDATE v1.projects
           SET sonarqube_project_key = %(sonar_key)s
         WHERE id = %(project_id)s""")

    def __init__(self,
                 application: 'app.Application',
                 project_id: int,
                 public_url: yarl.URL,
                 current_user: 'user.User',
                 db: sprockets_postgres.PostgresConnector):
        super().__init__(application, current_user, db)
        self._public_url = public_url
        self._imbi_project_id = project_id
        self._gitlab_project: typing.Optional[gitlab.ProjectInfo] = None
        self._project: typing.Optional[models.Project] = None
        self._sonar_client: typing.Optional[sonarqube.SonarQubeClient] = None

    async def prepare(self) -> typing.List[str]:
        self._project = await self._get_project(self._imbi_project_id)
        token = await self._get_gitlab_token()
        if self._project and self._project.gitlab_project_id is None:
            self._add_error('GitLab project does not exist for {}',
                            self._project.slug)
        if not self._has_error():
            client = gitlab.GitLabClient(token, self.application)
            self._gitlab_project = await client.fetch_project(
                self._project.gitlab_project_id)
            if self._gitlab_project is None:
                self._add_error('GitLab project id {} does not exist',
                                self._project.gitlab_project_id)

        if not self._has_error():
            self._sonar_client = sonarqube.SonarQubeClient(self.application)
            if not self._sonar_client.enabled:
                self._add_error('SonarQube integration is not configured')

        return self.errors

    async def run(self) -> dict:
        project_key, dashboard = await self._sonar_client.create_project(
            self._project,
            public_url=self._public_url,
            main_branch_name=self._gitlab_project.default_branch)

        link_id = self.automation_settings['sonarqube'].get(
            'project_link_type_id')
        if link_id:
            await self.db.execute(
                self.INSERT_SQL, {
                    'link_type_id': link_id,
                    'project_id': self._project.id,
                    'url': dashboard,
                    'username': self.user.username
                })
            await self.db.execute(self.UPDATE_SQL, {
                'project_id': self._project.id,
                'sonar_key': project_key
            })
        return {
            'sonarqube_dashboard': dashboard,
            'sonarqube_project_key': project_key
        }
