"""
Integration Endpoints

"""
from tornado import web

from . import (
    automations,
    github,
    gitlab,
    google,
    integrations,
    notifications,
    oauth2,
)

SLUG = r'[\w_\-%\+]+'

URLS = [
    web.url(r'^/github/auth', github.RedirectHandler, name='github-callback'),
    web.url(r'^/github/projects/(?P<project_id>[0-9]+)/tags$',
            github.ProjectTagsHandler),
    web.url(r'^/github/projects/(?P<project_id>[0-9]+)/deployments$',
            github.ProjectDeploymentsHandler),
    web.url(r'^/gitlab/auth', gitlab.RedirectHandler, name='gitlab-callback'),
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
    web.url(fr'/integrations/(?P<integration_name>{SLUG})/oauth2',
            oauth2.RecordRequestHandler,
            name='oauth2-management'),
] + notifications.URLS
