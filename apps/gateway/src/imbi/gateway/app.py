import datetime
import os

import fastapi
import typer
from imbi_common import access_log, graph, lifespan, server, settings
from imbi_common.plugins import registry as plugin_registry

import imbi_gateway
from imbi_gateway import app_status, lifespans, notifications

#: The built-in gateway-actions plugin does not follow the
#: ``imbi_plugin_*`` naming convention, so it is registered explicitly
#: through the ``IMBI_PLUGINS`` setting rather than the convention scan.
_BUILTIN_PLUGIN = 'imbi_gateway.plugin:GatewayActionsPlugin'


def _register_builtin_plugin() -> None:
    """Ensure ``IMBI_PLUGINS`` includes the built-in gateway plugin.

    Merges the built-in dotted path into whatever the operator has
    configured (env var or config file) before the registry reads the
    setting, so the gateway's own webhook actions are always discovered.
    """
    configured = settings.Plugins().imbi_plugins
    if _BUILTIN_PLUGIN not in configured:
        os.environ['IMBI_PLUGINS'] = ','.join([*configured, _BUILTIN_PLUGIN])


def create_app() -> fastapi.FastAPI:
    """Create and configure the FastAPI application instance."""
    _register_builtin_plugin()
    plugin_registry.load_plugins()
    app = fastapi.FastAPI(
        version=imbi_gateway.version,
        started_at=datetime.datetime.now(datetime.UTC),
        lifespan=lifespan.Lifespan(
            graph.graph_lifespan, lifespans.clickhouse_hook
        ),
    )
    app.include_router(notifications.router)
    app.include_router(app_status.router)
    app.add_middleware(
        access_log.AccessLogMiddleware,
        quiet_paths={'/status', '/gateway/status'},
    )
    return app


cli = typer.Typer(no_args_is_help=True)
cli.command('serve')(server.bind_entrypoint('imbi_gateway.app:create_app'))


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi Gateway CLI"""
    # Providing an empty callback forces typer to require a command
    # name - https://typer.tiangolo.com/tutorial/commands/one-or-multiple/
    # This is only necessary since we only have one command.
