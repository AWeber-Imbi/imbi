import re
from unittest import mock

import typer.testing

from apps.mcp.tests import helpers
from imbi.common import access_log
from imbi.common import logging as imbi_logging
from imbi.mcp import app

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


class ServeLoggingTests(helpers.TestCase):
    """The HTTP server logs through imbi-common, not uvicorn."""

    @mock.patch('imbi.mcp.app.server.create_server')
    def _serve(self, args: list[str], mock_create: mock.Mock) -> mock.Mock:
        runner = typer.testing.CliRunner()
        result = runner.invoke(app.cli, ['serve', *args])
        self.assertEqual(0, result.exit_code, result.output)
        return mock_create.return_value.run

    def test_installs_the_imbi_access_log(self) -> None:
        run = self._serve([])  # pyright: ignore[reportCallIssue]
        kwargs = run.call_args.kwargs
        self.assertEqual(
            [access_log.AccessLogMiddleware],
            [middleware.cls for middleware in kwargs['middleware']],
        )
        self.assertEqual(
            {'/status'}, kwargs['middleware'][0].kwargs['quiet_paths']
        )

    def test_disables_the_uvicorn_access_log(self) -> None:
        """Both logs at once would double every line."""
        run = self._serve([])  # pyright: ignore[reportCallIssue]
        self.assertIs(
            False, run.call_args.kwargs['uvicorn_config']['access_log']
        )

    def test_uses_the_shared_log_config(self) -> None:
        run = self._serve([])  # pyright: ignore[reportCallIssue]
        self.assertEqual(
            imbi_logging.get_log_config(),
            run.call_args.kwargs['uvicorn_config']['log_config'],
        )

    def test_stdio_takes_no_http_arguments(self) -> None:
        """stdio has no uvicorn, and passing HTTP kwargs would raise."""
        run = self._serve(  # pyright: ignore[reportCallIssue]
            ['--transport', 'stdio']
        )
        self.assertEqual({'transport': 'stdio'}, run.call_args.kwargs)
