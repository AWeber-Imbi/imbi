"""Plugin error types."""


class PluginNotFoundError(Exception):
    """Raised when a plugin slug is not registered."""


class PluginUnavailableError(Exception):
    """Raised when a plugin slug exists in the graph but not the registry."""


class CursorExpiredError(Exception):
    """Raised by log plugins when a pagination cursor has expired."""


class PluginTimeoutError(Exception):
    """Raised when a plugin call exceeds the configured timeout."""


class PluginCredentialsMissing(Exception):
    """Raised when required credentials are absent for a plugin."""
