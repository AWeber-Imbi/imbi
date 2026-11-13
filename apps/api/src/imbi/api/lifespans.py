"""Lifespan hooks for imbi-api services.

Each hook is an async context manager that initializes a service on
startup and cleans it up on shutdown. Hooks are composed using
:class:`imbi.common.lifespan.Lifespan` in the application factory.
"""

import asyncio
import contextlib
import logging
from collections import abc

from imbi.api import (
    graph_ids,
    iggy_metrics,
    openapi,
    secret_broker,
    settings,
    user_document_orgs,
)
from imbi.api.commit_sync import queue as commit_sync_queue
from imbi.api.deployment_sync import queue as deployment_sync_queue
from imbi.api.documents import read_sweeper as document_read_sweeper
from imbi.api.email.client import EmailClient
from imbi.api.email.templates import TemplateManager
from imbi.api.identity import sweeper as identity_sweeper
from imbi.api.llm import tokens
from imbi.api.maintenance import worker as maintenance_worker
from imbi.api.plugins import lifecycle as plugin_lifecycle
from imbi.api.pr_sync import queue as pr_sync_queue
from imbi.api.release_promote import queue as release_promote_queue
from imbi.api.scoring import queue as score_queue
from imbi.api.storage.client import StorageClient
from imbi.common import clickhouse, graph, iggy, valkey
from imbi.common.llm import AnthropicClient, AnthropicSettings
from imbi.common.llm import tokens as llm_tokens
from imbi.common.workflows import script_runner

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
    try:
        # First: the document backfill links to organizations by id.
        await graph_ids.backfill(db)
    except Exception:
        LOGGER.exception('Failed to give ids to organizations and users')
    try:
        await user_document_orgs.backfill(db)
    except Exception:
        LOGGER.exception('Failed to link user documents to organizations')


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
async def iggy_hook() -> abc.AsyncGenerator[None]:
    """Initialize and manage the Iggy connection."""
    result = await iggy.initialize()
    if result is False:
        raise RuntimeError('Iggy initialization failed')
    async with contextlib.aclosing(iggy):
        yield


