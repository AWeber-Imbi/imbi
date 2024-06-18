import re

from imbi.endpoints import base


class RequestHandler(base.AuthenticatedRequestHandler):
    NAME = 'reports-component-usage'
    SQL = re.sub(
        r'\s+', ' ', """\
        SELECT c.name, c.package_url, c.active_version, c.status,
               COUNT(v.id) AS version_count,
               COUNT(p.project_id) AS project_count
          FROM v1.components AS c
          JOIN v1.component_versions AS v ON v.package_url = c.package_url
          LEFT JOIN v1.project_components AS p ON p.version_id = v.id
         GROUP BY c.name, c.package_url, c.active_version
        """)

    async def get(self) -> None:
        result = await self.postgres_execute(self.SQL, metric_name=self.NAME)
        self.send_response(result.rows)
