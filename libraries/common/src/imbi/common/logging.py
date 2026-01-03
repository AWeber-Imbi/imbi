"""Logging configuration for Imbi services."""

import tomllib
from importlib import resources
from logging import config


def get_log_config() -> dict:
    """Load logging configuration from bundled log-config.toml.

    Returns:
        dict: Logging configuration dictionary suitable for
            logging.dictConfig()

    """
    log_config_file = resources.files('imbi_common') / 'log-config.toml'
    return tomllib.loads(log_config_file.read_text())


def configure_logging(
    log_config: dict | None = None, dev: bool = False
) -> None:
    """Configure logging using dictConfig.

    Args:
        log_config: Optional logging config dict. If None, loads from
            log-config.toml
        dev: If True, sets imbi logger to DEBUG level

    """
    if log_config is None:
        log_config = get_log_config()

    if dev:
        loggers = log_config.setdefault('loggers', {})
        loggers.setdefault('imbi', {})
        loggers['imbi']['level'] = 'DEBUG'

    config.dictConfig(log_config)
