from imbi.endpoints import base


class IndexRequestHandler(base.RequestHandler):

    NAME = 'ui-index'

    def get(self, *args, **kwargs):
        if self.request.path == '/':
            return self.redirect('/ui/')
        self.render(
            'index.html',
            javascript_url=self.application.settings.get('javascript_url'))
