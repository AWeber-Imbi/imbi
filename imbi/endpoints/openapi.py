"""
Serve the Swagger Endpoints

"""
import datetime
import os
from os import path

from imbi.endpoints import base


class RequestHandler(base.RequestHandler):
    """Services up the swagger related things rendered via Tornado's template
    system.

    """
    ENDPOINT = 'OpenAPI'
    TTL = 300

    def get(self, *args, **kwargs):
        template = 'docs.html'
        if args and args[0] == 'openapi.yaml':
            template = args[0]
            self.set_header('Content-Type', 'text/yaml')
        stat_result = os.stat(path.abspath(path.join(
            path.dirname(__file__), '..', 'templates', template)))
        self._add_last_modified_header(datetime.datetime.utcfromtimestamp(
            int(stat_result.st_mtime)))
        self._add_response_caching_headers(self.TTL)
        self.render(template,
                    **{'host': self.request.host,
                       'scheme': self.request.protocol,
                       'settings': self.settings})
