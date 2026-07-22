"""Request-aware public URL derivation.

A deployment may be reachable on more than one host -- e.g. an internal
host that fronts the SPA plus a separate internet-facing host that fronts
the MCP OAuth login. Absolute URLs advertised in :rfc:`8414` metadata or
handed to OAuth clients/IdPs must name the host the caller actually
reached, not a single global ``IMBI_API_URL``; otherwise discovery fails
its issuer check and IdP callbacks land on the wrong (often unreachable)
host.

The externally-visible origin is taken from the request as rewritten by
the proxy-headers middleware -- honored only for ``forwarded_allow_ips``
-- but is used only when it is an explicitly *trusted* origin (the
configured ``public_base_url`` plus ``cors_allowed_origins``). Anything
else falls back to the static ``public_base_url`` so a spoofed ``Host``
header can never redirect freshly minted tokens off-origin.
"""

from urllib import parse as urlparse

import fastapi

from imbi.api import settings


def trusted_origins() -> set[str]:
    """``scheme://host`` origins the deployment will speak as itself."""
    cfg = settings.get_server_config()
    origins = {o.rstrip('/') for o in cfg.cors_allowed_origins}
    parsed = urlparse.urlparse(cfg.public_base_url)
    if parsed.scheme and parsed.netloc:
        origins.add(f'{parsed.scheme}://{parsed.netloc}')
    return origins


def request_origin(request: fastapi.Request) -> str | None:
    """Trusted ``scheme://host`` for *request*, or ``None`` if untrusted.

    Scheme and host come from the (proxy-validated) request, so this is
    the origin the client actually used. Returned only when it is a
    configured trusted origin.
    """
    origin = f'{request.url.scheme}://{request.url.netloc}'
    return origin if origin in trusted_origins() else None


def public_base_url_for_request(request: fastapi.Request) -> str:
    """``public_base_url`` rebased onto the request's trusted origin.

    Preserves the configured API path prefix (e.g. ``/api``). Falls back
    to the static ``public_base_url`` when the request origin is not
    trusted.
    """
    cfg = settings.get_server_config()
    origin = request_origin(request)
    if origin is None:
        return cfg.public_base_url
    return f'{origin}{cfg.api_prefix}'
