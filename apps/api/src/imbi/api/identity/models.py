"""Per-user identity request/response models for the API surface."""

import datetime
import typing

import pydantic

from imbi.common.plugins.base import PollingDescriptor


class IdentityConnectionResponse(pydantic.BaseModel):
    """Public read model for a user's identity connection.

    Tokens — encrypted or plaintext — never appear here.
    """

    id: str
    integration_id: str
    integration_slug: str
    integration_name: str | None = None
    #: Slug of the plugin backing the integration (for plugin-level UI
    #: joins, e.g. matching a connection to a catalog plugin).
    plugin: str | None = None
    subject: str
    status: typing.Literal['active', 'revoked', 'expired']
    expires_at: datetime.datetime | None = None
    scopes: list[str] = []
    last_used_at: datetime.datetime | None = None
    metadata: dict[str, typing.Any] = {}


class IdentityConnectionStartRequest(pydantic.BaseModel):
    """Body for ``POST /me/identities/{integration_id}/start``."""

    return_to: str | None = None
    scopes: list[str] | None = None


class IdentityConnectionStartResponse(pydantic.BaseModel):
    """Reply to ``POST /me/identities/{integration_id}/start``."""

    authorization_url: str
    state: str
    polling: PollingDescriptor | None = None


class IdentityConnectionPollRequest(pydantic.BaseModel):
    """Body for ``POST /me/identities/{integration_id}/poll``."""

    state: str


class IdentityConnectionPollResponse(pydantic.BaseModel):
    """Reply to ``POST /me/identities/{integration_id}/poll``.

    ``status`` is ``'pending'`` while the user has not yet authorized
    out-of-band, ``'complete'`` once the IdP has issued tokens and the
    connection has been persisted.
    """

    status: typing.Literal['complete', 'pending']
    return_to: str | None = None


class IdentityCredentialsInternal(pydantic.BaseModel):
    """Server-side decrypted credentials.

    Built by the repository on read; *never* serialized to a response
    (the response model omits it).  Tokens are plaintext for in-process
    use only.
    """

    connection_id: str
    integration_id: str
    user_id: str
    subject: str
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime.datetime | None = None
    scopes: list[str] = []
    status: typing.Literal['active', 'revoked', 'expired']
    metadata: dict[str, typing.Any] = {}
