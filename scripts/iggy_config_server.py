"""Stand-in for imbi-api's Iggy connector configuration endpoints.

`compose.ci.yaml` points the connectors runtime at this instead of at
imbi-api, because the test suites run the API in-process and CI has no
imbi-api container for the runtime to fetch from. Serving the same JSON
here is what lets CI exercise the real ClickHouse sink.

The shape is the one
`imbi.api.endpoints.iggy_connectors` serves, and
`apps/api/tests/endpoints/test_iggy_connectors.py` asserts the two agree
field for field, so this file cannot drift away from the endpoint
unnoticed. Nothing in Imbi imports it; it runs on a bare `python:*-slim`
image with no dependencies.

Environment:

    IGGY_TOPICS          `stream=topic,topic;stream=topic`, the sinks to
                         serve. Mirrors `imbi.common.iggy.TOPICS`.
    CLICKHOUSE_URL       ClickHouse HTTP base URL, as reachable from the
                         connectors container.
    CLICKHOUSE_DATABASE  Database the sink inserts into.
    CLICKHOUSE_USERNAME, CLICKHOUSE_PASSWORD
    PLUGIN_PATH          Sink plugin in the connectors image.
    API_KEY              Bearer token every route requires.
    PORT                 Listen port, 8080 by default.
"""

import json
import os
import sys
from http import server

PLUGIN_PATH = os.environ.get(
    'PLUGIN_PATH', '/opt/iggy/connectors/libiggy_connector_clickhouse_sink'
)
API_KEY = os.environ.get('API_KEY', 'test-api-key')

#: Segments in `/sinks/{key}/configs`, the shortest sink path.
SINK_PATH_SEGMENTS = 3
VERSION = 0
CREATED_AT = '1970-01-01T00:00:00Z'


def parse_topics(value: str) -> dict[str, list[str]]:
    """Parse `stream=topic,topic;stream=topic` into a stream map."""
    topics: dict[str, list[str]] = {}
    for entry in value.split(';'):
        if not entry.strip():
            continue
        stream, _, names = entry.partition('=')
        topics[stream.strip()] = [
            name.strip() for name in names.split(',') if name.strip()
        ]
    return topics


def sink_config(stream: str, topics: list[str]) -> dict[str, object]:
    """Build one sink, the way the imbi-api endpoint builds it."""
    return {
        'key': stream,
        'enabled': True,
        'version': VERSION,
        'name': f'ClickHouse sink: {stream}',
        'path': PLUGIN_PATH,
        'transforms': None,
        'streams': [
            {
                'stream': stream,
                'topics': topics,
                'schema': 'json',
                'avro_schema_json': None,
                'avro_schema_path': None,
                'batch_length': 1000,
                'poll_interval': '250ms',
                'consumer_group': stream,
            }
        ],
        'plugin_config_format': 'json',
        'plugin_config': {
            'url': os.environ.get('CLICKHOUSE_URL', 'http://clickhouse:8123'),
            'database': os.environ.get('CLICKHOUSE_DATABASE', 'imbi'),
            'username': os.environ.get('CLICKHOUSE_USERNAME', 'default'),
            'password': os.environ.get('CLICKHOUSE_PASSWORD', 'password'),
            'table': stream,
            'insert_format': 'json_each_row',
            'timeout_seconds': 30,
            'max_retries': 3,
            'retry_delay': 1,
            'verbose_logging': False,
        },
        'verbose': False,
        'benchmark': False,
    }


def active_configs() -> dict[str, object]:
    """The whole active configuration, as `GET /configs/active`."""
    topics = parse_topics(os.environ.get('IGGY_TOPICS', 'events=gateway'))
    return {
        'sinks': {
            stream: sink_config(stream, names)
            for stream, names in topics.items()
        },
        'sources': {},
    }


class Handler(server.BaseHTTPRequestHandler):
    def _send(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if self.headers.get('Authorization') == f'Bearer {API_KEY}':
            return True
        self._send({'detail': 'Unauthorized'}, 401)
        return False

    def do_GET(self) -> None:
        if self.path == '/healthz':
            # Unauthenticated so the compose healthcheck needs no token.
            # Not part of the contract imbi-api implements.
            self._send({'status': 'ok'})
            return
        if not self._authorized():
            return
        configs = active_configs()
        sinks: dict[str, object] = configs['sinks']  # type: ignore[assignment]
        if self.path == '/configs/active':
            self._send(configs)
            return
        if self.path == '/configs/active/versions':
            self._send(
                {
                    'sinks': {
                        stream: {
                            'version': VERSION,
                            'created_at': CREATED_AT,
                        }
                        for stream in sinks
                    },
                    'sources': {},
                }
            )
            return
        parts = self.path.strip('/').split('/')
        if (
            len(parts) >= SINK_PATH_SEGMENTS
            and parts[0] == 'sinks'
            and parts[2] == 'configs'
        ):
            sink = sinks.get(parts[1])
            if sink is None:
                self._send({'detail': 'Unknown sink'}, 404)
            elif len(parts) == SINK_PATH_SEGMENTS:
                self._send([sink])
            elif parts[3] in ('active', str(VERSION)):
                self._send(sink)
            else:
                self._send({'detail': 'Unknown version'}, 404)
            return
        self._send({'detail': 'Not Found'}, 404)

    def _method_not_allowed(self) -> None:
        """Versions are code here, exactly as they are in imbi-api."""
        # The body is never read: a caller could declare a large
        # Content-Length and withhold it, stalling this single-threaded
        # server. Closing the connection discards it instead.
        self.close_connection = True
        if self._authorized():
            self._send({'detail': 'Method Not Allowed'}, 405)

    do_POST = _method_not_allowed  # noqa: N815 - matches the handler names
    do_PUT = _method_not_allowed  # noqa: N815
    do_DELETE = _method_not_allowed  # noqa: N815

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stdout.write(f'iggy-config-server: {fmt % args}\n')
        sys.stdout.flush()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8080'))
    server.HTTPServer(('0.0.0.0', port), Handler).serve_forever()  # noqa: S104
