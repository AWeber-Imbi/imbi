"""Read the CVE catalog that the ``cve-sync`` maintenance operation fills.

The catalog is global, like the packages it describes, so the path has no
organization. Reading it needs ``component:read``: whoever can read a
package's advisories can read the records behind them.
"""

import typing

import fastapi

from imbi.api import cves
from imbi.api.auth import permissions

cves_router = fastapi.APIRouter(prefix='/cves', tags=['CVEs'])


@cves_router.get('/{cve_id}')
async def get_cve(
    cve_id: str,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('component:read')),
    ],
) -> cves.CveRecord:
    """Return one CVE record from the catalog."""
    normalized = cves.normalize(cve_id)
    record = (await cves.lookup([normalized])).get(normalized)
    if record is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'No CVE {normalized!r} in the catalog'
        )
    return record
