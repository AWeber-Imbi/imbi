# Authentication

Authentication primitives for JWT tokens and encryption.

## Overview

The auth module provides core authentication functionality that can be used
by any service in the Imbi ecosystem:

- **JWT Tokens**: Access and refresh token creation/verification
- **Token Encryption**: Fernet encryption for sensitive data at rest
- **Config Encryption**: Fernet encryption for persisted configuration
  secrets, keyed separately from token encryption

## JWT Tokens

```python
from imbi_common.auth import core

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
from imbi_common.auth import encryption

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
from imbi_common.auth import encryption

# Encrypt a configuration secret
encrypted = encryption.encrypt_config_value("client-secret")

# Decrypt (None on invalid ciphertext)
decrypted = encryption.decrypt_config_value(encrypted)
```

## API Reference

### Core Functions

::: imbi_common.auth.core.create_access_token

::: imbi_common.auth.core.create_refresh_token

::: imbi_common.auth.core.verify_token

### Encryption Functions

::: imbi_common.auth.encryption.TokenEncryption

::: imbi_common.auth.encryption.get_fernet

::: imbi_common.auth.encryption.encrypt_token

::: imbi_common.auth.encryption.decrypt_token

::: imbi_common.auth.encryption.ConfigEncryption

::: imbi_common.auth.encryption.get_config_fernet

::: imbi_common.auth.encryption.encrypt_config_value

::: imbi_common.auth.encryption.decrypt_config_value
