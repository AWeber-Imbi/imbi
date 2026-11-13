import datetime
import os

import fastapi
import pydantic_settings
import typer

import imbi.gateway
from imbi.common import (
    access_log,
    body_limit,
    graph,
    lifespan,
    metrics,
    posthog,
    sentry,
    server,
    settings,
)
from imbi.common.plugins import registry as plugin_registry
from imbi.gateway import app_status, lifespans, notifications

#: The built-in gateway-actions plugin does not follow the
#: ``imbi_plugin_*`` naming convention, so it is registered explicitly
#: through the ``IMBI_PLUGINS`` setting rather than the convention scan.
_BUILTIN_PLUGIN = 'imbi.gateway.plugin:GatewayActionsPlugin'


class ServerSettings(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix='IMBI_GATEWAY_'
    )
    # Largest request body, in bytes, before imbi-gateway answers 413.
    # The default fits GitHub's 25 MB cap on a webhook payload.
    max_request_body_bytes: int = 25 * 1024 * 1024


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
        version=imbi.gateway.version,
        started_at=datetime.datetime.now(datetime.UTC),
        lifespan=lifespan.Lifespan(
            sentry.sentry_lifespan,
            graph.graph_lifespan,
            lifespans.clickhouse_hook,
            lifespans.iggy_hook,
        ),
    )
    app.include_router(notifications.router)
    app.include_router(app_status.router)
    # For Prometheus to scrape by pod IP. The Caddyfile refuses
    # /gateway/metrics so that the public routes do not reach it.
    metrics.add_route(app)
    # Innermost, so that the access log wraps its 413.
    app.add_middleware(
        body_limit.BodyLimitMiddleware,
        limit=ServerSettings().max_request_body_bytes,
    )
    app.add_middleware(
        access_log.AccessLogMiddleware,
        quiet_paths={'/status', '/gateway/status', metrics.PATH},
    )
    posthog.install(app)
    return app


cli = typer.Typer(no_args_is_help=True)
cli.command('serve')(server.bind_entrypoint('imbi.gateway.app:create_app'))


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi Gateway CLI"""
    # Providing an empty callback forces typer to require a command
    # name - https://typer.tiangolo.com/tutorial/commands/one-or-multiple/
    # This is only necessary since we only have one command.
