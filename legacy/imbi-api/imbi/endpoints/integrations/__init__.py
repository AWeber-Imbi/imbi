"""
Integration Endpoints

"""
from tornado import web

from . import automations, gitlab, google, integrations, notifications

SLUG = r'[\w_\-%\+]+'

URLS = [
    web.url(r'^/gitlab/auth', gitlab.RedirectHandler),
    web.url(r'^/gitlab/namespaces', gitlab.UserNamespacesHandler),
    web.url(r'^/gitlab/projects', gitlab.ProjectsHandler),
    web.url(r'^/google/auth', google.RedirectHandler),
    web.url(r'^/integrations$',
            integrations.CollectionRequestHandler,
            name='integrations'),
    web.url(fr'^/integrations/(?P<name>{SLUG})$',
            integrations.RecordRequestHandler,
            name='integration'),
    web.url(fr'/integrations/(?P<integration_name>{SLUG})/automations/?',
            automations.CollectionRequestHandler,
            name='automations'),
    web.url(
        fr'/integrations/(?P<integration_name>{SLUG})'
        fr'/automations/(?P<slug>{SLUG})',
        automations.RecordRequestHandler,
        name='automation'),
] + notifications.URLS
