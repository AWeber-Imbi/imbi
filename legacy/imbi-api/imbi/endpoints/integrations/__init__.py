"""
Integration Endpoints

"""
from tornado import web

from . import gitlab, google, integrations, notifications

URLS = [
    web.url(r'^/gitlab/auth', gitlab.RedirectHandler),
    web.url(r'^/gitlab/namespaces', gitlab.UserNamespacesHandler),
    web.url(r'^/gitlab/projects', gitlab.ProjectsHandler),
    web.url(r'^/google/auth', google.RedirectHandler),
    web.url(r'^/integrations$',
            integrations.CollectionRequestHandler,
            name='integrations'),
    web.url(r'^/integrations/(?P<name>[\w_\-%\+]+)$',
            integrations.RecordRequestHandler,
            name='integration'),
] + notifications.URLS
