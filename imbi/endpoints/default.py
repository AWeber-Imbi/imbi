"""
Request Handler used for rendering errors

"""
from tornado import web

from imbi.endpoints import base


class RequestHandler(base.RequestHandler):

    ENDPOINT = 'not-found'

    def get(self, *args, **kwargs):
        raise web.HTTPError(404)
