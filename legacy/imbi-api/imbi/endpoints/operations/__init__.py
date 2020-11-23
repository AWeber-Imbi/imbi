"""
Operations Views

"""
from tornado import web

from . import changelog

URLS = [
    web.url(r'/operations/changelog', changelog.RequestHandler)
]
