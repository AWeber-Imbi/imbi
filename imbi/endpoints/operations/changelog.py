"""
Request Handler for the Change Log

"""
from tornado import web

from imbi.endpoints import base


class RequestHandler(base.RequestHandler):

    NAME = 'operations-change-log'

    @web.authenticated
    def get(self, *args, **kwargs):
        return self.send_response([])
