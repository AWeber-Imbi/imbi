"""
System Reports

"""
from tornado import web

from . import authentication, index, project_actions, settings, user

IndexRequestHandler = index.IndexRequestHandler

URLS = [
    web.url(r'^/ui/', index.IndexRequestHandler),
    web.url(r'/ui/connections/(?P<integration_name>.*)',
            authentication.ConnectionRequestHandler),
    web.url(r'^/ui/login$', authentication.LoginRequestHandler),
    web.url(r'^/ui/login/google$', authentication.GoogleLoginRequestHandler),
    web.url(r'^/ui/logout$', authentication.LogoutRequestHandler),
    web.url(r'^/ui/settings$', settings.RequestHandler),
    web.url(r'^/ui/user$', user.UserRequestHandler),
    web.url(r'^/ui/available-automations$', user.AvailableAutomationsHandler),
    web.url(r'^/ui/projects/(?P<project_id>[0-9]+)/actions$',
            project_actions.AvailableActionsHandler),
    web.url(r'^/ui/.*$', index.IndexRequestHandler)
]
