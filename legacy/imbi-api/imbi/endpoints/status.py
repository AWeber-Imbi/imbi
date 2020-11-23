"""
Application Status View

"""
from imbi import __version__
from imbi.endpoints import base

MAINTENANCE = 'maintenance'
OK = 'ok'


class RequestHandler(base.RequestHandler):
    """Implement a status handler endpoint that can be used to get information
    about the current service
    """
    ENDPOINT = 'Status'

    async def get(self, *args, **kwargs):
        """Tornado RequestHandler GET request endpoint for reporting status
        :param list args: positional args
        :param  dict kwargs: keyword args
        """
        prune = self.get_argument('flush', 'false') == 'true'
        self.set_status(self._status_response_code())
        self.write({
            'application': self.settings['service'],
            'status': OK if self.application.ready_to_serve else MAINTENANCE,
            'version': __version__,
            'counters': await self.application.stats.counters(prune),
            'durations': await self.application.stats.durations(prune)
        })

    def _status_response_code(self):
        """Return the status code for the request based upon the application
        status.
        :rtype: int
        """
        if self.application.ready_to_serve:
            return 200
        return 503
