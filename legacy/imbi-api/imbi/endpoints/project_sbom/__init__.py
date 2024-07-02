from tornado import web

from . import handlers

URLS = [
    web.url(r'^/projects/(?P<project_id>\d+)/sbom$',
            handlers.SBOMInjectionHandler),
]
