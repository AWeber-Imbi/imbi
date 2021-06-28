import asyncio
import dataclasses
import logging
import typing

import sprockets_postgres

import imbi.integrations
import imbi.user
from imbi.endpoints import gitlab


@dataclasses.dataclass
class Project:
    description: typing.Union[str, None]
    gitlab_project_id: typing.Union[int, None]
    name: str
    namespace_id: int
    project_id: int
    project_type_id: int
    slug: str

    @classmethod
    def from_database(cls, row: dict) -> 'Project':
        field_names = {f.name for f in dataclasses.fields(cls)}
        filtered = {n: v for n, v in row.items() if n in field_names}
        filtered['project_id'] = row['id']
        return cls(**filtered)


class GitLabCreateProjectAutomation:
    def __init__(self,
                 project: Project,
                 user: imbi.user.User,
                 db: sprockets_postgres.PostgresConnector):
        self.db = db
        self.imbi_project = project
        self.logger = logging.getLogger(__package__).getChild(
            self.__class__.__name__)
        self.user = user

        self._errors: typing.List[str] = []
        self._gitlab: typing.Optional[gitlab.GitLabClient] = None
        self._gitlab_parent: typing.Optional[dict] = None

    async def prepare(self) -> typing.List[str]:
        if self.imbi_project.gitlab_project_id is not None:
            self._add_error('GitLab project {} already exists for {}',
                            self.imbi_project.gitlab_project_id,
                            self.imbi_project.slug)
        else:
            project_path, token = await asyncio.gather(
                self._get_gitlab_project_path(), self._get_gitlab_token())
            if project_path and token:
                self._gitlab = gitlab.GitLabClient(token)
                self._gitlab_parent = await self._get_gitlab_parent(
                    project_path)

        return self._errors

    async def run(self):
        gitlab_info = await self._gitlab.create_project(
            self._gitlab_parent, self.imbi_project.name,
            description=self.imbi_project.description)
        await self.db.execute(
            """UPDATE v1.projects
                  SET gitlab_project_id = %(gitlab_project_id)s
                WHERE id = %(project_id)s""",
            {
                'project_id': self.imbi_project.project_id,
                'gitlab_project_id': gitlab_info['id'],
            })
        return gitlab_info

    def _add_error(self, msg_format, *args):
        message = msg_format.format(*args)
        self.logger.warning('%s', message)
        self._errors.append(message)

    async def _get_gitlab_project_path(self) -> typing.Union[
            typing.Tuple[str, str], None]:
        result = await self.db.execute(
            """SELECT p.gitlab_project_id,
                      n.slug AS namespace_slug,
                      n.gitlab_group_name,
                      t.slug AS type_slug,
                      t.gitlab_project_prefix
                 FROM v1.projects AS p
                 JOIN v1.namespaces AS n ON (n.id = p.namespace_id)
                 JOIN v1.project_types AS t ON (t.id = p.project_type_id)
                WHERE p.id = %(project_id)s
            """,
            {'project_id': self.imbi_project.project_id})
        if result.row_count == 0:
            self._add_error('project row not found for {}',
                            self.imbi_project.project_id)
        elif result.row['gitlab_group_name'] is None:
            self._add_error('GitLab group is not defined for namespace {}',
                            result.row['namespace_slug'])
        elif result.row['gitlab_project_prefix'] is None:
            self._add_error('GitLab prefix is not defined for project type {}',
                            result.row['type_slug'])
        else:
            return (result.row['gitlab_group_name'],
                    result.row['gitlab_project_prefix'])
        return None

    async def _get_gitlab_token(self) -> typing.Union[
            imbi.integrations.IntegrationToken, None]:
        tokens = await self.user.fetch_integration_tokens('gitlab')
        if not tokens:
            self._add_error('GitLab token not found for current user')
            return None
        return tokens[0]

    async def _get_gitlab_parent(self, path) -> dict:
        gitlab_parent = await self._gitlab.fetch_group(*path)
        if not gitlab_parent:
            self._add_error('GitLab path {} does not exist', '/'.join(path))
        return gitlab_parent
