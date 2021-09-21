"""
Application Status View

"""
import platform

import distro
from sprockets.mixins import mediatype
from tornado import web

from imbi import version

MAINTENANCE = 'maintenance'
OK = 'ok'


class RequestHandler(mediatype.ContentMixin,
                     web.RequestHandler):
    """Returns the current status"""
    NAME = 'status'

    SYSTEM = {
        'language': {
            'name': 'python',
            'implementation': platform.python_implementation(),
            'version': platform.python_version()
        },
        'os': {
            'name': distro.name(),
            'version': distro.version()
        }
    }

    async def get(self):
        """Tornado RequestHandler GET request endpoint for reporting status"""
        self.set_status(self._status_response_code())
        self.send_response({
            'started_at': self.application.started_at_str,
            'status': OK if self.application.ready_to_serve else MAINTENANCE,
            'system': self.SYSTEM,
            'version': version})

    def set_default_headers(self) -> None:
        """Override the default headers, setting the Server response header"""
        super().set_default_headers()
        self.set_header('Server', self.settings['server_header'])

    def _status_response_code(self):
        """Return the status code for the request based upon the application
        status.
        :rtype: int
        """
        if self.application.ready_to_serve:
            return 200
        return 503
