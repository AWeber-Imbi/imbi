from psycopg2 import sql

from imbi.endpoints import base


class UserRequestHandler(base.AuthenticatedRequestHandler):

    NAME = 'ui-user'

    def get(self, *args, **kwargs):
        user = self.current_user.as_dict()
        del user['password']
        self.send_response(user)


class AvailableAutomationsHandler(base.AuthenticatedRequestHandler):

    NAME = 'available-automations'

    async def get(self, *args, **kwargs):
        automation_categories = self.get_query_arguments('category')
        project_type_ids = self.get_query_arguments('project_type_id')
        project_types = self.get_query_arguments('project_type')

        query = sql.SQL('SELECT DISTINCT a.name AS automation_name,'
                        '                i.name AS integration_name,'
                        '                a.slug AS automation_slug'
                        '          FROM v1.integrations AS i'
                        '          JOIN v1.automations AS a'
                        '            ON a.integration_name = i.name'
                        '     LEFT JOIN v1.user_oauth2_tokens AS t'
                        '            ON t.integration = i.name'
                        '         WHERE (i.api_secret IS NOT NULL'
                        '                OR t.username = %(username)s)')
        filter_clauses = []
        identification_clauses = []
        params = {'username': self._current_user.username}

        if automation_categories:
            filter_clauses.append(
                sql.SQL('a.categories && ARRAY[%(categories)s]::{}[]').format(
                    sql.Identifier('v1', 'automation_category_type')))
            params['categories'] = automation_categories

        if project_type_ids:
            identification_clauses.append(
                sql.SQL('EXISTS (SELECT aa.automation_id'
                        '          FROM v1.available_automations AS aa'
                        '         WHERE aa.automation_id = a.id'
                        '           AND aa.project_type_id IN %(type_ids)s)'))
            params['type_ids'] = tuple(project_type_ids)
        if project_types:
            identification_clauses.append(
                sql.SQL('EXISTS (SELECT aa.automation_id'
                        '          FROM v1.available_automations AS aa'
                        '          JOIN v1.project_types AS pt'
                        '            ON pt.id = aa.project_type_id'
                        '         WHERE aa.automation_id = a.id'
                        '           AND pt.slug IN %(project_types)s)'))
            params['project_types'] = tuple(project_types)

        if filter_clauses:
            query = sql.SQL(' AND ').join([query] + filter_clauses)
        if identification_clauses:
            clause = sql.SQL('(') + sql.SQL(' OR ').join(
                identification_clauses) + sql.SQL(')')
            query = sql.SQL(' AND ').join([query, clause])

        result = await self.postgres_execute(query, params)
        self.send_response(result.rows)
