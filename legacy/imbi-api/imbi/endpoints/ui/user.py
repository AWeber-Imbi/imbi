from imbi.endpoints import base


class UserRequestHandler(base.AuthenticatedRequestHandler):

    NAME = 'ui-user'

    def get(self, *args, **kwargs):
        user = self.current_user.as_dict()
        del user['password']
        self.send_response(user)
