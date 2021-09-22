"""
Serve the OpenAPI related Endpoints

"""
import datetime

from imbi.endpoints import base


class RequestHandler(base.RequestHandler):
    """Services up the swagger related things rendered via Tornado's template
    system.

    """
    NAME = 'openapi'
    TTL = 300

    def get(self, *args):
        template = 'docs.html'
        if args and args[0] == 'openapi.yaml':
            template = 'openapi.yaml'
            self.set_header('Content-Type', 'text/yaml')
        stat = (self.application.settings['template_path'] / template).stat()
        self._add_last_modified_header(
            datetime.datetime.utcfromtimestamp(int(stat.st_mtime)))
        self._add_response_caching_headers(self.TTL)
        self.render(
            template, **{
                'host': self.request.host,
                'scheme': self.request.protocol,
                'settings': self.settings})
