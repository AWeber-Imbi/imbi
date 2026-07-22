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


class PluginAuthenticationFailed(Exception):
    """Raised when a plugin's API call is rejected by the upstream IdP
    or service for an authentication-related reason (HTTP 401, an AWS
    ``ExpiredToken`` JSON-1.1 error, etc.).

    Distinct from :class:`PluginCredentialsMissing` (which signals a
    config-time absence) and :class:`PluginUnavailableError` (which
    signals an upstream outage): this error tells the host's retry
    layer that refreshing the actor's :class:`IdentityConnection` and
    retrying the call once is a reasonable next step.
    """


class PluginRateLimited(Exception):
    """Raised when a plugin exhausts an upstream API's rate limit.

    Carries ``retry_at`` -- a Unix epoch (``time.time()``-comparable) at
    which the upstream says work may resume -- so the host can pause and
    keep the job queued rather than fail it.  Distinct from
    :class:`PluginAuthenticationFailed` (refresh-and-retry) and
    :class:`PluginUnavailableError` (upstream outage): this error tells
    the host's queue layer to back off until ``retry_at`` and try again,
    not to dead-letter the work.
    """

    def __init__(self, retry_at: float, message: str = '') -> None:
        self.retry_at: float = retry_at
        super().__init__(message or f'Rate limited until epoch {retry_at:.0f}')


class PluginRemediationNotSupported(Exception):
    """Raised when a plugin is asked to remediate but does not implement
    :meth:`~imbi.common.plugins.base.AnalysisPlugin.remediate`.

    The host should treat this as a client error (the finding offered no
    fix, or the plugin advertised one without implementing it).
    """

    def __init__(self, plugin_slug: str, remediation_id: str) -> None:
        self.plugin_slug: str = plugin_slug
        self.remediation_id: str = remediation_id
        super().__init__(
            f'Plugin {plugin_slug!r} does not support remediation '
            f'(id={remediation_id!r})'
        )


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
