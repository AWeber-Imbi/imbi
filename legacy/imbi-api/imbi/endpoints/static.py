from tornado import web


class StaticFileHandler(web.StaticFileHandler):

    def set_default_headers(self) -> None:
        """Override the default headers, setting the Server response header"""
        super().set_default_headers()
        self.set_header('Server', self.settings['server_header'])
        self.set_header('Access-Control-Allow-Origin', '*')
