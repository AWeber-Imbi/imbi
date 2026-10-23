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
import typing

import httpx

from imbi.harness import privilege

LOGGER = logging.getLogger(__name__)

TOKEN = '/var/run/secrets/kubernetes.io/serviceaccount/token'
CA = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
API = 'https://kubernetes.default.svc'


async def delete_own_pod() -> bool:
    """Delete this pod. Return whether Kubernetes accepted it."""
    return await _own_pod('DELETE', 'deletion') is not None


async def label_own_pod(labels: dict[str, str]) -> bool:
    """Add ``labels`` to this pod. Return whether Kubernetes accepted
    it."""
    return await _patch_labels(labels, 'labeling') is not None


async def own_pod_labels() -> dict[str, str] | None:
    """Return the labels of this pod; ``None`` when they cannot be
    read. An empty merge patch returns the pod, so the Role needs no
    ``get``."""
    response = await _patch_labels({}, 'label read')
    if response is None:
        return None
    try:
        pod: typing.Any = response.json()
        found: dict[str, typing.Any] = pod['metadata'].get('labels') or {}
    except (ValueError, KeyError, TypeError, AttributeError):
        LOGGER.error('Pod label read: the response is not a pod')
        return None
    return {str(k): str(v) for k, v in found.items()}


async def _patch_labels(
    labels: dict[str, str], what: str
) -> httpx.Response | None:
    return await _own_pod(
        'PATCH',
        what,
        content=json.dumps({'metadata': {'labels': labels}}),
        headers={'Content-Type': 'application/merge-patch+json'},
    )


async def _own_pod(
    method: str,
    what: str,
    *,
    content: str | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response | None:
    name = os.environ.get('POD_NAME')
    namespace = os.environ.get('POD_NAMESPACE')
    if not name or not namespace:
        LOGGER.info('No POD_NAME or POD_NAMESPACE: no pod %s', what)
        return None
    try:
        with privilege.effective():
            token = privilege.read_root_file(TOKEN)
        context = ssl.create_default_context(cafile=CA)
    except OSError as err:
        LOGGER.error('Cannot read the service account token: %s', err)
        return None
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
            return None
    if response.is_error:
        LOGGER.error('Pod %s refused: %s', what, response.status_code)
        return None
    LOGGER.info('Pod %s of %s done', what, name)
    return response
