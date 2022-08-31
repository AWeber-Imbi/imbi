from __future__ import annotations

from imbi import models
from imbi.automations import base
from imbi.clients import sentry


class SentryCreateProjectAutomation(base.Automation):

    def __init__(self, application, project_id, current_user, db) -> None:
        super().__init__(application, current_user, db)
        self.client = sentry.SentryClient(application)
        self.imbi_project_id = project_id
        self.project: models.Project | None = None
        self.settings = self.automation_settings['sentry']

    async def prepare(self) -> list[str]:
        if not self.client.enabled:
            self._add_error('Sentry integration is not enabled')
        else:
            project = await self._get_project(self.imbi_project_id)
            if project is None:
                self._add_error('Project id {} does not exist',
                                self.imbi_project_id)
            elif not project.namespace.sentry_team_slug:
                self._add_error(
                    'Namespace {} does not have a sentry slug, not creating'
                    ' sentry project for project {}', project.namespace.slug,
                    self.imbi_project_id)
            else:
                self.project = project
        return self.errors

    async def run(self) -> sentry.ProjectInfo:
        project = await self.client.create_project(
            self.project.namespace.sentry_team_slug, self.project.name)
        try:
            await self.db.execute(
                'UPDATE v1.projects'
                '   SET sentry_project_slug = %(slug)s,'
                '       last_modified_at = CURRENT_TIMESTAMP,'
                '       last_modified_by = %(username)s'
                ' WHERE id = %(imbi_project_id)s', {
                    'imbi_project_id': self.imbi_project_id,
                    'slug': project.slug,
                    'username': self.user.username,
                }
            )
            if self.settings.get('project_link_type_id'):
                await self.db.execute(
                    '  INSERT INTO v1.project_links(project_id, link_type_id,'
                    '                               created_by, url)'
                    '       VALUES (%(imbi_project_id)s,'
                    '               %(project_link_type_id)s, %(username)s,'
                    '               %(url)s) '
                    '  ON CONFLICT '
                    'ON CONSTRAINT project_links_pkey'
                    '    DO UPDATE'
                    '          SET last_modified_at = CURRENT_TIMESTAMP,'
                    '              last_modified_by = %(username)s,'
                    '              url = %(url)s', {
                        'imbi_project_id': self.imbi_project_id,
                        'project_link_type_id':
                            self.settings['project_link_type_id'],
                        'url': project.link,
                        'username': self.user.username,
                    }
                )
            for name, value in project.keys.items():
                await self.db.execute(
                    '  INSERT INTO v1.project_secrets(project_id, name, value,'
                    '                                 created_by)'
                    '       VALUES (%(imbi_project_id)s, %(key_name)s,'
                    '               %(key_value)s, %(username)s)'
                    '  ON CONFLICT '
                    'ON CONSTRAINT project_secrets_pkey'
                    '    DO UPDATE'
                    '          SET value = %(key_value)s,'
                    '              last_modified_at = CURRENT_TIMESTAMP,'
                    '              last_modified_by = %(username)s', {
                        'imbi_project_id': self.imbi_project_id,
                        'key_name': f'sentry_{name.lower()}',
                        'key_value': self.application.encrypt_value(value),
                        'username': self.user.username,
                    }
                )

        # Using a wide catch of Exception here to ensure that we remove
        # the sentry project if we fail to save it for any reason.  This
        # prevents orphaning sentry projects when we have a DB problem.
        except Exception as error:
            self.logger.error('removing sentry project %s due to error: %s',
                              project.slug, error)
            await self.client.remove_project(project.slug)
            raise

        return project
