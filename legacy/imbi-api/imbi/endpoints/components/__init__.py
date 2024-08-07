from tornado import web

from . import handlers

URLS = [
    web.url(r'/components$',
            handlers.CollectionRequestHandler,
            name='components'),
    web.url(r'/components/(?P<package_url>.+)$',
            handlers.RecordRequestHandler,
            name='component'),
    web.url(r'^/projects/(?P<project_id>\d+)/components$',
            handlers.ProjectComponentsRequestHandler,
            name='project-components'),
]