@contextlib.asynccontextmanager
async def iggy_metrics_hook() -> abc.AsyncGenerator[None]:
    """Refresh the Iggy topic status gauges in the background."""
    stop = asyncio.Event()
    task = asyncio.create_task(iggy_metrics.run_refresher(stop=stop))
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
            LOGGER.warning(
                'Iggy metrics refresher exited with error', exc_info=True
            )


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

    With ``IMBI_AI_PROVIDER_API``, the client sends the workload identity
    token of that AI Provider (WIF plan 4.6). Else it uses
    ``ANTHROPIC_API_KEY``. Without either it is a disabled client —
    endpoints that depend on this still resolve but their completions
    return ``degraded=True`` with a fallback payload.
    """
    provider_id = settings.get_ai_providers().api
    if provider_id:
        anthropic_settings = AnthropicSettings()
        client = AnthropicClient(
            anthropic_settings,
            client=llm_tokens.bearer_client(
                tokens.ProviderToken(
                    provider_id, lambda: _graph, secret_broker.get_store
                ),
                timeout=anthropic_settings.timeout,
                max_retries=anthropic_settings.max_retries,
            ),
        )
    else:
        client = AnthropicClient()
    if client.available:
        LOGGER.info(
            'Anthropic client initialized (model=%s)', client.default_model
        )
    else:
        LOGGER.info('Anthropic client disabled — no AI provider or API key')
    try:
        yield client
    finally:
        await client.aclose()


#: Sandbox workers of the editor's script preview (ADR 0027). A preview
#: is a person at the editor, and each worker is a process of imbi-api.
SCRIPT_PREVIEW_PROCESSES = 2


@contextlib.asynccontextmanager
async def script_preview_hook() -> abc.AsyncGenerator[
    script_runner.Runner | None
]:
    """Start the sandbox of the workflow editor's script preview.

    A sandbox that does not start turns the preview off (it returns
    ``503``); imbi-api still starts.
    """
    async with contextlib.AsyncExitStack() as stack:
        try:
            runner = await stack.enter_async_context(
                script_runner.open_runner(
                    processes=SCRIPT_PREVIEW_PROCESSES,
                    max_memory=script_runner.DEFAULT_MAX_MEMORY_MB
                    * 1024
                    * 1024,
                    max_seconds=script_runner.DEFAULT_MAX_SECONDS,
                )
            )
        except Exception:  # noqa: BLE001 -- the preview is optional
            LOGGER.warning(
                'The script preview sandbox did not start', exc_info=True
            )
            runner = None
        yield runner


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
async def document_read_sweeper_hook() -> abc.AsyncGenerator[None]:
    """Finalize abandoned document read sessions.

    A reading session normally closes itself with a final `sendBeacon`
    flush, but that is best-effort -- a killed tab or a dropped network
    leaves the session open. This sweeper closes anything idle past
    :data:`_document_reads.SESSION_IDLE_TIMEOUT_SECONDS` so its engaged
    time still reaches the document's numbers.
    """
    try:
        client = valkey.get_client()
    except RuntimeError:
        LOGGER.warning('Valkey unavailable; read sweeper not started')
        yield None
        return
    stop = asyncio.Event()
    LOGGER.info('Document read-session sweeper starting')
    task = asyncio.create_task(
        document_read_sweeper.run_sweeper(client, stop=stop)
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
            LOGGER.warning('Read sweeper exited with error', exc_info=True)


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
async def deployment_sync_worker_hook() -> abc.AsyncGenerator[None]:
    """Run the on-demand deployment-resync consumer loop."""
    try:
        client = valkey.get_client()
    except RuntimeError:
        LOGGER.warning(
            'Valkey unavailable; deployment-sync worker not started'
        )
        yield None
        return
    if _graph is None:
        LOGGER.warning('Graph not ready; deployment-sync worker not started')
        yield None
        return
    stop = asyncio.Event()
    LOGGER.info('Deployment-sync worker starting')
    consumer_task = asyncio.create_task(
        deployment_sync_queue.consume_deployment_sync(
            client, _graph, stop=stop
        )
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
                'Deployment-sync worker task exited with error', exc_info=True
            )


@contextlib.asynccontextmanager
async def release_promote_worker_hook() -> abc.AsyncGenerator[None]:
    """Run the consumer that watches dispatched release builds."""
    try:
        client = valkey.get_client()
    except RuntimeError:
        LOGGER.warning(
            'Valkey unavailable; release-promote worker not started'
        )
        yield None
        return
    if _graph is None:
        LOGGER.warning('Graph not ready; release-promote worker not started')
        yield None
        return
    stop = asyncio.Event()
    LOGGER.info('Release-promote worker starting')
    consumer_task = asyncio.create_task(
        release_promote_queue.consume_release_promote(
            client, _graph, stop=stop
        )
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
                'Release-promote worker task exited with error', exc_info=True
            )


@contextlib.asynccontextmanager
async def maintenance_worker_hook() -> abc.AsyncGenerator[None]:
    """Run the global maintenance operation consumer loop."""
    try:
        client = valkey.get_client()
    except RuntimeError:
        LOGGER.warning('Valkey unavailable; maintenance worker not started')
        yield None
        return
    if _graph is None:
        LOGGER.warning('Graph not ready; maintenance worker not started')
        yield None
        return
    stop = asyncio.Event()
    LOGGER.info('Maintenance worker starting')
    consumer_task = asyncio.create_task(
        maintenance_worker.run_worker(client, _graph, stop=stop)
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
                'Maintenance worker task exited with error', exc_info=True
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
    stop = asyncio.Event()
    LOGGER.info('Score recompute worker starting')
    consumer_task = asyncio.create_task(
        score_queue.consume_recompute(client, _graph, stop=stop)
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
