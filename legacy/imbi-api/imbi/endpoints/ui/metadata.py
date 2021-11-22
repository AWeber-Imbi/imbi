import asyncio

from imbi.endpoints import base, cookie_cutters, environments, groups, \
    namespaces, fact_types, project_link_types, project_types


class RequestHandler(base.RequestHandler):

    NAME = 'metadata'

    async def get(self) -> None:
        """Return all metadata in a single request"""

        results = await asyncio.gather(
            self.postgres_execute(
                cookie_cutters.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='cookie-cutters'),
            self.postgres_execute(
                environments.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='environments'),
            self.postgres_execute(
                groups.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='groups'),
            self.postgres_execute(
                namespaces.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='namespaces'),
            self.postgres_execute(
                fact_types.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='project-fact-types'),
            self.postgres_execute(
                project_link_types.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='project-link-types'),
            self.postgres_execute(
                project_types.CollectionRequestHandler.COLLECTION_SQL,
                metric_name='project-types')
        )

        self.send_response({
            'cookie_cutters': results[0].rows,
            'environments': results[1].rows,
            'groups': results[2].rows,
            'namespaces': results[3].rows,
            'project_fact_types': results[4].rows,
            'project_link_types': results[5].rows,
            'project_types': results[6].rows
        })
