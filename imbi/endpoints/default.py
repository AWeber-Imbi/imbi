"""
Request Handler used for rendering errors

"""
from imbi.endpoints import base


class RequestHandler(base.RequestHandler):

    ENDPOINT = 'Default'

    def get(self, *args, **kwargs):
        if self._respond_with_html:
            return self.render('index.html')
        self.set_status(404)
        self.send_response({'message': 'File Not Found'})
