"""Pod self-deletion at the end of a chain (plan section 4.2 step 5),
and the egress labels of the chain (egress allowlist PRD 5.7).

The pod mounts a projected service account token in the ``runner``
container only, owned by uid 0 with mode ``0400``. The runner reads it
with its saved uid 0 here, for each call: no other process of the pod
can read it. The token's Role allows only ``delete`` (a Deployment
pod) and ``patch`` (with egress enforcement) on pods in the runner
namespace. An admission policy lets the runner change only the egress
labels of its own pod. After a deletion, the ReplicaSet starts a clean
pod.

The pod name and namespace come from the downward API (``POD_NAME``,
``POD_NAMESPACE``). Without them (a test pod), nothing is deleted.
"""

import json
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
    return await _own_pod('DELETE', 'deletion')


async def label_own_pod(labels: dict[str, str]) -> bool:
    """Add ``labels`` to this pod. Return whether Kubernetes accepted
    it."""
    return await _own_pod(
        'PATCH',
        'labeling',
        content=json.dumps({'metadata': {'labels': labels}}),
        headers={'Content-Type': 'application/merge-patch+json'},
    )


async def _own_pod(
    method: str,
    what: str,
    *,
    content: str | None = None,
    headers: dict[str, str] | None = None,
) -> bool:
    name = os.environ.get('POD_NAME')
    namespace = os.environ.get('POD_NAMESPACE')
    if not name or not namespace:
        LOGGER.info('No POD_NAME or POD_NAMESPACE: no pod %s', what)
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
            response = await client.request(
                method,
                f'{API}/api/v1/namespaces/{namespace}/pods/{name}',
                content=content,
                headers={
                    **(headers or {}),
                    'Authorization': f'Bearer {token}',
                },
            )
        except httpx.HTTPError as err:
            LOGGER.error('Pod %s failed: %s', what, type(err).__name__)
            return False
    if response.is_error:
        LOGGER.error('Pod %s refused: %s', what, response.status_code)
        return False
    LOGGER.info('Pod %s of %s done', what, name)
    return True
