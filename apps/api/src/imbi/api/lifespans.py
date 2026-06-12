"""Lifespan hooks for imbi-api services.

Each hook is an async context manager that initializes a service on
startup and cleans it up on shutdown. Hooks are composed using
:class:`imbi_common.lifespan.Lifespan` in the application factory.
"""

import asyncio
import contextlib
import logging
from collections import abc

from imbi_common import clickhouse, graph, valkey
from imbi_common.llm import AnthropicClient

from imbi_api import openapi
from imbi_api.commit_sync import queue as commit_sync_queue
from imbi_api.email.client import EmailClient
from imbi_api.email.templates import TemplateManager
from imbi_api.identity import sweeper as identity_sweeper
from imbi_api.plugins import lifecycle as plugin_lifecycle
from imbi_api.pr_sync import queue as pr_sync_queue
from imbi_api.scoring import queue as score_queue
from imbi_api.storage.client import StorageClient

LOGGER = logging.getLogger(__name__)

_graph: graph.Graph | None = None


async def _on_graph_startup(db: graph.Graph) -> None:
    """Refresh blueprint models and load plugins after the graph pool opens."""
    global _graph
    _graph = db
    try:
        await openapi.refresh_blueprint_models(db)
    except Exception:
        LOGGER.exception('Failed to refresh blueprint models')
    try:
        await plugin_lifecycle.startup_load_plugins(db)
    except Exception:
        LOGGER.exception('Failed to load plugins')


graph.set_on_startup(_on_graph_startup)


@contextlib.asynccontextmanager
async def clickhouse_hook() -> abc.AsyncGenerator[None]:
    """Initialize and manage the ClickHouse connection."""
    result = await clickhouse.initialize()
    if result is False:
        raise RuntimeError('ClickHouse initialization failed')
    async with contextlib.aclosing(clickhouse):
        yield


@contextlib.asynccontextmanager
async def email_hook() -> abc.AsyncGenerator[
    tuple[EmailClient, TemplateManager]
]:
    """Initialize and manage the email subsystem."""
    email_client = EmailClient()
    await email_client.initialize()
    template_manager = TemplateManager()
    async with contextlib.aclosing(email_client):
        yield email_client, template_manager


@contextlib.asynccontextmanager
async def storage_hook() -> abc.AsyncGenerator[StorageClient]:
    """Initialize and manage S3 storage."""
    storage_client = StorageClient()
    await storage_client.initialize()
    async with contextlib.aclosing(storage_client):
        yield storage_client


@contextlib.asynccontextmanager
async def anthropic_hook() -> abc.AsyncGenerator[AnthropicClient]:
    """Initialize the shared Anthropic client.

    Falls back to a disabled client when ``ANTHROPIC_API_KEY`` is
    absent — endpoints that depend on this still resolve but their
    completions return ``degraded=True`` with a fallback payload.
    """
    client = AnthropicClient()
    if client.available:
        LOGGER.info(
            'Anthropic client initialized (model=%s)', client.default_model
        )
    else:
        LOGGER.info('Anthropic client disabled — ANTHROPIC_API_KEY not set')
    try:
        yield client
    finally:
        await client.aclose()


@contextlib.asynccontextmanager
async def identity_refresh_hook() -> abc.AsyncGenerator[None]:
    """Run the identity-token refresh sweeper for the API process.

    Polls :func:`identity.repository.stale_connections` every 60s and
    refreshes connections whose ``expires_at`` is within 5 minutes.
    Failed refreshes flip ``status='expired'``.
    """
    try:
        client = valkey.get_client()
    except RuntimeError:
        LOGGER.warning('Valkey unavailable; identity sweeper not started')
        yield None
        return
    if _graph is None:
        LOGGER.warning('Graph not ready; identity sweeper not started')
        yield None
        return
    stop = asyncio.Event()
    LOGGER.info('Identity refresh sweeper starting')
    task = asyncio.create_task(
        identity_sweeper.run_sweeper(_graph, client, stop=stop)
    )
    try:
        yield None
    finally:
        stop.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            LOGGER.warning('Identity sweeper exited with error', exc_info=True)


@contextlib.asynccontextmanager
async def commit_sync_worker_hook() -> abc.AsyncGenerator[None]:
    """Run the on-demand commit/tag-sync consumer loop."""
    try:
        client = valkey.get_client()
    except RuntimeError:
        LOGGER.warning('Valkey unavailable; commit-sync worker not started')
        yield None
        return
    if _graph is None:
        LOGGER.warning('Graph not ready; commit-sync worker not started')
        yield None
        return
    stop = asyncio.Event()
    LOGGER.info('Commit-sync worker starting')
    consumer_task = asyncio.create_task(
        commit_sync_queue.consume_commit_sync(client, _graph, stop=stop)
    )
    try:
        yield None
    finally:
        stop.set()
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                'Commit-sync worker task exited with error', exc_info=True
            )


@contextlib.asynccontextmanager
async def pr_sync_worker_hook() -> abc.AsyncGenerator[None]:
    """Run the on-demand PR-sync consumer loop."""
    try:
        client = valkey.get_client()
    except RuntimeError:
        LOGGER.warning('Valkey unavailable; pr-sync worker not started')
        yield None
        return
    if _graph is None:
        LOGGER.warning('Graph not ready; pr-sync worker not started')
        yield None
        return
    stop = asyncio.Event()
    LOGGER.info('PR-sync worker starting')
    consumer_task = asyncio.create_task(
        pr_sync_queue.consume_pr_sync(client, _graph, stop=stop)
    )
    try:
        yield None
    finally:
        stop.set()
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                'PR-sync worker task exited with error', exc_info=True
            )


@contextlib.asynccontextmanager
async def score_worker_hook() -> abc.AsyncGenerator[None]:
    """Run the score-recompute consumer and the daily tick."""
    try:
        client = valkey.get_client()
    except RuntimeError:
        LOGGER.warning('Valkey unavailable; score worker not started')
        yield None
        return
    if _graph is None:
        LOGGER.warning('Graph not ready; score worker not started')
        yield None
        return
    ch = clickhouse.client.Clickhouse.get_instance()
    stop = asyncio.Event()
    LOGGER.info('Score recompute worker starting')
    consumer_task = asyncio.create_task(
        score_queue.consume_recompute(client, _graph, ch, stop=stop)
    )
    tick_task = asyncio.create_task(
        score_queue.run_daily_tick(client, _graph, stop=stop)
    )
    try:
        yield None
    finally:
        stop.set()
        for task in (consumer_task, tick_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                LOGGER.warning(
                    'Score worker task exited with error', exc_info=True
                )
