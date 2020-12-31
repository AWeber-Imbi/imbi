"""
Application Views

"""
from os import path

from tornado import web

from . import (
    admin,
    openapi,
    operations,
    project,
    settings,
    status,
    ui
)

URLS = [
    web.url(r'^/$', ui.IndexRequestHandler),
    web.url(r'^/test.html$', ui.TestRequestHandler),
    web.url(r'^/schema/(.*)$', web.StaticFileHandler,
            {'path': path.abspath(
                path.join(path.dirname(__file__), '..', 'schema'))}),
    web.url(r'^/status$', status.RequestHandler),
    web.url(r'^/api-docs/$', openapi.RequestHandler),
    web.url(r'^/api-docs/(openapi.yaml)$', openapi.RequestHandler),
    web.url(r'^/ui/groups$', ui.GroupsRequestHandler),
    web.url(r'^/ui/login$', ui.LoginRequestHandler),
    web.url(r'^/ui/logout$', ui.LogoutRequestHandler),
    web.url(r'^/ui/settings$', ui.SettingsRequestHandler),
    web.url(r'^/ui/user$', ui.UserRequestHandler),
    web.url(r'^/ui/.*$', ui.IndexRequestHandler)
] + operations.URLS + project.URLS + settings.URLS + admin.URLS
