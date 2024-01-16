from tornado import web

from . import filters
from . import notifications

PREFIX = r'^/integrations/(?P<integration_name>[^/]+)/notifications'
SLUG = r'[\w_\-%\+]+'

URLS = [
    web.url(fr'{PREFIX}/?$',
            notifications.CollectionRequestHandler,
            name=notifications.CollectionRequestHandler.NAME),
    web.url(fr'{PREFIX}/(?P<name>{SLUG})$',
            notifications.RecordRequestHandler,
            name=notifications.RecordRequestHandler.NAME),
    web.url(fr'{PREFIX}/(?P<notification_name>{SLUG})/filters$',
            filters.CollectionRequestHandler,
            name=filters.CollectionRequestHandler.NAME),
    web.url(
        fr'{PREFIX}/(?P<notification_name>{SLUG})/filters/(?P<name>{SLUG})$',
        filters.RecordRequestHandler,
        name=filters.RecordRequestHandler.NAME),
]
