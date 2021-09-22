from imbi.endpoints import base


class LoginRequestHandler(base.RequestHandler):

    NAME = 'ui-login'

    async def post(self, *args, **kwargs):
        body = self.get_request_body()
        if not await self.session.authenticate(
                body.get('username'), body.get('password')):
            self.logger.debug('Session failed to authenticate')
            self.set_status(401)
            self.send_response({'message': 'Authentication Failure'})
            return
        await self.session.save()
        self.set_status(200)
        self.send_response(self.session.user.as_dict())


class LogoutRequestHandler(base.RequestHandler):

    NAME = 'ui-logout'

    async def get(self, *args, **kwargs):
        await self.session.clear()
        self.send_response({'loggedOut': True})
