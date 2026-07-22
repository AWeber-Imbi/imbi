"""HTTP client for talking to the Imbi API.

Exposes ``Imbi``, an ``httpx.AsyncClient`` subclass with bookkeeping
methods used by services that integrate with the Imbi API (e.g.
``imbi-gateway``).
"""

from imbi_common.api.client import Imbi
from imbi_common.api.settings import Settings

__all__ = ['Imbi', 'Settings']
