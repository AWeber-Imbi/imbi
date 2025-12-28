from imbi.endpoints import base
from imbi.endpoints.components import models


class RequestHandler(base.AuthenticatedRequestHandler):
    NAME = 'reports-outdated-projects'

    async def get(self) -> None:
        result = await self.postgres_execute(
            'SELECT c.project_id, v.status, p.name AS project_name,'
            '       n.name AS project_namespace,'
            '       COUNT(c.version_id) AS num_components'
            '  FROM v1.project_components AS c'
            '  JOIN v1.component_versions AS v'
            '    ON v.package_url = c.package_url AND v.id = c.version_id'
            '  JOIN v1.projects AS p ON p.id = c.project_id'
            '  JOIN v1.namespaces AS n ON n.id = p.namespace_id'
            ' GROUP BY c.project_id, v.status, p.name, n.name'
            ' ORDER BY c.project_id',
            metric_name=self.NAME)

        # using a helper here makes it easy to pick up the
        # values from the last set of rows
        def add_current_to_report() -> None:
            outdated = sum(
                current.get(k, 0) for k in models.OUTDATED_COMPONENT_STATUSES)
            if outdated:
                current['component_score'] = models.ProjectStatus.calculate(
                    current)
                # pivot from 'Up-to-date' to 'up_to_date'
                for e in models.ProjectComponentStatus:
                    current[e.name.lower()] = current.pop(e.value)
                report_rows.append(current.copy())

        report_rows = []
        current = {}
        empty = {e.value: 0 for e in models.ProjectComponentStatus}

        for row in result.rows:
            if row['project_id'] != current.get('project_id'):
                add_current_to_report()
                current = empty | {
                    'project_id': row['project_id'],
                    'project_namespace': row['project_namespace'],
                    'project_name': row['project_name']
                }
            current[row['status']] = row['num_components']
        add_current_to_report()  # capture the final in-progress row

        self.send_response(report_rows)
