# Authentication Guide

This guide covers implementing authentication using imbi-common's auth
primitives.

## Overview

The auth module provides three core capabilities:

1. **Password Hashing**: Secure password storage with Argon2id
2. **JWT Tokens**: Stateless authentication with access/refresh tokens
3. **Token Encryption**: Fernet encryption for sensitive data at rest

## Password Management

### Hashing Passwords

Always hash passwords before storing them in the database:

```python
from imbi_common.auth import core
from imbi_common import models, neo4j

# Hash the password
password_hash = core.hash_password("user_password_123")

# Create user with hashed password
user = models.User(
    email="user@example.com",
    display_name="User Name",
    password_hash=password_hash,
    is_active=True
)
await neo4j.create_node(user)
```

### Verifying Passwords

During login, verify the provided password against the stored hash:

```python
from imbi_common.auth import core
from imbi_common import models, neo4j

# Fetch user
user = await neo4j.fetch_node(
    models.User,
    {"email": "user@example.com"}
)

if user is None:
    print("User not found")
elif not user.is_active:
    print("User is inactive")
elif core.verify_password("user_password_123", user.password_hash):
    print("Login successful!")
else:
    print("Invalid password")
```

### Password Rehashing

Argon2id parameters may change over time. Check if passwords need
rehashing:

```python
from imbi_common.auth import core
from imbi_common import models, neo4j

user = await neo4j.fetch_node(
    models.User,
    {"email": "user@example.com"}
)

# During login, check if hash needs updating
if core.verify_password("user_password_123", user.password_hash):
    if core.needs_rehash(user.password_hash):
        # Update to latest parameters
        user.password_hash = core.hash_password("user_password_123")
        await neo4j.upsert(user, constraint={"email": user.email})
```

## JWT Tokens

### Creating Tokens

Generate access and refresh tokens after successful login:

```python
from imbi_common.auth import core

# Create access token (short-lived, e.g., 1 hour)
access_token = core.create_access_token(
    subject=user.email,
    extra_claims={
        "display_name": user.display_name,
        "is_admin": user.is_admin
    }
)

# Create refresh token (long-lived, e.g., 30 days)
refresh_token = core.create_refresh_token(
    subject=user.email
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
from imbi_common.auth import core

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
from imbi_common.auth import core

try:
    # Verify refresh token
    payload = core.verify_token(refresh_token)
    user_email = payload["sub"]

    # Fetch user to get current claims
    user = await neo4j.fetch_node(
        models.User,
        {"email": user_email}
    )

    if user is None or not user.is_active:
        raise Exception("User not found or inactive")

    # Issue new access token
    new_access_token = core.create_access_token(
        subject=user.email,
        extra_claims={
            "display_name": user.display_name,
            "is_admin": user.is_admin
        }
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
from imbi_common.auth import encryption
from imbi_common import models, neo4j

# Encrypt OAuth access token before storing
encrypted_token = encryption.encrypt_token("oauth_access_token_abc123")

# Store encrypted token
oauth_identity = models.OAuthIdentity(
    user_id="user@example.com",
    provider="google",
    provider_user_id="12345",
    access_token=encrypted_token,  # Stored encrypted
    refresh_token=None
)
await neo4j.create_node(oauth_identity)
```

### Decrypting Tokens

Decrypt tokens when needed:

```python
from imbi_common.auth import encryption
from imbi_common import models, neo4j

# Fetch OAuth identity
oauth_identity = await neo4j.fetch_node(
    models.OAuthIdentity,
    {"user_id": "user@example.com", "provider": "google"}
)

# Decrypt access token
decrypted_token = encryption.decrypt_token(
    oauth_identity.access_token
)

# Use decrypted token for OAuth API calls
```

## Session Management

### Creating Sessions

Track user sessions for audit and security:

```python
from imbi_common import models, neo4j, clickhouse
from datetime import datetime
import uuid

# Create session record in Neo4j
session = models.Session(
    session_id=str(uuid.uuid4()),
    user_id=user.email,
    created_at=datetime.now(),
    last_activity=datetime.now(),
    ip_address="192.168.1.100",
    user_agent="Mozilla/5.0 ..."
)
await neo4j.create_node(session)

# Log session activity to ClickHouse
activity_data = {
    "timestamp": datetime.now(),
    "session_id": session.session_id,
    "user_id": user.email,
    "activity_type": "login",
    "ip_subnet": "192.168.1.0",  # Truncated for GDPR
    "user_agent_family": "Chrome",
    "user_agent_version": "120.0",
    "metadata": "/api/auth/login"
}
await clickhouse.insert("session_activity", [activity_data])
```

### Validating Sessions

Check session validity on each request:

