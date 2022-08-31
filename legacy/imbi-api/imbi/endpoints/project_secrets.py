from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):
    NAME = 'project-secrets'
    ID_KEY = ['project_id', 'name']
    ITEM_NAME = 'project-secret'
    FIELDS = ['project_id']
    TTL = 300

    COLLECTION_SQL = (
        'SELECT s.project_id, p.slug AS project_slug, s.name, s.value,'
        '       s.created_by, s.last_modified_by'
        '  FROM v1.project_secrets AS s'
        '  JOIN v1.projects AS p ON s.project_id = p.id'
        ' WHERE s.project_id = %(project_id)s'
    )

    async def get(self, *args, **kwargs):
        result = await self.postgres_execute(self.COLLECTION_SQL, kwargs,
                                             metric_name=f'get-{self.NAME}')
        for row in result.rows:
            row['value'] = self.application.decrypt_value(row['value'])
        self.send_response(result.rows)
