import typer.testing

from imbi_mcp import app
from tests import helpers


class CLITests(helpers.TestCase):
    def test_cli_is_typer(self) -> None:
        self.assertIsInstance(app.cli, typer.Typer)

    def test_cli_no_args_shows_help(self) -> None:
        runner = typer.testing.CliRunner()
        result = runner.invoke(app.cli, [])
        self.assertIn('Usage', result.output)

    def test_cli_help(self) -> None:
        runner = typer.testing.CliRunner()
        result = runner.invoke(app.cli, ['--help'])
        self.assertEqual(0, result.exit_code)
        self.assertIn('serve', result.output)

    def test_serve_help(self) -> None:
        runner = typer.testing.CliRunner()
        result = runner.invoke(app.cli, ['serve', '--help'])
        self.assertEqual(0, result.exit_code)
        self.assertIn('--transport', result.output)
        self.assertIn('--host', result.output)
        self.assertIn('--port', result.output)
