import asyncio
import dataclasses
import logging
import pathlib
import tempfile
import typing

import cookiecutter.main
import isort.api
import sprockets_postgres
import yarl
from yapf.yapflib import yapf_api

import imbi.integrations
import imbi.user
from imbi.endpoints import gitlab


@dataclasses.dataclass
class CookieCutter:
    name: str
    project_type_id: int
    url: str


@dataclasses.dataclass
class Namespace:
    gitlab_group_name: typing.Union[str, None]
    name: str
    slug: str


@dataclasses.dataclass
class ProjectType:
    id: int
    environment_urls: bool
    gitlab_project_prefix: typing.Union[str, None]
    name: str
    slug: str


@dataclasses.dataclass
class Project:
    description: typing.Union[str, None]
    gitlab_project_id: typing.Union[int, None]
    id: int
    name: str
    namespace: Namespace
    project_type: ProjectType
    slug: str


class Automation:
    def __init__(self,
                 application: 'imbi.app.Application',
                 user: 'imbi.user.User',
                 db: sprockets_postgres.PostgresConnector):
        self.application = application
        self.automation_settings = self.application.settings['automations']
        self.db = db
        self.errors: typing.List[str] = []
        self.logger = logging.getLogger(__package__).getChild(
            self.__class__.__name__)
        self.user = user

    def _add_error(self, msg_format, *args):
        message = msg_format.format(*args)
        self.logger.warning('%s', message)
        self.errors.append(message)

    def _has_error(self) -> bool:
        return len(self.errors) > 0

    async def _get_project(self, project_id: int) -> typing.Union[
            Project, None]:
        result = await self.db.execute(
            """SELECT p.name AS project_name,
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
                WHERE p.id = %(project_id)s
            """,
            {'project_id': project_id})
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
            return Project(
                description=result.row['project_description'],
                gitlab_project_id=result.row['gitlab_project_id'],
                id=project_id,
                name=result.row['project_name'],
                namespace=Namespace(
                    gitlab_group_name=result.row['gitlab_group_name'],
                    name=result.row['namespace_name'],
                    slug=result.row['namespace_slug']),
                project_type=ProjectType(
                    environment_urls=result.row['environment_urls'],
                    gitlab_project_prefix=result.row['gitlab_project_prefix'],
                    id=result.row['project_type_id'],
                    name=result.row['project_type_name'],
                    slug=result.row['project_type_slug']),
                slug=result.row['project_slug'])

    async def _get_gitlab_token(self) -> typing.Union[
            'imbi.integrations.IntegrationToken', None]:
        tokens = await self.user.fetch_integration_tokens('gitlab')
        if not tokens:
            self._add_error('GitLab token not found for current user')
            return None
        return tokens[0]

    @staticmethod
    def _generate_sonar_key(project: Project) -> str:
        return ':'.join([project.namespace.slug.lower(), project.slug.lower()])

    def _generate_sonar_dashboard_link(self, root_url: str,
                                       project: Project) -> str:
        if self.automation_settings['sonar']['url']:
            root_url = yarl.URL(self.automation_settings['sonar']['url'])
            return str(root_url.with_path('/dashboard').with_query({
                'id': self._generate_sonar_key(project),
            }))


class GitLabCreateProjectAutomation(Automation):
    def __init__(self,
                 application: 'imbi.app.Application',
                 project_id: int,
                 user: 'imbi.user.User',
                 db: sprockets_postgres.PostgresConnector):
        super().__init__(application, user, db)
        self.imbi_project_id = project_id
        self._gitlab: typing.Optional[gitlab.GitLabClient] = None
        self._gitlab_parent: typing.Optional[dict] = None
        self._project: typing.Optional[Project] = None

    async def prepare(self) -> typing.List[str]:
        project: Project
        token: imbi.integrations.IntegrationToken
        project, token = await asyncio.gather(
            self._get_project(self.imbi_project_id), self._get_gitlab_token())
        if project is not None and project.gitlab_project_id is not None:
            self._add_error('GitLab project {} already exists for {}',
                            project.gitlab_project_id, project.slug)
        elif project is not None and token is not None:
            self._gitlab = gitlab.GitLabClient(token, self.application)
            self._gitlab_parent = await self._get_gitlab_parent(project)
            self._project = project
        return self.errors

    async def run(self):
        gitlab_info = await self._gitlab.create_project(
            self._gitlab_parent, self._project.name,
            description=self._project.description)
        await self.db.execute(
            """UPDATE v1.projects
                  SET gitlab_project_id = %(gitlab_project_id)s
                WHERE id = %(project_id)s""",
            {
                'project_id': self._project.id,
                'gitlab_project_id': gitlab_info['id'],
            })

        link_id = self.automation_settings['gitlab'].get('repository_link_id')
        if link_id:
            await self.db.execute(
                """INSERT INTO v1.project_links(project_id, link_type_id,
                                                created_by, url)
                        VALUES (%(project_id)s, %(link_type_id)s,
                                %(username)s, %(url)s)""",
                {
                    'link_type_id': link_id,
                    'project_id': self._project.id,
                    'url': gitlab_info['web_url'],
                    'username': self.user.username,
                })

        link_id = self.automation_settings['sonar'].get('dashboard_link_id')
        if link_id:
            await self.db.execute(
                """INSERT INTO v1.project_links(project_id, link_type_id,
                                                created_by, url)
                        VALUES (%(project_id)s, %(link_type_id)s,
                                %(username)s, %(url)s)""",
                {
                    'link_type_id': link_id,
                    'project_id': self._project.id,
                    'url': self._generate_sonar_dashboard_link(
                        None, self._project),
                    'username': self.user.username,
                })
            await self.db.execute(
                """UPDATE v1.projects
                      SET sonarqube_project_key = %(sonar_key)s
                    WHERE id = %(project_id)s""",
                {
                    'project_id': self._project.id,
                    'sonar_key': self._generate_sonar_key(self._project),
                }
            )

        return gitlab_info

    async def _get_gitlab_parent(self, project: Project) -> dict:
        gitlab_parent = await self._gitlab.fetch_group(
            project.namespace.gitlab_group_name,
            project.project_type.gitlab_project_prefix)
        if not gitlab_parent:
            self._add_error('GitLab path {}/{} does not exist',
                            project.namespace.gitlab_group_name,
                            project.project_type.gitlab_project_prefix)
        return gitlab_parent


