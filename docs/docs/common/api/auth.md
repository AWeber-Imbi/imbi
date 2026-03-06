# Authentication

Authentication primitives for JWT tokens and encryption.

## Overview

The auth module provides core authentication functionality that can be used
by any service in the Imbi ecosystem:

- **JWT Tokens**: Access and refresh token creation/verification
- **Token Encryption**: Fernet encryption for sensitive data at rest

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
