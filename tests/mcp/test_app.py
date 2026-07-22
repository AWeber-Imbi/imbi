import re
from unittest import mock

import typer.testing

from imbi.mcp import app
from tests.mcp import helpers

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)


class CLITests(helpers.TestCase):
    def test_cli_is_typer(self) -> None:
        self.assertIsInstance(app.cli, typer.Typer)

    def test_cli_no_args_shows_help(self) -> None:
        runner = typer.testing.CliRunner()
        result = runner.invoke(app.cli, [])
        self.assertIn('Usage', _strip_ansi(result.output))

    def test_cli_help(self) -> None:
        runner = typer.testing.CliRunner()
        result = runner.invoke(app.cli, ['--help'])
        self.assertEqual(0, result.exit_code)
        self.assertIn('serve', _strip_ansi(result.output))

    def test_serve_help(self) -> None:
        runner = typer.testing.CliRunner()
        result = runner.invoke(app.cli, ['serve', '--help'])
        self.assertEqual(0, result.exit_code)
        output = _strip_ansi(result.output)
        self.assertIn('--api-url', output)
        self.assertIn('--transport', output)
        self.assertIn('--host', output)
        self.assertIn('--port', output)

    @mock.patch('imbi.mcp.app.server.create_server')
    def test_serve_api_connection_error(self, mock_create: mock.Mock) -> None:
        mock_create.side_effect = ConnectionError('Connection refused')
        runner = typer.testing.CliRunner()
        result = runner.invoke(
            app.cli, ['serve', '--api-url', 'http://bad:9999']
        )
        self.assertNotEqual(0, result.exit_code)
        output = _strip_ansi(result.output)
        self.assertIn('Failed to connect', output)