```python
from imbi_common import models, neo4j
from datetime import datetime, timedelta

session = await neo4j.fetch_node(
    models.Session,
    {"session_id": session_id}
)

if session is None:
    raise Exception("Session not found")

# Check if session expired (e.g., 24 hours)
session_timeout = timedelta(hours=24)
if datetime.now() - session.last_activity > session_timeout:
    # Session expired
    await neo4j.delete_node(session)
    raise Exception("Session expired")

# Update last activity
session.last_activity = datetime.now()
await neo4j.upsert(session, constraint={"session_id": session.session_id})
```

### Ending Sessions

Handle logout by deleting the session:

```python
from imbi_common import models, neo4j

session = await neo4j.fetch_node(
    models.Session,
    {"session_id": session_id}
)

if session:
    await neo4j.delete_node(session)
```

## API Keys

### Generating API Keys

Create API keys for programmatic access:

```python
from imbi_common import models, neo4j
from datetime import datetime, timedelta
import secrets

# Generate secure random key
api_key = secrets.token_urlsafe(32)

# Hash the key before storing (like passwords)
from imbi_common.auth import core
api_key_hash = core.hash_password(api_key)

# Create API key record
api_key_record = models.APIKey(
    key_hash=api_key_hash,
    user_id="user@example.com",
    name="CI/CD Pipeline",
    created_at=datetime.now(),
    expires_at=datetime.now() + timedelta(days=365),
    last_used_at=None,
    is_active=True
)
await neo4j.create_node(api_key_record)

# Return the plain key to user (only shown once!)
return {"api_key": api_key}
```

### Validating API Keys

Verify API keys on authenticated endpoints:

```python
from imbi_common import models, neo4j
from imbi_common.auth import core

async def validate_api_key(api_key: str) -> models.User | None:
    # Fetch all active API keys (consider adding an index)
    async for key_record in neo4j.fetch_nodes(
        models.APIKey,
        filters={"is_active": True}
    ):
        # Verify against stored hash
        if core.verify_password(api_key, key_record.key_hash):
            # Check expiration
            if key_record.expires_at < datetime.now():
                return None

            # Update last used
            key_record.last_used_at = datetime.now()
            await neo4j.upsert(
                key_record,
                constraint={"key_hash": key_record.key_hash}
            )

            # Fetch and return user
            return await neo4j.fetch_node(
                models.User,
                {"email": key_record.user_id}
            )

    return None
```

## MFA (Multi-Factor Authentication)

### Enrolling TOTP

Store encrypted TOTP secrets:

```python
from imbi_common import models, neo4j
from imbi_common.auth import encryption
import pyotp

# Generate TOTP secret
totp_secret = pyotp.random_base32()

# Encrypt before storing
encrypted_secret = encryption.encrypt_token(totp_secret)

# Store encrypted secret
totp_record = models.TOTPSecret(
    user_id=user.email,
    encrypted_secret=encrypted_secret,
    is_enabled=False,  # User must verify first
    created_at=datetime.now()
)
await neo4j.create_node(totp_record)

# Generate QR code URI for user
totp = pyotp.TOTP(totp_secret)
qr_uri = totp.provisioning_uri(
    name=user.email,
    issuer_name="Imbi"
)

return {"qr_uri": qr_uri}
```

### Verifying TOTP

Verify TOTP codes during login:

```python
from imbi_common import models, neo4j
from imbi_common.auth import encryption
import pyotp

# Fetch TOTP secret
totp_record = await neo4j.fetch_node(
    models.TOTPSecret,
    {"user_id": user.email, "is_enabled": True}
)

if totp_record is None:
    raise Exception("MFA not enabled for user")

# Decrypt secret
totp_secret = encryption.decrypt_token(totp_record.encrypted_secret)

# Verify code
totp = pyotp.TOTP(totp_secret)
if totp.verify(user_provided_code, valid_window=1):
    print("MFA verification successful")
else:
    print("Invalid MFA code")
```

## Configuration

Configure auth settings in your config file:

```toml
[auth]
# JWT
jwt_secret = "your-secret-key-change-in-production"
jwt_algorithm = "HS256"
access_token_expire_seconds = 3600        # 1 hour
refresh_token_expire_seconds = 2592000    # 30 days

# Password Policy
password_min_length = 12
password_require_uppercase = true
password_require_lowercase = true
password_require_digit = true
password_require_special = true

# Sessions
session_timeout_seconds = 86400           # 24 hours
max_concurrent_sessions = 5

# API Keys
api_key_max_lifetime_days = 365

# Encryption (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
encryption_key = "your-fernet-key-here"

# MFA
mfa_issuer_name = "Imbi"
mfa_totp_period = 30
mfa_totp_digits = 6
```

⚠️ **Security Notes**:
- Always use strong, randomly-generated secrets in production
- Store secrets in a secrets manager, not in config files
- Rotate secrets regularly
- Use HTTPS for all authentication endpoints
- Implement rate limiting on login endpoints
