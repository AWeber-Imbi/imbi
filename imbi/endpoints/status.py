"""
Application Status View

"""
import datetime
import platform

import distro
import isodate
from sprockets.mixins import mediatype
from tornado import web

from imbi import version

MAINTENANCE = 'maintenance'
OK = 'ok'


class RequestHandler(mediatype.ContentMixin,
                     web.RequestHandler):
    """Returns the current status and internal metrics"""
    ENDPOINT = 'Status'

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
        prune = self.get_argument('flush', 'false') == 'true'
        self.set_status(self._status_response_code())
        self.send_response({
            'counters': await self.application.stats.counters(prune),
            'durations': await self.application.stats.durations(prune),
            'postgres': await self.application.postgres_status(),
            'started_at': self.application.started_at_str,
            'status': OK if self.application.ready_to_serve else MAINTENANCE,
            'system': self.SYSTEM,
            'uptime': isodate.duration_isoformat(
                datetime.datetime.now(datetime.timezone.utc) -
                self.application.started_at),
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
