from __future__ import annotations

import asyncio
import typing
from collections import abc

import psycopg2
import pydantic
import sprockets_postgres

import imbi.opensearch.project
from imbi import common, errors
from imbi.endpoints import base


class Integration(pydantic.BaseModel):
    """Extracts selected columns from v1.integrations"""
    name: str


class NotificationRule(pydantic.BaseModel):
    """Extracts selected columns from v1.notification_rules"""
    fact_type_id: int
    pattern: common.JsonPointer


class NotificationFilter(pydantic.BaseModel):
    """Extracts selected columns from v1.notification_filters"""
    name: str
    pattern: common.JsonPointer
    operation: str
    value: str
    action: str


class Notification(pydantic.BaseModel):
    """Model of a v1.notifications row and related entities"""
    integration: Integration
    id_pattern: common.JsonPointer
    verification_token: typing.Union[str, None] = None
    documentation: typing.Union[str, None] = None
    default_action: str
    rules: typing.List[NotificationRule] = pydantic.Field(default_factory=list)
    filters: typing.List[NotificationFilter] = pydantic.Field(
        default_factory=list)


class ProjectInfo(pydantic.BaseModel):
    """Extracts selected columns from v1.projects"""
    id: int
    project_type_id: int


T: typing.TypeAlias = typing.TypeVar('T')
Pair: typing.TypeAlias = tuple[T, T]


