"""
Application Metrics

"""
import datetime

import isodate
from sprockets.mixins import mediatype
from tornado import web


class RequestHandler(mediatype.ContentMixin,
                     web.RequestHandler):
    """Returns internal metrics"""
    ENDPOINT = 'metrics'

    async def get(self):
        """Tornado RequestHandler GET request endpoint for reporting status"""
        prune = self.get_argument('flush', 'false') == 'true'
        self.send_response({
            'counters': await self.application.stats.counters(prune),
            'durations': await self.application.stats.durations(prune),
            'postgres': await self.application.postgres_status(),
            'uptime': isodate.duration_isoformat(
                datetime.datetime.now(datetime.timezone.utc) -
                self.application.started_at)})

    def set_default_headers(self) -> None:
        """Override the default headers, setting the Server response header"""
        super().set_default_headers()
        self.set_header('Server', self.settings['server_header'])
