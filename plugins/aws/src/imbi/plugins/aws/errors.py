"""Errors raised by the AWS identity plugin and helpers."""

from imbi_common.plugins.errors import (
    IdentityAuthorizationExpired,
    IdentityAuthorizationPending,
)


class AccountNotResolvedError(Exception):
    """Raised when ``account_resolution.resolve_account`` cannot find a
    matching ``AwsAccount`` for the actor's context.

    Mapped to HTTP 412 by the host with a body listing the selector
    that was tried so operators can see exactly which ``MAPS_TO`` edge
    is missing.
    """

    def __init__(
        self,
        *,
        selector: list[str],
        anchors_checked: list[str] | None = None,
    ) -> None:
        super().__init__(
            f'No AwsAccount mapped from selector={selector}; '
            f'anchors_checked={anchors_checked or []}'
        )
        self.selector = selector
        self.anchors_checked = anchors_checked or []


class IamIcDeviceFlowExpired(IdentityAuthorizationExpired):
    """Raised when the IAM IC device-code expires before the user
    completes the login (CreateToken returns ExpiredTokenException).
    """


class IamIcAuthorizationPending(IdentityAuthorizationPending):
    """Raised by ``poll`` while the user is still authenticating.

    Sentinel only — the host's poll loop catches this and continues.
    """
