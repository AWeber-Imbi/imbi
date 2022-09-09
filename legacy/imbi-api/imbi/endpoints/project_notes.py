from __future__ import annotations

from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):
    NAME = 'project-notes'

    ID_KEY = ['id', 'project_id']
    """Tell the framework what parts of the path to use as query parameters"""

    FIELDS = ['content', 'project_id']
    """Identifies properties in the POST request

    These can come from the request body or the path parameters and
    are the values available to `POST_SQL`.  Note that `username` is
    added automatically based on the current user.

    """

    ITEM_NAME = 'project-note'
    """Identifies the route name for a single item in the collection."""

    COLLECTION_SQL = (
        'SELECT id, content, project_id, created_by, updated_by'
        '  FROM v1.project_notes'
        ' WHERE project_id = %(project_id)s'
        ' ORDER BY created_at DESC, id DESC'
    )

    GET_SQL = (
        'SELECT id, content, created_by, project_id, updated_by'
        '  FROM v1.project_notes'
        ' WHERE id = %(id)s'
    )

    POST_SQL = (
        'INSERT INTO v1.project_notes(project_id, content, created_by)'
        '     VALUES (%(project_id)s, %(content)s, %(username)s)'
        '  RETURNING *'
    )


class RecordHandler(base.CRUDRequestHandler):
    NAME = 'project-note'
    ID_KEY = ['id', 'project_id']
    GET_SQL = (
        'SELECT id, content, created_by, project_id, updated_by'
        '  FROM v1.project_notes'
        ' WHERE id = %(id)s'
        '   AND project_id = %(project_id)s'
    )
    PATCH_SQL = (
        'UPDATE v1.project_notes'
        '   SET updated_by = %(username)s,'
        '       updated_at = CURRENT_TIMESTAMP,'
        '       content = %(content)s'
        ' WHERE id = %(current_id)s'
        '   AND project_id = %(current_project_id)s'
    )
    DELETE_SQL = (
        'DELETE FROM v1.project_notes'
        ' WHERE id = %(id)s'
        '   AND project_id = %(project_id)s'
    )
