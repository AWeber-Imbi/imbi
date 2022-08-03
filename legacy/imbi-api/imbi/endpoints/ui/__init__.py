"""
System Reports

"""
from tornado import web

from . import automations, authentication, groups, index, settings, user

IndexRequestHandler = index.IndexRequestHandler

URLS = automations.URLS + [
    web.url(r'^/ui/', index.IndexRequestHandler),
    web.url(r'^/ui/login$', authentication.LoginRequestHandler),
    web.url(r'^/ui/logout$', authentication.LogoutRequestHandler),
    web.url(r'^/ui/settings$', settings.RequestHandler),
    web.url(r'^/ui/user$', user.UserRequestHandler),
    web.url(r'^/ui/.*$', index.IndexRequestHandler)
]
