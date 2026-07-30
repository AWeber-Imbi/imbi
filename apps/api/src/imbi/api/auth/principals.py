"""The identities Imbi's own background workers act under.

A *process principal* is a synthetic :class:`~permissions.AuthContext` --
never a stored user -- that background work stamps on the rows it writes so
the audit trail records which worker recorded them.  Readers that display
"who did this" filter them out with :func:`is_process_principal`: a process
name is provenance, not attribution.

Each worker aliases its own slug from here (``REQUESTED_BY =
principals.DEPLOYMENT_SYNC``) so the set and the workers cannot drift --
adding one without listing it here would surface a process name as a
release author.
"""

import functools

from imbi.api import models
from imbi.api.auth import permissions

#: Slugs, one per worker. See ``REQUESTED_BY`` in each worker's module.
COMMIT_SYNC = 'commit-sync'
DEPLOYMENT_SYNC = 'deployment-sync'
MAINTENANCE = 'maintenance'
OPSLOG_BACKFILL = 'maintenance-opslog-backfill'
PR_SYNC = 'pr-sync'
#: Fallback stamped when a queued job carries no requesting principal.
SYSTEM = 'system'

PROCESS_PRINCIPALS = frozenset(
    {
        COMMIT_SYNC,
        DEPLOYMENT_SYNC,
        MAINTENANCE,
        OPSLOG_BACKFILL,
        PR_SYNC,
        SYSTEM,
    }
)


def is_process_principal(name: str | None) -> bool:
    """Return ``True`` when ``name`` is a worker rather than a person.

    A missing name counts: nothing to attribute is the same answer as a
    process having recorded the row.
    """
    return not name or name in PROCESS_PRINCIPALS


@functools.cache
def system_auth(slug: str, display_name: str) -> permissions.AuthContext:
    """Synthetic principal a background worker acts under.

    Never persisted; exists so service functions that require an
    ``AuthContext`` attribute their work to the worker.  Identity attach is
    best-effort for these and falls back to the Integration's service
    credentials for a userless principal.
    """
    return permissions.AuthContext(
        auth_method='client_credentials',
        service_account=models.ServiceAccount(
            slug=slug, display_name=display_name
        ),
    )
