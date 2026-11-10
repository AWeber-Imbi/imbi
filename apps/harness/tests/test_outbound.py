"""The egress proxy environment (egress proxy plan 5.3)."""

import unittest

from imbi.harness import outbound

PROXY = 'http://chain:tok.en@proxy.example:3128'


class ProxyHelpersTestCase(unittest.TestCase):
    """The egress proxy environment (egress proxy plan 5.3)."""

    def test_proxy_url(self) -> None:
        self.assertEqual(
            outbound.proxy_url('http://proxy.example:3128', 'tok.en'), PROXY
        )
        self.assertEqual(
            outbound.proxy_url('http://proxy.example:3128', None),
            'http://proxy.example:3128',
        )

    def test_no_proxy_has_the_configured_services(self) -> None:
        env = outbound.proxy_env(
            PROXY,
            'http://imbi-api.imbi.svc:8000/api',
            'http://imbi-mcp.imbi.svc:8001/mcp',
            None,
        )
        self.assertEqual(env['HTTPS_PROXY'], PROXY)
        self.assertEqual(env['https_proxy'], PROXY)
        self.assertEqual(env['NO_PROXY'], env['no_proxy'])
        excluded = env['NO_PROXY'].split(',')
        # The API, the MCP server, the local model proxy (127.0.0.1),
        # and the IPv6 loopback do not go through the proxy.
        for host in (
            'imbi-api.imbi.svc',
            'imbi-mcp.imbi.svc',
            '127.0.0.1',
            '::1',
            'localhost',
        ):
            with self.subTest(host=host):
                self.assertIn(host, excluded)
        self.assertEqual(outbound.proxy_token(env), 'tok.en')
        self.assertIsNone(outbound.proxy_token({}))
