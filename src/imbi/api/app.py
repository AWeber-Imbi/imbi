"""
FastAPI application factory for Imbi.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from imbi import __version__
from imbi.config import Config
from imbi.database import close_database, initialize_database

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if True else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Handles startup and shutdown events for the FastAPI application.
    """
    config: Config = app.state.config
    logger.info("Starting Imbi application", version=__version__)

    # Initialize Valkey (Redis-compatible) pools
    logger.info("Initializing Valkey connections")
    try:
        # Note: redis-py library is used as Valkey is protocol-compatible
        app.state.session_valkey = await aioredis.from_url(
            config.session.valkey.url,
            encoding=config.session.valkey.encoding,
            decode_responses=config.session.valkey.decode_responses,
        )
        await app.state.session_valkey.ping()
        logger.info("Session Valkey connected")

        app.state.stats_valkey = await aioredis.from_url(
            config.stats.valkey.url,
            encoding=config.stats.valkey.encoding,
            decode_responses=config.stats.valkey.decode_responses,
        )
        await app.state.stats_valkey.ping()
        logger.info("Stats Valkey connected")
    except Exception as e:
        logger.error("Failed to connect to Valkey", error=str(e))
        raise

    # Initialize PostgreSQL
    logger.info("Initializing PostgreSQL connection pool")
    try:
        if config.postgres.url:
            # Parse URL to get connection parameters
            # TODO: Implement URL parsing
            # For now, require individual parameters
            raise ValueError(
                "URL-based postgres configuration not yet implemented. "
                "Use host, port, database, user, password instead."
            )
        else:
            await initialize_database(
                host=config.postgres.host,
                port=config.postgres.port,
                database=config.postgres.database,
                user=config.postgres.user,
                password=config.postgres.password,
                min_pool_size=config.postgres.min_pool_size,
                max_pool_size=config.postgres.max_pool_size,
                timeout=config.postgres.timeout,
                log_queries=config.postgres.log_queries,
            )
        logger.info("PostgreSQL connected")
    except Exception as e:
        logger.error("Failed to connect to PostgreSQL", error=str(e))
        raise

    # Initialize OpenSearch (if enabled)
    if config.opensearch.enabled:
        logger.info("Initializing OpenSearch client")
        # TODO: Implement OpenSearch initialization
        logger.warning("OpenSearch support not yet implemented")

    # Initialize Claude client (if enabled)
    if config.claude.enabled:
        if config.claude.api_key:
            logger.info("Initializing Claude AI client", model=config.claude.model)
            # TODO: Implement Claude initialization
            logger.warning("Claude integration not yet implemented")
        else:
            logger.warning("Claude enabled but API key not configured")

    # Initialize Sentry (if enabled)
    if config.sentry.enabled and config.sentry.dsn:
        logger.info("Initializing Sentry")
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration

            sentry_sdk.init(
                dsn=config.sentry.dsn,
                environment=config.sentry.environment,
                traces_sample_rate=config.sentry.traces_sample_rate,
                integrations=[FastApiIntegration()],
            )
            logger.info("Sentry initialized")
        except ImportError:
            logger.warning("Sentry SDK not installed. Install with: pip install sentry-sdk")

    logger.info("Application startup complete")
    app.state.ready = True

    yield  # Application is running

    # Shutdown
    logger.info("Shutting down application")

    # Close Valkey connections
    if hasattr(app.state, "session_valkey"):
        await app.state.session_valkey.close()
        logger.info("Session Valkey closed")

    if hasattr(app.state, "stats_valkey"):
        await app.state.stats_valkey.close()
        logger.info("Stats Valkey closed")

    # Close PostgreSQL connection pool
    await close_database()
    logger.info("PostgreSQL connection pool closed")

    logger.info("Application shutdown complete")


def create_app(config: Config) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        config: Application configuration

    Returns:
        Configured FastAPI application instance
    """
    app = FastAPI(
        title="Imbi API",
        description="DevOps Service Management Platform",
        version=__version__,
        docs_url="/api/docs" if config.debug else None,
        redoc_url="/api/redoc" if config.debug else None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # Store config in app state
    app.state.config = config
    app.state.ready = False

    # Add middleware
    _configure_middleware(app, config)

    # Add error handlers
    _configure_error_handlers(app)

    # Add routers
    _configure_routers(app)

    logger.info("FastAPI application created", version=__version__)

    return app


def _configure_middleware(app: FastAPI, config: Config) -> None:
    """Configure application middleware."""

    # CORS middleware
    if config.cors.enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors.allowed_origins,
            allow_credentials=config.cors.allow_credentials,
            allow_methods=config.cors.allowed_methods,
            allow_headers=config.cors.allowed_headers,
        )
        logger.info("CORS middleware configured")

    # Session middleware
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.session.secret_key,
        session_cookie=config.session.cookie_name,
        max_age=config.session.duration * 86400,  # Convert days to seconds
        https_only=not config.debug,
        same_site="lax",
    )
    logger.info("Session middleware configured")

    # Gzip compression
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    logger.info("Gzip middleware configured")

    # TODO: Add stats collection middleware
    # TODO: Add request ID middleware


def _configure_error_handlers(app: FastAPI) -> None:
    """Configure custom error handlers."""

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Handle Pydantic validation errors."""
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "type": "https://imbi.example.com/errors/validation-error",
                "title": "Validation Error",
                "status": 422,
                "detail": "Request validation failed",
                "errors": exc.errors(),
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle unhandled exceptions."""
        logger.error("Unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "type": "https://imbi.example.com/errors/internal-error",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "An unexpected error occurred",
            },
        )

    logger.info("Error handlers configured")


def _configure_routers(app: FastAPI) -> None:
    """Configure API routers."""

    # Health check endpoint (simple, no authentication required)
    @app.get("/api/status", tags=["Health"])
    async def health_check() -> dict:
        """Health check endpoint."""
        return {
            "status": "ok",
            "version": __version__,
            "ready": app.state.ready,
        }

    # Import and register routers
    from imbi.routers import (
        auth,
        environments,
        groups,
        namespaces,
        project_types,
        projects,
    )

    app.include_router(auth.router, prefix="/api")
    app.include_router(namespaces.router, prefix="/api")
    app.include_router(project_types.router, prefix="/api")
    app.include_router(environments.router, prefix="/api")
    app.include_router(groups.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")

    # TODO: Add other routers
    # from imbi.routers import operations, integrations, reports, chat
    # ...

    logger.info("API routers configured")
