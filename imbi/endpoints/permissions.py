from . import base


class RequestHandler(base.AuthenticatedRequestHandler):

    NAME = 'permissions'

    @base.require_permission('admin')
    async def get(self):
        self.send_response(list(self.settings['permissions']))
