"""Authentication and authorization for the assistant service.

This module used to carry its own JWT verification and permission
query, written before there was a shared one. Both now live in
:mod:`imbi.common.auth.permissions`, so the names below are re-exports
and the endpoints that import them are unchanged.

Two behaviors changed with the switch, both toward the platform norm:

* A caller may now authenticate with an ``ik_`` API key or a
  service-account client-credentials token, not only a user JWT.
  ``AuthContext.user`` is ``None`` for a service account, which is why
  the endpoints here reach for ``require_user`` rather than ``user``.
* Role inheritance resolves correctly. The local query walked
  ``INHERITS_FROM*0..``, and Apache AGE does not honor the zero-hop
  case, so a role's own grants were the only ones that counted. The
  shared query collects ancestors with ``*1..`` and unions the start
  role back in.
"""

from imbi.common import models
from imbi.common.auth import permissions

__all__ = [
    'AuthContext',
    'User',
    'get_current_user',
    'load_principal_permissions',
    'oauth2_scheme',
]

AuthContext = permissions.AuthContext
User = models.User
get_current_user = permissions.get_current_user
load_principal_permissions = permissions.load_principal_permissions
oauth2_scheme = permissions.oauth2_scheme
