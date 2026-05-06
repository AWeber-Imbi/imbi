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


class PluginSchemaCollisionError(Exception):
    """Raised when a plugin declares a vlabel that collides with another
    plugin or with core's static schemata.
    """


class IdentityAuthorizationPending(Exception):
    """Raised by an identity plugin's ``exchange_code`` while the user
    has not yet completed an out-of-band authorization step (e.g. an
    OAuth 2.0 device-code flow).  The host's poll loop is expected to
    catch this and retry at the plugin's polling interval.
    """


class IdentityAuthorizationExpired(Exception):
    """Raised by an identity plugin's ``exchange_code`` when an
    out-of-band authorization (e.g. an IdP-issued device code) has
    expired before the user completed it.  The host should surface
    this to the UI so the user can restart the flow.
    """
