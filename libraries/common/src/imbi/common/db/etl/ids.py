"""Deterministic ids for rows that the graph does not give an id.

A new id is derived from the graph values that identify the row, so a
second ETL run on the same source gives the same id (plan Appendix E,
E22).
"""

import hashlib

#: The alphabet and size of the ``nanoid`` package defaults, so a
#: derived id has the same form as an id that the application makes.
ALPHABET = '_-0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
SIZE = 21


def derive_id(namespace: str, *parts: str) -> str:
    """Return a nanoid-shaped id derived from *namespace* and *parts*.

    The same arguments always give the same id. Different arguments
    give different ids unless SHA-256 collides.

    """
    digest = hashlib.sha256(
        '\x00'.join((namespace, *parts)).encode('utf-8')
    ).digest()
    return ''.join(ALPHABET[byte & 63] for byte in digest[:SIZE])
