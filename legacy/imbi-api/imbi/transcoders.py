import decimal
import urllib.parse

from sprockets.mixins.mediatype import handlers, transcoders


def parse_form_body(data) -> dict:
    def translate_value(v):
        if not v:
            return None

        m = {'null': None, 'true': True, 'false': False}
        try:
            value = m[v]
        except KeyError:
            try:
                value = float(v)
            except ValueError:
                value = v
        return value

    if hasattr(data, 'decode'):
        data = data.decode('utf-8')
    form_body = {}
    parsed = urllib.parse.parse_qsl(data, keep_blank_values=True)
    for name, value in parsed:
        value = translate_value(value)
        if name in form_body:
            if not isinstance(form_body[name], list):
                form_body[name] = [form_body[name]]
            form_body[name].append(value)
        else:
            form_body[name] = value
    return form_body


class DecimalMixin:

    def dump_object(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super().dump_object(obj)


class JSONTranscoder(DecimalMixin, transcoders.JSONTranscoder):
    """Handle Decimal Values"""


class MsgPackTranscoder(DecimalMixin, transcoders.MsgPackTranscoder):
    """Handle Decimal Values"""


class HTMLTranscoder(transcoders.JSONTranscoder):

    def __init__(self, content_type='text/html', default_encoding='utf-8'):
        super().__init__(content_type, default_encoding)
        self.dump_options = {
            'default': self.dump_object,
            'separators': (',', ':')
        }

    def dumps(self, value):
        """Just pass through the value if it's a string, otherwise dump it as
        JSON.

        :rtype: str

        """
        if not isinstance(value, (bytes, str)):
            value = '<html><body><pre>{}</pre></body></html>'.format(
                super().dumps(value))
        return value

    @staticmethod
    def loads(value):
        """Just pass through the value."""
        return value


class FormTranscoder(handlers.TextContentHandler):
    def __init__(self):
        super().__init__('application/x-www-form-urlencoded', dumps=self.dumps,
                         loads=self.loads, default_encoding='utf-8')

    def dumps(self, inst_data) -> str:
        return urllib.parse.urlencode(inst_data)

    def loads(self, data):
        return parse_form_body(data)
