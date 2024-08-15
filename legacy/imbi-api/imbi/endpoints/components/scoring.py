from __future__ import annotations

import logging

import sprockets_postgres
import typing_extensions as typing

import imbi.models
import imbi.opensearch.project
from imbi.endpoints.components import models

if typing.TYPE_CHECKING:
    import imbi.app


async def update_component_score_for_project(
        project_id: int,
        connector: sprockets_postgres.PostgresConnector,
        app: imbi.app.Application,
        *,
        index_project: bool = True):
    logger = logging.getLogger(__package__).getChild(
        'update_component_score_for_project')

    fact_id = app.settings['component_scoring']['project_fact_type_id']
    if not fact_id:
        return

    transaction: sprockets_postgres.PostgresConnector
    async with connector.transaction() as transaction:
        result = await transaction.execute(
            'SELECT value'
            '  FROM v1.project_facts'
            ' WHERE project_id = %(project_id)s'
            '   AND fact_type_id = %(fact_id)s', {
                'project_id': project_id,
                'fact_id': fact_id
            })
        current_status = result.row['value'] if result else None

        result = await transaction.execute(
            'SELECT c.package_url, c.status, c.active_version, v.version'
            '  FROM v1.project_components AS p'
            '  JOIN v1.component_versions AS v'
            '    ON p.package_url = v.package_url AND p.version_id = v.id'
            '  JOIN v1.components AS c ON v.package_url = c.package_url'
            ' WHERE project_id = %(project_id)s'
            '   AND ((c.status = %(active)s AND c.active_version IS NOT NULL)'
            '        OR c.status != %(active)s)', {
                'active': 'Active',
                'project_id': project_id,
            },
            metric_name='retrieve-tracked-components')

        outdated = set()
        up_to_date = set()
        deprecated = set()
        forbidden = set()
        rows = [
            models.ProjectComponentRow.model_validate(row) for row in result
        ]
        for row in rows:
            logger.debug('examining %s', row)
            if row.status == models.ComponentStatus.ACTIVE:
                if row.version in row.active_version:
                    up_to_date.add(row.package_url)
                else:
                    outdated.add(row.package_url)
            elif row.status == models.ComponentStatus.DEPRECATED:
                deprecated.add(row.package_url)
            elif row.status == models.ComponentStatus.FORBIDDEN:
                forbidden.add(row.package_url)

        logger.debug('%s up_to_date, %s outdated, %s deprecated, %s forbidden',
                     len(up_to_date), len(outdated), len(deprecated),
                     len(forbidden))
        if not deprecated and not forbidden and not outdated:
            status = models.ProjectStatus.OKAY
        elif not forbidden and (len(up_to_date) > len(outdated) or deprecated):
            status = models.ProjectStatus.NEEDS_WORK
        else:
            status = models.ProjectStatus.UNACCEPTABLE

        if status != current_status:
            logger.info(
                'updating component score from %s to %s for project %s',
                current_status or 'NULL', status, project_id)
            await transaction.execute(
                'INSERT INTO v1.project_facts(project_id, fact_type_id, value,'
                '                             recorded_at, recorded_by)'
                '     VALUES (%(project_id)s, %(fact_id)s, %(value)s,'
                '             CURRENT_TIMESTAMP, %(recorded_by)s)'
                ' ON CONFLICT (project_id, fact_type_id)'
                '   DO UPDATE'
                '         SET value = %(value)s,'
                '             recorded_at = CURRENT_TIMESTAMP,'
                '             recorded_by = %(recorded_by)s', {
                    'project_id': project_id,
                    'fact_id': fact_id,
                    'value': status,
                    'recorded_by': 'system'
                },
                metric_name='set-component-score')

            if index_project:
                project = await imbi.models.project(project_id, app)
                if project is not None:  # may have been removed
                    index = imbi.opensearch.project.ProjectIndex(app)
                    await index.index_document(project)


async def enable_component_scoring(app: imbi.app.Application) -> None:
    """Enable the project component scoring feature

    1. creates the database rows for the fact type
    2. updates app.settings[component_scoring]

    """
    logger = logging.getLogger(__package__).getChild(
        'enable_component_scoring')

    app_config = app.settings.setdefault('component_scoring', {})
    if app_config['enabled']:  # nothing to do here
        return

    connector: sprockets_postgres.PostgresConnector
    transaction: sprockets_postgres.PostgresConnector
    async with app.postgres_connector() as connector:
        async with connector.transaction() as transaction:
            # Create a new project fact using the configured name
            fact_name = app_config['fact_name']
            logger.info('Creating %r project fact type', fact_name)
            result = await transaction.execute(
                'INSERT INTO v1.project_fact_types('
                '               created_by, name, fact_type, data_type,'
                '               project_type_ids, ui_options)'
                '     VALUES (%(created_by)s, %(name)s, %(fact_type)s,'
                '             %(data_type)s, %(empty)s, %(ui_options)s)'
                '  RETURNING id', {
                    'created_by': 'system',
                    'data_type': 'integer',
                    'empty': [],
                    'fact_type': 'range',
                    'name': fact_name,
                    'ui_options': ['read-only'],
                })

            # Create range values that encompass the ProjectStatus enum
            # values in imbi.endpoints.components.models. Note that we start
            # at zero and use a value slightly greater than that upper bound
            # of the last range as the start of the next range.
            app_config['project_fact_type_id'] = result.row['id']
            lower_bound = 0.0
            for upper_bound in sorted(models.ProjectStatus):
                await transaction.execute(
                    'INSERT INTO v1.project_fact_type_ranges('
                    '               created_by, fact_type_id, min_value,'
                    '               max_value, score)'
                    '     VALUES (%(created_by)s, %(fact_type_id)s,'
                    '             %(min_value)s, %(max_value)s,'
                    '             %(max_value)s)', {
                        'created_by': 'system',
                        'fact_type_id': app_config['project_fact_type_id'],
                        'max_value': float(upper_bound),
                        'min_value': lower_bound,
                    })
                lower_bound = float(upper_bound) + 0.01

    logger.info('Created %r project fact type with ID %r', fact_name,
                app_config['project_fact_type_id'])
