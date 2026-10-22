# Authentication

Authentication primitives for JWT tokens and encryption.

## Overview

The auth module provides core authentication functionality that can be used
by any service in the Imbi ecosystem:

- **JWT Tokens**: Access and refresh token creation/verification
- **Token Encryption**: Fernet encryption for sensitive data at rest
- **Config Encryption**: Fernet encryption for persisted configuration
  secrets, keyed separately from token encryption
- **Password Hashing**: Argon2id hashes for passwords and API key secrets

For request authentication and permission checks, see
[Permissions](permissions.md).

## JWT Tokens

```python
from imbi.common.auth import core

# Create an access token
access_token = core.create_access_token(
    subject="user@example.com",
    extra_claims={"role": "admin"}
)

# Create a refresh token
refresh_token = core.create_refresh_token(
    subject="user@example.com"
)

# Verify and decode a token
try:
    payload = core.verify_token(access_token)
    user_id = payload["sub"]
    role = payload.get("role")
except Exception as e:
    print(f"Invalid token: {e}")
```

## Token Encryption

```python
from imbi.common.auth import encryption

# Encrypt sensitive data (e.g., OAuth tokens)
encrypted = encryption.encrypt_token("sensitive_oauth_token")

# Decrypt
decrypted = encryption.decrypt_token(encrypted)
```

## Config Encryption

Persisted configuration secrets (e.g. external MCP server credentials) are
encrypted with a dedicated key sourced from `IMBI_CONFIG_ENCRYPTION_KEY`,
separate from the token-encryption key, so the two can be rotated
independently. `decrypt_config_value` returns `None` for `None` or
invalid/corrupt ciphertext.

```python
from imbi.common.auth import encryption

# Encrypt a configuration secret
encrypted = encryption.encrypt_config_value("client-secret")

# Decrypt (None on invalid ciphertext)
decrypted = encryption.decrypt_config_value(encrypted)
```

## Password Hashing

`imbi.common.auth.password` hashes with Argon2id. API key verification in
[Permissions](permissions.md) uses the same hasher for key secrets.
`verify_password` returns `False` for a wrong password and for a hash
that is not valid. It does not raise.

```python
from imbi.common.auth import password

hashed = password.hash_password("correct horse battery staple")
if password.verify_password("correct horse battery staple", hashed):
    if password.needs_rehash(hashed):
        hashed = password.hash_password("correct horse battery staple")
```

## API Reference

### Core Functions

::: imbi.common.auth.core.create_access_token

::: imbi.common.auth.core.create_refresh_token

::: imbi.common.auth.core.verify_token

### Encryption Functions

::: imbi.common.auth.encryption.TokenEncryption

::: imbi.common.auth.encryption.get_fernet

::: imbi.common.auth.encryption.encrypt_token

::: imbi.common.auth.encryption.decrypt_token

::: imbi.common.auth.encryption.ConfigEncryption

::: imbi.common.auth.encryption.get_config_fernet

::: imbi.common.auth.encryption.encrypt_config_value

::: imbi.common.auth.encryption.decrypt_config_value

### Password Functions

::: imbi.common.auth.password.hash_password

::: imbi.common.auth.password.verify_password

::: imbi.common.auth.password.needs_rehash
