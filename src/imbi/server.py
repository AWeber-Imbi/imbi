"""
Server entry point for Imbi.

Runs the FastAPI application using Uvicorn.
"""
import argparse
import sys
from pathlib import Path

import structlog
import uvicorn

from imbi import __version__
from imbi.api.app import create_app
from imbi.config import load_config

logger = structlog.get_logger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Imbi - DevOps Service Management Platform"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Imbi {__version__}",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        help="Path to configuration file (.toml or .yaml)",
    )
    parser.add_argument(
        "--host",
        type=str,
        help="Host to bind to (overrides config)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        help="Port to bind to (overrides config)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        help="Number of worker processes (overrides config)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point for the server."""
    args = parse_args()

    try:
        # Load configuration
        if args.config:
            config = load_config(args.config)
        else:
            logger.warning("No configuration file specified, using environment variables")
            config = load_config()

        # Apply command-line overrides
        if args.host:
            config.http.host = args.host
        if args.port:
            config.http.port = args.port
        if args.reload:
            config.http.reload = True
        if args.workers:
            config.http.workers = args.workers
        if args.debug:
            config.debug = True

        logger.info(
            "Starting Imbi server",
            version=__version__,
            host=config.http.host,
            port=config.http.port,
            workers=config.http.workers,
            debug=config.debug,
        )

        # Create the FastAPI app
        app = create_app(config)

        # Run with uvicorn
        uvicorn.run(
            app,
            host=config.http.host,
            port=config.http.port,
            workers=config.http.workers if not config.http.reload else 1,
            reload=config.http.reload,
            log_level="debug" if config.debug else "info",
            access_log=True,
            server_header=False,  # Don't expose server info
        )

    except Exception as e:
        logger.error("Failed to start server", error=str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
