import fastmcp

import imbi_mcp
from imbi_mcp import server
from tests import helpers


class ServerTests(helpers.TestCase):
    def test_mcp_instance(self) -> None:
        self.assertIsInstance(server.mcp, fastmcp.FastMCP)

    def test_mcp_name(self) -> None:
        self.assertEqual('Imbi', server.mcp.name)

    def test_mcp_version(self) -> None:
        self.assertEqual(imbi_mcp.version, server.mcp.version)
