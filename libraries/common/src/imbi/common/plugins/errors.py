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


class PluginInstallationMissing(Exception):
    """The Integration's own credential does not cover the target resource.

    Raised when a plugin holds valid service credentials but they grant
    it nothing on the resource in question -- canonically, a GitHub App
    that is configured correctly and simply is not installed on the
    repository.

    Distinct from :class:`PluginCredentialsMissing` (nothing configured
    at all) and :class:`PluginAuthenticationFailed` (a credential the
    remote rejected): here the credential is good and the *grant* is
    absent, so neither refreshing nor retrying changes the answer.  The
    host surfaces it as a terminal ``403`` rather than a ``5xx`` for
    exactly that reason -- consuming clients retry ``5xx``, and an
    uninstalled App is not transient.

    Background sync paths may still choose to treat it as a clean skip;
    a mutating path must not, because a silent skip there means the
    deploy or rollback did not happen and nothing said so.

    ``integration_slug`` identifies the Integration whose credential
    came up short.  The slug rather than the node id because that is
    what ``?source=`` accepts -- a caller that has to pick a different
    Integration can act on it directly.
    """

    def __init__(
        self,
        message: str,
        *,
        owner_repo: str | None = None,
        integration_slug: str | None = None,
    ) -> None:
        self.owner_repo: str | None = owner_repo
        self.integration_slug: str | None = integration_slug
        super().__init__(message)


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
