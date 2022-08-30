"""
System Reports

"""
from tornado import web

from . import gitlab, sentry, sonarqube

URLS = [
    web.url(r'^/ui/automations/gitlab/commit',
            gitlab.InitialCommitRequestHandler),
    web.url(r'^/ui/automations/gitlab/create', gitlab.CreationRequestHandler),
    web.url(r'^/ui/automations/sentry/create',
            sentry.ProjectCreationRequestHandler),
    web.url(r'^/ui/automations/sonarqube/create',
            sonarqube.CreationRequestHandler),
]
