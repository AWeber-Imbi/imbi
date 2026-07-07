"""Integration credential storage.

Plugin Architecture v3: there is exactly one credential store per
Integration -- ``Integration.encrypted_credentials``, a mapping of
credential field name to its Fernet-encrypted value. Decryption is done
in ``imbi-common`` via
:func:`imbi_common.plugins.credentials.decrypt_integration_credentials`
so every host shares one code path; this module only writes the blob and
reports which fields are populated (never the plaintext values).
"""

import json
import logging
import typing

import fastapi
from imbi_common import graph
from imbi_common.auth.encryption import TokenEncryption

LOGGER = logging.getLogger(__name__)

# Bounded retries for the credential compare-and-swap. Each retry
# re-reads the committed blob and re-applies the partial update on top so
# concurrent patches converge; the cap only fires under pathological
# sustained contention on the same Integration.
_MAX_PATCH_RETRIES = 3

_READ_CREDS: typing.LiteralString = """
MATCH (i:Integration {{slug: {slug}}})-[:BELONGS_TO]->
  (:Organization {{slug: {org_slug}}})
RETURN i.encrypted_credentials AS creds
LIMIT 1
"""


async def _read_encrypted_credentials(
    db: graph.Graph,
    integration_slug: str,
    org_slug: str,
) -> tuple[bool, str, dict[str, str]]:
    """Return ``(found, raw_blob, {field: ciphertext})``.

    ``found`` is ``False`` when no Integration matches ``slug`` within
    ``org_slug``. ``raw_blob`` is the stored JSON string verbatim (``''``
    when absent) -- the compare-and-swap witness.
    """
    records = await db.execute(
        _READ_CREDS,
        {'slug': integration_slug, 'org_slug': org_slug},
        ['creds'],
    )
    if not records:
        return False, '', {}
    raw = graph.parse_agtype(records[0].get('creds'))
    if not raw or not isinstance(raw, str):
        return True, '', {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        LOGGER.warning(
            'Integration %r credentials blob is not valid JSON',
            integration_slug,
        )
        return True, raw, {}
    if not isinstance(parsed, dict):
        return True, raw, {}
    typed = typing.cast('dict[str, typing.Any]', parsed)
    return True, raw, {k: str(v) for k, v in typed.items() if v}


async def get_integration_credential_fields(
    db: graph.Graph,
    integration_slug: str,
    org_slug: str,
) -> list[str]:
    """Return the credential field names currently populated.

    The ciphertext (and plaintext) values are never surfaced.
    """
    _found, _raw, encrypted = await _read_encrypted_credentials(
        db, integration_slug, org_slug
    )
    return sorted(encrypted)


async def patch_integration_credentials(
    db: graph.Graph,
    integration_slug: str,
    org_slug: str,
    updates: dict[str, str | None],
) -> list[str]:
    """Apply a partial update to ``Integration.encrypted_credentials``.

    ``updates`` maps a credential field name to its new plaintext value.
    ``None`` (or an empty string) removes the field. Existing fields not
    present in ``updates`` are preserved. Returns the resulting set of
    populated field names.

    Guarded by a compare-and-swap on the stored blob so two concurrent
    patches cannot clobber each other: each attempt re-reads the
    committed map and only writes when the stored ciphertext is unchanged
    since the read.
    """
    encryptor = TokenEncryption.get_instance()
    for _attempt in range(_MAX_PATCH_RETRIES):
        found, expected, current = await _read_encrypted_credentials(
            db, integration_slug, org_slug
        )
        if not found:
            raise fastapi.HTTPException(
                status_code=404, detail='Integration not found'
            )
        for field, value in updates.items():
            if not value:
                current.pop(field, None)
            else:
                encrypted = encryptor.encrypt(value)
                if encrypted is not None:
                    current[field] = encrypted
        blob = json.dumps(current)
        query: typing.LiteralString = """
        MATCH (i:Integration {{slug: {slug}}})-[:BELONGS_TO]->
          (:Organization {{slug: {org_slug}}})
        WHERE coalesce(i.encrypted_credentials, '') = {expected}
        SET i.encrypted_credentials = {blob}
        RETURN i
        """
        updated = await db.execute(
            query,
            {
                'slug': integration_slug,
                'org_slug': org_slug,
                'expected': expected,
                'blob': blob,
            },
            ['i'],
        )
        if updated:
            return sorted(current)
    raise fastapi.HTTPException(
        status_code=409,
        detail='Integration credentials were modified concurrently; retry',
    )
