# Authentication Guide

This guide covers implementing authentication using imbi-common's auth
primitives.

## Overview

The auth module provides two core capabilities:

1. **JWT Tokens**: Stateless authentication with access/refresh tokens
2. **Token Encryption**: Fernet encryption for sensitive data at rest

## JWT Tokens

### Creating Tokens

Generate access and refresh tokens after successful login:

```python
from imbi.common.auth import core

# Create access token (short-lived, e.g., 1 hour)
access_token = core.create_access_token(
    subject="user@example.com",
    extra_claims={
        "display_name": "Example User",
        "is_admin": False
    }
)

# Create refresh token (long-lived, e.g., 30 days)
refresh_token = core.create_refresh_token(
    subject="user@example.com"
)

# Return both tokens to client
return {
    "access_token": access_token,
    "refresh_token": refresh_token,
    "token_type": "bearer"
}
```

### Verifying Tokens

Verify and decode tokens on protected endpoints:

```python
from imbi.common.auth import core

try:
    # Verify the token
    payload = core.verify_token(access_token)

    # Extract claims
    user_email = payload["sub"]
    is_admin = payload.get("is_admin", False)

    # Proceed with authenticated request
    print(f"Authenticated as: {user_email}")

except Exception as e:
    # Token is invalid, expired, or malformed
    print(f"Authentication failed: {e}")
    # Return 401 Unauthorized
```

### Token Refresh Flow

Implement token refresh to avoid frequent re-authentication:

```python
from imbi.common.auth import core

try:
    # Verify refresh token
    payload = core.verify_token(refresh_token)
    user_email = payload["sub"]

    # Issue new access token with current claims
    new_access_token = core.create_access_token(
        subject=user_email,
        extra_claims={"display_name": "Example User"}
    )

    return {"access_token": new_access_token, "token_type": "bearer"}

except Exception as e:
    print(f"Token refresh failed: {e}")
    # Return 401 Unauthorized - user must login again
```

## Token Encryption

### Encrypting Sensitive Tokens

Use Fernet encryption for storing OAuth tokens or other sensitive data:

```python
from imbi.common.auth import encryption

# Encrypt a sensitive value before storing
encrypted_token = encryption.encrypt_token("oauth_access_token_abc123")

# Store the encrypted value in the database
```

### Decrypting Tokens

Decrypt tokens when needed:

```python
from imbi.common.auth import encryption

# Decrypt when you need to use the value
decrypted_token = encryption.decrypt_token(encrypted_value)
```

### Using the TokenEncryption Class

For more control, use the singleton `TokenEncryption` class directly:

```python
from imbi.common.auth.encryption import TokenEncryption

# Get the singleton instance
encryptor = TokenEncryption.get_instance()

# Encrypt/decrypt
encrypted = encryptor.encrypt("sensitive-value")
decrypted = encryptor.decrypt(encrypted)
```

## Configuration

Configure auth settings in your config file or environment:

```toml
[auth]
# JWT
jwt_secret = "your-secret-key-change-in-production"
jwt_algorithm = "HS256"
access_token_expire_seconds = 3600        # 1 hour
refresh_token_expire_seconds = 2592000    # 30 days

# Encryption (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
encryption_key = "your-fernet-key-here"
```

!!! warning "Security Notes"
    - Always use strong, randomly-generated secrets in production
    - Store secrets in a secrets manager, not in config files
    - Rotate secrets regularly
    - Use HTTPS for all authentication endpoints
    - Implement rate limiting on login endpoints