class GitLabInitialCommitAutomation(Automation):
    def __init__(self,
                 application: 'imbi.app.Application',
                 project_id: int,
                 cookie_cutter: str,
                 user: 'imbi.user.User',
                 db: sprockets_postgres.PostgresConnector):
        super().__init__(application, user, db)
        self._cookie_cutter_name = cookie_cutter
        self._imbi_project_id = project_id

        self._cookie_cutter: typing.Union[CookieCutter, None] = None
        self._gitlab: typing.Optional[gitlab.GitLabClient] = None
        self._gitlab_project_info: typing.Union[dict, None] = None
        self._project: typing.Union[Project, None] = None
        self._token: typing.Union[imbi.integrations.IntegrationToken,
                                  None] = None

    async def prepare(self) -> typing.List[str]:
        self._project = await self._get_project(self._imbi_project_id)
        self._token = await self._get_gitlab_token()
        self._cookie_cutter = await self._get_cookie_cutter(
            self._cookie_cutter_name)

        if not self._has_error() and (self._project.project_type.id !=
                                      self._cookie_cutter.project_type_id):
            self._add_error(
                'Cookie Cutter {} is not available for Project Type {}',
                self._cookie_cutter.name, self._project.project_type.slug)
        elif self._project.gitlab_project_id is None:
            self._add_error('GitLab project does not exist for {}',
                            self._project.slug)
        else:
            self._gitlab = gitlab.GitLabClient(self._token, self.application)
            self._gitlab_project_info = await self._gitlab.fetch_project(
                self._project.gitlab_project_id)
            if not self._gitlab_project_info:
                self._add_error('GitLab project id {} does not exist',
                                self._project.gitlab_project_id)
        return self.errors

    async def run(self):
        self.logger.info('generating initial commit for %s (%s) from %s',
                         self._project.slug, self._project.id,
                         self._cookie_cutter.url)
        package_name = self._project.slug.lower().replace('-', '_')
        with tempfile.TemporaryDirectory() as tmp_dir:
            # TODO: create a "nicer" context to work with ... this one
            # TODO: is from project-creator
            context = {
                'consul_prefix': '/'.join([
                    'services',
                    self._project.namespace.gitlab_group_name.lower(),
                    self._project.project_type.gitlab_project_prefix,
                ]),
                'gitlab_namespace_id':
                    self._gitlab_project_info['namespace']['id'],
                'gitlab_project_id': self._gitlab_project_info['id'],
                'gitlab_url': self._gitlab_project_info['web_url'],
                'package_name': package_name,
                'project_name': self._project.name,
                'project_team':
                    self._project.namespace.gitlab_group_name.lower(),
                'short_description': self._project.description,
                # These are also available for future use
                # 'sentry_team': None,
                # 'legacy_sentry_dsn': None,
                # 'sentry_dsn': None,
                # 'sentry_slug': None,
                # 'sentry_dashboard': None,
                # 'sentry_organization': None,
            }
            if self.automation_settings['sonar'].get('url'):
                context.update({
                    'sonar_project_key': self._generate_sonar_key(
                        self._project),
                    'sonar_project_url': self._generate_sonar_dashboard_link(
                        '', self._project)
                })

            self.logger.debug('expanding %s for project %s in %s',
                              self._cookie_cutter.url, self._project.id,
                              tmp_dir)
            project_dir = cookiecutter.main.cookiecutter(
                self._cookie_cutter.url, extra_context=context, no_input=True,
                output_dir=tmp_dir)
            project_dir = pathlib.Path(project_dir)

            self.logger.debug('reformatting project files')
            isort_cfg = self.automation_settings['isort']
            isort_cfg.setdefault('known_first_party', [])
            isort_cfg['known_first_party'].append(context['package_name'])
            yapf_style = self.automation_settings['yapf']

            for py_file in project_dir.rglob('*.py'):
                isort.api.sort_file(py_file, **isort_cfg)
                yapf_api.FormatFile(str(py_file), style_config=yapf_style,
                                    in_place=True)

            self.logger.debug('committing to GitLab')
            commit_info = await self._gitlab.commit_tree(
                self._gitlab_project_info, project_dir,
                'Initial commit (automated)')

            return commit_info

    async def _get_cookie_cutter(self, url: str) -> typing.Union[
            CookieCutter, None]:
        result = await self.db.execute(
            """SELECT name, project_type_id, url
                 FROM v1.cookie_cutters
                WHERE url = %(url)s""",
            {'url': url})
        if result.row_count != 0:
            return CookieCutter(**result.row)
        else:
            self._add_error('Cookie cutter {} does not exist', url)
