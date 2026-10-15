"""Pod self-deletion at the end of a chain (plan section 4.2 step 5).

The pod mounts a projected service account token in the ``runner``
container only, owned by uid 0 with mode ``0400``. The runner reads it
with its saved uid 0 here, once, at the end of the chain: during the
chain no process of the pod can read it. The token's Role allows only
``delete`` on pods in the runner namespace. The ReplicaSet then starts
a clean pod.

The pod name and namespace come from the downward API (``POD_NAME``,
``POD_NAMESPACE``). Without them (a test pod), nothing is deleted.
"""

import logging
import os
import ssl

import httpx

from imbi.harness import privilege

LOGGER = logging.getLogger(__name__)

TOKEN = '/var/run/secrets/kubernetes.io/serviceaccount/token'
CA = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
API = 'https://kubernetes.default.svc'


async def delete_own_pod() -> bool:
    """Delete this pod. Return whether Kubernetes accepted it."""
    name = os.environ.get('POD_NAME')
    namespace = os.environ.get('POD_NAMESPACE')
    if not name or not namespace:
        LOGGER.info('No POD_NAME or POD_NAMESPACE: the pod stays')
        return False
    try:
        with privilege.effective():
            token = privilege.read_root_file(TOKEN)
        context = ssl.create_default_context(cafile=CA)
    except OSError as err:
        LOGGER.error('Cannot read the service account token: %s', err)
        return False
    async with httpx.AsyncClient(verify=context, timeout=10) as client:
        try:
            response = await client.delete(
                f'{API}/api/v1/namespaces/{namespace}/pods/{name}',
                headers={'Authorization': f'Bearer {token}'},
            )
        except httpx.HTTPError as err:
            LOGGER.error('Pod deletion failed: %s', type(err).__name__)
            return False
    if response.is_error:
        LOGGER.error('Pod deletion refused: %s', response.status_code)
        return False
    LOGGER.info('Deleted pod %s', name)
    return True
