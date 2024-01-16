from tornado import web

from . import notifications

PREFIX = r'^/integrations/(?P<integration_name>[^/]+)/notifications'

URLS = [
    web.url(fr'{PREFIX}/?$',
            notifications.CollectionRequestHandler,
            name='notifications'),
    web.url(fr'{PREFIX}/(?P<name>[\w_\-%\+]+)$',
            notifications.RecordRequestHandler,
            name='notification'),
]