class ProcessingHandler(base.RequestHandler):
    """Handle incoming notifications from integrated applications.

    This handler is a little strange in that it requires that the last
    portion of the path match the request method. This makes the
    configuration of a webhook clearer since you are explicitly stating
    what the expected HTTP method and information passing mechanism is.
    Most webhooks will use the `.../post` variant.  The other path
    elements identify the source integration and notification type.

    Request processing will only fail for operational or configuration
    reasons. If an incoming notification does not match an existing
    project or fails to generate an update list, then the handler will
    exit successfully. This is by design.

    If the request targets a non-existent integration or notification,
    then a 404 error will be returned. This is essentially an incorrect
    path.

    """
    async def prepare(self) -> None:
        # make sure that the appropriate handler is being invoked
        # based on the last portion of the path
        await super().prepare()
        method_from_path = self.path_kwargs['action'].upper()
        if self.request.method.upper() != method_from_path:
            raise errors.BadRequest(
                'request method %r does not match expected %r',
                self.request.method.upper(), method_from_path)

    async def _process_notification(self, integration_name, notification_name,
                                    body) -> None:
        """Process the incoming notification.

        The request processing methods (eg, `post`, `put`, etc.) are
        responsible for gathering the body of the notification from
        the request and calling this method to do the actual processing.

        """
        self.logger.name = '.'.join(
            [__package__, integration_name, notification_name])
        notification = await self._get_notification(integration_name,
                                                    notification_name)
        if not self._evaluate_filters(notification, body):
            return

        self.logger.info('processing notification %s/%s default %r',
                         integration_name, notification_name,
                         notification.default_action)
        search_index = imbi.opensearch.project.ProjectIndex(self.application)
        for project in await self._get_projects(notification, body):
            self.logger.debug('checking for updates on imbi project id=%s',
                              project.id)
            updates = await self._gather_updates(project, notification, body)
            if updates:
                self.logger.info('updating %s facts on imbi project id=%s',
                                 len(updates), project.id)
                await self._update_facts(project, updates)
                await search_index.index_document_by_id(project.id)

    async def get(self, *, integration_name: str, notification_name: str,
                  **_kwargs: str) -> None:
        body: dict[str, str | list[str] | None] = {}
        for arg, values in self.request.query_arguments.items():
            # NB ..../get?foo results in {'foo': [b'']} and NOT
            # {'foo': []} as one might otherwise expect
            if (len(values) == 0 or len(values) == 1
                    and values[0] == b''):  # pragma: no branch
                body[arg] = None
            elif len(values) == 1:
                body[arg] = values[0].decode('utf-8')
            else:
                raise errors.UnprocessableEntity(
                    'multiple query arguments with same name %r', arg)
        await self._process_notification(integration_name, notification_name,
                                         body)

    async def post(self, *, integration_name: str, notification_name: str,
                   **_kwargs: str) -> None:
        await self._process_notification(integration_name, notification_name,
                                         self.get_request_body())

    put = post

    async def _update_facts(self, project, updates) -> None:

        async with self.application.postgres_connector(
                on_duration=self.on_postgres_timing) as connector:
            for fact_type_id, value in updates.items():
                try:
                    await connector.execute(
                        'INSERT INTO v1.project_facts'
                        '            (project_id, fact_type_id, value,'
                        '             recorded_at, recorded_by)'
                        '     VALUES (%(project_id)s, %(fact_type_id)s,'
                        '             %(value)s, CURRENT_TIMESTAMP,'
                        '             %(username)s)'
                        '         ON CONFLICT (project_id, fact_type_id)'
                        '         DO UPDATE'
                        '        SET value = %(value)s,'
                        '            recorded_at = CURRENT_TIMESTAMP,'
                        '            recorded_by = %(username)s',
                        parameters={
                            'project_id': project.id,
                            'fact_type_id': fact_type_id,
                            'value': value,
                            'username': 'system'
                        },
                        metric_name='upsert-project-fact')
                except (asyncio.TimeoutError, psycopg2.Error) as error:
                    raise errors.InternalServerError(
                        'failed to update fact %s for project %s with value'
                        ' %r: %s', fact_type_id, project.id, value, error)

    async def _get_notification(self, integration_name: str,
                                notification_name: str) -> Notification:
        key = {
            'integration_name': integration_name,
            'notification_name': notification_name
        }
        queries = [
            self.postgres_execute(
                'SELECT name'
                '  FROM v1.integrations'
                ' WHERE name = %(integration_name)s',
                parameters=key,
                metric_name='fetch-integration'),
            self.postgres_execute(
                'SELECT id_pattern, verification_token, documentation,'
                '       default_action'
                '  FROM v1.integration_notifications'
                ' WHERE integration_name = %(integration_name)s'
                '   AND notification_name = %(notification_name)s',
                parameters=key,
                metric_name='fetch-notifications'),
            self.postgres_execute(
                'SELECT filter_name AS name, pattern, operation, value, action'
                '  FROM v1.notification_filters'
                ' WHERE integration_name = %(integration_name)s'
                '   AND notification_name = %(notification_name)s',
                parameters=key,
                metric_name='fetch-notification-filters'),
            self.postgres_execute(
                'SELECT fact_type_id, pattern'
                ' FROM v1.notification_rules'
                ' WHERE integration_name = %(integration_name)s'
                '   AND notification_name = %(notification_name)s',
                parameters=key,
                metric_name='fetch-notification-rules')
        ]
        results: tuple[sprockets_postgres.QueryResult, ...]
        results = await asyncio.gather(*queries)
        integration_data, notification_data, filters, rules = results

        if not integration_data.row:
            raise errors.ItemNotFound('Integration %r not found',
                                      integration_name)
        if not notification_data.row:
            raise errors.ItemNotFound('Notification %r not found',
                                      notification_name)

        integration = Integration.model_validate(integration_data.row)
        notification_data.row['integration'] = integration.model_dump()
        notification = Notification.model_validate(notification_data.row)
        notification.rules.extend(
            NotificationRule.model_validate(row) for row in rules.rows)
        notification.filters.extend(
            NotificationFilter.model_validate(row) for row in filters.rows)

        return notification

    def _coerce_value(
        self,
        constraint: str,
        notification_value: str | float | int | bool,
    ) -> Pair[int] | Pair[float] | Pair[bool] | Pair[str]:
        """Coerce the string constraint according to received value"""
        try:
            if isinstance(notification_value,
                          bool) and constraint.lower() in {'true', 'false'}:
                self.logger.debug('_coercing %r and %r to boolean', constraint,
                                  notification_value)
                return constraint.lower() == 'true', notification_value
            if isinstance(notification_value, float):
                self.logger.debug('_coercing %r and %r to float', constraint,
                                  notification_value)
                return float(constraint), notification_value
            if isinstance(notification_value, int) and constraint.isdigit():
                self.logger.debug('_coercing %r and %r to int', constraint,
                                  notification_value)
                return int(constraint, 10), notification_value
        except (TypeError, ValueError):
            self.logger.warning('failed to coerce %r to a %s', constraint,
                                notification_value.__class__.__name__)
        return constraint, notification_value

    def _evaluate_filters(self, notification: Notification, body) -> bool:
        """Evaluate the list of filters.

        If the default action is "process", then the notification
        should be processed unless there is a matching "ignore"
        filter.

        If the default action is "ignore", then the notification
        should be processed if there is at least one matching
        "process" filter and zero matching "ignore" filters.

        :returns: ``True`` if the notification should be processed
            and ``False`` otherwise

        """
        matches = []
        unspecified = object()
        for notification_filter in notification.filters:
            constraint = notification_filter.value
            value = notification_filter.pattern.resolve(body, unspecified)
            self.logger.debug('evaluating filter %s with %r',
                              notification_filter,
                              'unmatched' if value is unspecified else value)
            if value is not unspecified:
                constraint, value = self._coerce_value(constraint, value)
                if value == constraint:
                    if notification_filter.operation == '==':
                        self.logger.debug('matched %s -> %s',
                                          notification_filter.name,
                                          notification_filter.action)
                        matches.append((notification_filter, value))
                else:
                    if notification_filter.operation == '!=':
                        self.logger.debug('matched %s -> %s',
                                          notification_filter.name,
                                          notification_filter.action)
                        matches.append((notification_filter, value))

        should_process = None
        if matches:
            ignores = [(f, t) for f, t in matches if f.action == 'ignore']
            process = [(f, t) for f, t in matches if f.action == 'process']
            if ignores:
                should_process = False
                for f, v in ignores:
                    self.logger.info('ignoring %s found %r instead of %r',
                                     f.name, v, f.value)
            elif process:
                should_process = True
                for f, v in process:
                    self.logger.info('processing: %s matched %r', f.name, v)
        if should_process is None:
            self.logger.info('using default %s', notification.default_action)
            should_process = notification.default_action == 'process'
        return should_process

    async def _get_projects(self, notification: Notification,
                            body) -> abc.Iterable[ProjectInfo]:
        surrogate_project_id = notification.id_pattern.resolve(body, None)
        if surrogate_project_id is None:
            self.logger.warning('failed to find surrogate project id using %s',
                                notification.id_pattern)
            return []

        self.logger.debug('looking for project %s@%s', surrogate_project_id,
                          notification.integration.name)
        result = await self.postgres_execute(
            'SELECT p.id, p.project_type_id'
            '  FROM v1.project_identifiers AS i'
            '  JOIN v1.projects AS p ON (p.id = i.project_id)'
            ' WHERE i.external_id = %(external_id)s::TEXT'
            '   AND i.integration_name = %(integration_name)s',
            parameters={
                'external_id': surrogate_project_id,
                'integration_name': notification.integration.name,
            },
            metric_name='get-project-by-surrogate-id')
        if not result:
            self.logger.warning(
                'failed to find imbi project for %s@%s',
                surrogate_project_id,
                notification.integration.name,
            )
            return []
        return [ProjectInfo.model_validate(r) for r in result.rows]

    async def _gather_updates(self, project: ProjectInfo,
                              notification: Notification,
                              body) -> dict[int, str]:
        """Process the notification rules into a dict of updates

        :returns: a dictionary that maps from fact type ID to the new value

        """
        result = await self.postgres_execute(
            'SELECT id'
            '  FROM v1.project_fact_types'
            ' WHERE project_type_ids @> ARRAY[%s]', [project.project_type_id],
            metric_name='get-facts-types-for-notification')
        if not result:
            self.logger.debug('no project facts defined for project type %s',
                              project.project_type_id)
            return {}

        unspecified = object()
        updates = {}
        valid_fact_type_ids = {r['id'] for r in result}
        for rule in notification.rules:
            if rule.fact_type_id in valid_fact_type_ids:
                value = rule.pattern.resolve(body, unspecified)
                if value is not unspecified:
                    updates[rule.fact_type_id] = value
        return updates
