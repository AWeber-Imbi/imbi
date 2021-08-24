"""
Integration Endpoints

"""
from tornado import web

from . import gitlab, oauth2

URLS = [
    web.url(r'^/gitlab/auth', gitlab.RedirectHandler),
    web.url(r'^/gitlab/namespaces', gitlab.UserNamespacesHandler),
    web.url(r'^/gitlab/projects', gitlab.ProjectsHandler),
    web.url(r'^/integrations$', oauth2.CollectionRequestHandler),
    web.url(r'^/integrations/(?P<name>[\w_\-%\+]+)$',
            oauth2.RecordRequestHandler, name='integration')
]
