from tornado import web

from . import handlers

URLS = [
    web.url(r'^/projects/(?P<project_id>\d+)/configuration/ssm$',
            handlers.CollectionRequestHandler,
            name='project-ssm-parameters'),
    web.url(
        r'^/projects/(?P<project_id>\d+)/configuration/ssm/'
        r'(?P<name>[\w_\-%\+]+)$',
        handlers.RecordRequestHandler,
        name='project-ssm-parameter'),
]
