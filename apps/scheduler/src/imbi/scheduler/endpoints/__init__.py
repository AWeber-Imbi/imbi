"""HTTP API for imbi-scheduler.

One router per PRD section 10, mounted by :func:`imbi.scheduler.app.create_app`
under the base path. There are no ``/credentials`` routes: ADR 0002 removed
the credential store, so there is nothing for them to manage.
"""

import fastapi

from imbi.scheduler.endpoints import runs, tasks

router = fastapi.APIRouter()
router.include_router(tasks.router)
router.include_router(runs.router)

__all__ = ['router']
