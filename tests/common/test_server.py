import pathlib
import tempfile
import tomllib
import typing
import unittest.mock
from importlib import resources

import tomli_w
import typer.testing

from imbi.common import helpers, server, settings


class ServerCliTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.uvicorn_run = self.enterContext(
            unittest.mock.patch('imbi.common.server.uvicorn.run')
        )
        self.enterContext(
            unittest.mock.patch.object(settings.SSL, 'configure')
        )
        self.log_config_data = tomllib.loads(
            resources.files('imbi.common')
            .joinpath('log-config.toml')
            .read_text()
        )
        self.standard_kwargs: dict[
            str, bool | dict[str, typing.Any] | int | str | None
        ] = {
            'access_log': False,
            'env_file': None,
            'factory': True,
            'host': '127.0.0.1',
            'log_config': self.log_config_data,
            'port': 8000,
        }
        self.cli = typer.Typer()
        self.cli.command()(server.serve)

    def test_without_args(self) -> None:
        result = typer.testing.CliRunner().invoke(self.cli)
        self.assertNotEqual(0, result.exit_code)
        self.assertIn('missing argument', result.output.lower())
        self.assertIn('entrypoint', result.output.lower())
        self.uvicorn_run.assert_not_called()

    def test_with_only_entrypoint_arg(self) -> None:
        result = typer.testing.CliRunner().invoke(
            self.cli, ['package.module:func']
        )
        self.assertEqual(0, result.exit_code, result.output)
        self.uvicorn_run.assert_called_once_with(
            'package.module:func', **self.standard_kwargs
        )

    def test_with_invalid_entrypoint(self) -> None:
        result = typer.testing.CliRunner().invoke(self.cli, ['invalid'])
        self.assertNotEqual(0, result.exit_code)
        self.assertIn(
            "invalid value for 'entrypoint'",
            result.output.lower(),
            result.output,
        )
        self.uvicorn_run.assert_not_called()

    def test_when_uvicorn_is_not_installed(self) -> None:
        saved_value = server.uvicorn_available
        try:
            server.uvicorn_available = False
            result = typer.testing.CliRunner().invoke(
                self.cli, ['package.module:function']
            )
        finally:
            server.uvicorn_available = saved_value

        self.assertNotEqual(0, result.exit_code)
        self.assertIn('uvicorn is not installed', str(result.exception).lower())

    def test_in_dev_mode(self) -> None:
        result = typer.testing.CliRunner().invoke(
            self.cli, ['--dev', 'package.module:func']
        )
        self.assertEqual(0, result.exit_code, result.output)

        # update the log config to match expectations
        loggers = helpers.unwrap_as(
            dict[str, dict[str, str]], self.log_config_data.get('loggers')
        )
        loggers.setdefault('imbi', {})['level'] = 'DEBUG'
        loggers.setdefault('package', {})['level'] = 'DEBUG'

        self.uvicorn_run.assert_called_once_with(
            'package.module:func',
            **{
                **self.standard_kwargs,
                'reload': True,
            },
        )

    def test_with_envfile(self) -> None:
        result = typer.testing.CliRunner().invoke(
            self.cli, ['--env-file', 'test.env', 'package.module:func']
        )
        self.assertEqual(0, result.exit_code, result.output)
        self.uvicorn_run.assert_called_once_with(
            'package.module:func',
            **{
                **self.standard_kwargs,
                'env_file': pathlib.Path('test.env'),
            },
        )

    def test_with_host_and_port(self) -> None:
        result = typer.testing.CliRunner().invoke(
            self.cli,
            [
                '--host',
                '127.0.0.1',
                '--port',
                '8080',
                'package.module:func',
            ],
        )
        self.assertEqual(0, result.exit_code, result.output)
        self.uvicorn_run.assert_called_once_with(
            'package.module:func',
            **{**self.standard_kwargs, 'host': '127.0.0.1', 'port': 8080},
        )

    def test_with_explicit_log_config(self) -> None:
        # modify the log config to verify the change
        self.log_config_data['root']['level'] = 'DEBUG'

        with tempfile.NamedTemporaryFile(mode='wb') as f:
            tomli_w.dump(self.log_config_data, f)
            f.flush()
            result = typer.testing.CliRunner().invoke(
                self.cli,
                ['--log-config', f.name, 'package.module:func'],
            )
        self.assertEqual(0, result.exit_code, result.output)
        self.uvicorn_run.assert_called_once_with(
            'package.module:func',
            **{**self.standard_kwargs, 'log_config': self.log_config_data},
        )

    def test_verbose_flag(self) -> None:
        result = typer.testing.CliRunner().invoke(
            self.cli, ['--verbose', 'package.module:func']
        )
        self.assertEqual(0, result.exit_code, result.output)

        # update the log config to match expectations
        loggers = helpers.unwrap_as(
            dict[str, dict[str, str]], self.log_config_data.get('loggers')
        )
        loggers.setdefault('package', {})['level'] = 'DEBUG'
        self.uvicorn_run.assert_called_once_with(
            'package.module:func',
            **{**self.standard_kwargs, 'log_config': self.log_config_data},
        )

    def test_rebinding_entrypoint(self) -> None:
        cli = typer.Typer()
        cli.command('serve')(server.bind_entrypoint('package.module:func'))
        result = typer.testing.CliRunner().invoke(cli)
        self.assertEqual(0, result.exit_code, result.output)
        self.uvicorn_run.assert_called_once_with(
            'package.module:func', **self.standard_kwargs
        )

    def test_rebinding_entrypoint_with_default_port(self) -> None:
        cli = typer.Typer()
        cli.command('serve')(
            server.bind_entrypoint('package.module:func', default_port=8002)
        )
        result = typer.testing.CliRunner().invoke(cli)
        self.assertEqual(0, result.exit_code, result.output)
        self.uvicorn_run.assert_called_once_with(
            'package.module:func',
            **{**self.standard_kwargs, 'port': 8002},
        )

    def test_rebinding_entrypoint_default_port_overridden_by_flag(
        self,
    ) -> None:
        cli = typer.Typer()
        cli.command('serve')(
            server.bind_entrypoint('package.module:func', default_port=8002)
        )
        result = typer.testing.CliRunner().invoke(cli, ['--port', '9000'])
        self.assertEqual(0, result.exit_code, result.output)
        self.uvicorn_run.assert_called_once_with(
            'package.module:func',
            **{**self.standard_kwargs, 'port': 9000},
        )
