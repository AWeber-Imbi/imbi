import typing
import re

from imbi import automations, models, errors
from imbi.endpoints import base, projects


class _DependencyRequestMixin:

    ID_KEY = ['project_id', 'dependency_id']
    ITEM_NAME = 'project-dependency'
    FIELDS = ['project_id', 'dependency_id']
    TTL = 300

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT project_id, created_at, created_by, dependency_id
          FROM v1.project_dependencies
         WHERE project_id=%(project_id)s
           AND dependency_id=%(dependency_id)s""")

    POST_SQL = re.sub(
        r'\s+', ' ', """\
        INSERT INTO v1.project_dependencies
                    (project_id, dependency_id, created_by)
             VALUES (%(project_id)s, %(dependency_id)s, %(username)s)
          RETURNING project_id, dependency_id, created_at, created_by""")

    async def _run_automations(
            self, dependency: models.ProjectDependency,
            selected_automations: typing.Sequence[models.Automation]) -> None:
        """Run a list of automations for the dependency

        If an automation fails, then an InternalServerError is raised.
        """
        if not selected_automations:
            return

        ordered_automations = automations.sort_automations(
            selected_automations)

        self.logger.info(
            'running automations for dependency '
            '(project: %s, dependency: %s): %r', dependency.project_id,
            dependency.dependency_id, [a.slug for a in ordered_automations])
        try:
            await automations.run_automations(ordered_automations,
                                              dependency,
                                              application=self.application,
                                              user=self._current_user,
                                              query_executor=self)
        except errors.ApplicationError:  # this is meant for the end user
            raise
        except automations.AutomationFailedError as error:
            raise errors.InternalServerError(str(error)) from None


class CollectionRequestHandler(projects.ProjectAttributeCollectionMixin,
                               _DependencyRequestMixin,
                               base.CollectionRequestHandler):

    NAME = 'project-dependencies'

    COLLECTION_SQL = re.sub(
        r'\s+', ' ', """\
          SELECT project_id, created_by, dependency_id
            FROM v1.project_dependencies
           WHERE project_id=%(project_id)s
        ORDER BY dependency_id""")

    COLLECTION_WITH_DEPENDENCY_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT d.project_id, d.created_at, d.created_by, d.dependency_id,
               p.name AS dependency_name,
               p.namespace_id AS dependency_namespace_id,
               p.project_type_id AS dependency_project_type_id
          FROM v1.project_dependencies AS d
          JOIN v1.projects AS p
            ON d.dependency_id=p.id
         WHERE project_id=%(project_id)s""")

    async def get(self, *args, **kwargs):
        if 'dependency' in self.get_query_arguments('include'):
            result = await self.postgres_execute(
                self.COLLECTION_WITH_DEPENDENCY_SQL,
                kwargs,
                metric_name='get-{}'.format(self.NAME))
            response = [{
                'project_id': row['project_id'],
                'dependency_id': row['dependency_id'],
                'created_at': row['created_at'],
                'created_by': row['created_by'],
                'dependency': {
                    'id': row['dependency_id'],
                    'name': row['dependency_name'],
                    'namespace_id': row['dependency_namespace_id'],
                    'project_type_id': row['dependency_project_type_id'],
                }
            } for row in result.rows]
            self.send_response(response)
        else:
            await super().get(*args, **kwargs)

    async def post(self, *args, **kwargs):
        values = self.get_request_body()
        values['project_id'] = kwargs['project_id']
        values['username'] = self._current_user.username
        dependent_project = await models.project(values['project_id'],
                                                 self.application)
        selected_automations = await automations.retrieve_automations(
            self.application, values.get('automations', []),
            dependent_project.project_type.id)

        result = await self.postgres_execute(self.POST_SQL, values,
                                             f'post-{self.NAME}')
        if not result.row_count:
            raise errors.DatabaseError('Failed to create project dependency',
                                       title='Failed to create record')

        dependency = models.ProjectDependency(
            project_id=result.row['project_id'],
            dependency_id=result.row['dependency_id'],
            created_at=result.row['created_at'],
            created_by=result.row['created_by'])

        try:
            await self._run_automations(dependency, selected_automations)
        except Exception as error:
            self.logger.exception('_run_automations failure: %s', error)
            self.logger.error(
                'removing dependency (project: %s, '
                'dependency: %s) due to error', dependency.project_id,
                dependency.dependency_id)
            await self.postgres_execute(
                'DELETE FROM v1.project_dependencies'
                '     WHERE project_id = %(project_id)s'
                '       AND dependency_id = %(dependency_id)s', {
                    'project_id': dependency.project_id,
                    'dependency_id': dependency.dependency_id
                })
            raise errors.InternalServerError('Failed to run automations: %s',
                                             error) from None

        await self.index_document(dependent_project.id)
        self.send_response(vars(dependency))


class RecordRequestHandler(projects.ProjectAttributeCRUDMixin,
                           _DependencyRequestMixin, base.CRUDRequestHandler):

    NAME = 'project-dependency'

    DELETE_SQL = re.sub(
        r'\s+', ' ', """\
        DELETE FROM v1.project_dependencies
         WHERE project_id=%(project_id)s
           AND dependency_id=%(dependency_id)s""")

    async def delete(self, *args, **kwargs):
        body = self.get_request_body() if self.request.body else {}
        dependency = await models.project_dependency(kwargs['project_id'],
                                                     kwargs['dependency_id'],
                                                     self.application)
        if dependency is None:
            raise errors.ItemNotFound(instance=self.request.uri)
        dependent_project = await models.project(kwargs['project_id'],
                                                 self.application)
        selected_automations = await automations.retrieve_automations(
            self.application, body.get('automations', []),
            dependent_project.project_type.id)

        result = await self.postgres_execute(self.DELETE_SQL, kwargs,
                                             f'delete-{self.NAME}')
        if not result.row_count:
            raise errors.ItemNotFound(instance=self.request.uri)

        try:
            await self._run_automations(dependency, selected_automations)
        except Exception as error:
            self.logger.exception('_run_automations failure: %s', error)
            self.logger.error(
                're-adding dependency (project: %s, '
                'dependency: %s) due to error', dependency.project_id,
                dependency.dependency_id)
            await self.postgres_execute(
                self.POST_SQL, {
                    'project_id': dependency.project_id,
                    'dependency_id': dependency.dependency_id,
                    'created_by': dependency.created_by
                })
            raise errors.InternalServerError('Failed to run automations: %s',
                                             error) from None

        await self.index_document(kwargs['project_id'])
        self.set_status(204, reason='Item Deleted')
