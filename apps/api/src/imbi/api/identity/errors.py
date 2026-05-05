"""Identity-flow error types."""


class IdentityRequiredError(Exception):
    """Raised when a dependent plugin call needs an identity that the
    actor has not yet connected.

    Mapped by the API to HTTP 401 with
    ``WWW-Authenticate: Imbi-Identity plugin_id=<id>`` and a JSON body
    ``{error: 'identity_required', plugin_id, start_url}``.
    """

    def __init__(self, plugin_id: str, start_url: str) -> None:
        super().__init__(f'Identity required for plugin {plugin_id!r}')
        self.plugin_id = plugin_id
        self.start_url = start_url


class IdentityRefreshFailed(Exception):
    """Raised when a refresh-token grant fails terminally.

    The repository flips the connection's ``status`` to ``'expired'``
    before this propagates.
    """


class IdentityRevokedError(Exception):
    """Raised when the actor's connection has been revoked."""
