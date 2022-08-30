import re

from imbi.endpoints import base


class _RequestHandlerMixin:

    ID_KEY = 'id'
    FIELDS = ['id', 'name', 'slug', 'icon_class', 'maintained_by',
              'gitlab_group_name', 'sentry_team_slug']
    DEFAULTS = {'icon_class': 'fas fa-users', 'maintained_by': []}

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, "name", created_at, created_by,
               last_modified_at, last_modified_by,
               slug, icon_class, maintained_by,
               gitlab_group_name, sentry_team_slug
          FROM v1.namespaces WHERE id=%(id)s""")


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):

    NAME = 'namespaces'
    ITEM_NAME = 'namespace'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """ \
        SELECT id, "name", slug, icon_class, maintained_by, gitlab_group_name,
               sentry_team_slug
          FROM v1.namespaces ORDER BY "name" ASC""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.namespaces
                    ("name", created_by, slug, icon_class, "maintained_by",
                     gitlab_group_name, sentry_team_slug)
             VALUES (%(name)s, %(username)s, %(slug)s, %(icon_class)s,
                     %(maintained_by)s, %(gitlab_group_name)s,
                     %(sentry_team_slug)s)
          RETURNING id""")


class RecordRequestHandler(_RequestHandlerMixin, base.AdminCRUDRequestHandler):

    NAME = 'namespace'

    DELETE_SQL = 'DELETE FROM v1.namespaces WHERE id=%(id)s'

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.namespaces
           SET "name" = %(name)s,
               last_modified_at = CURRENT_TIMESTAMP,
               last_modified_by = %(username)s,
               slug = %(slug)s,
               icon_class = %(icon_class)s,
               "maintained_by" = %(maintained_by)s,
               gitlab_group_name = %(gitlab_group_name)s,
               sentry_team_slug = %(sentry_team_slug)s
         WHERE id=%(id)s""")
