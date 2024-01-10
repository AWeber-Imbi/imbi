"""
Integration Endpoints

"""
from tornado import web

from . import _apps, gitlab, google

URLS = [
    web.url(r'^/gitlab/auth', gitlab.RedirectHandler),
    web.url(r'^/gitlab/namespaces', gitlab.UserNamespacesHandler),
    web.url(r'^/gitlab/projects', gitlab.ProjectsHandler),
    web.url(r'^/google/auth', google.RedirectHandler),
    web.url(r'^/integrations$',
            _apps.CollectionRequestHandler,
            name='integrations'),
    web.url(r'^/integrations/(?P<name>[\w_\-%\+]+)$',
            _apps.RecordRequestHandler,
            name='integration'),
]
