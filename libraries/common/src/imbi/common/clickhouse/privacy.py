"""Privacy utilities for GDPR-compliant ClickHouse storage.

This module provides utilities for transforming PII data before storage
in ClickHouse to comply with GDPR and data minimization principles.
"""

import hashlib
import ipaddress
import typing


def hash_ip_address(ip: str) -> str:
    """Hash IP address using SHA256 for privacy-preserving storage.

    Args:
        ip: IP address string (IPv4 or IPv6)

    Returns:
        SHA256 hex digest of the IP address

    Example:
        >>> hash_ip_address('192.168.1.1')
        'c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646'

    """
    return hashlib.sha256(ip.encode('utf-8')).hexdigest()


def truncate_ip_to_subnet(ip: str) -> str:
    """Truncate IP address to subnet for privacy-preserving storage.

    IPv4 addresses are truncated to /24 subnet (last octet zeroed).
    IPv6 addresses are truncated to /48 subnet.

    Args:
        ip: IP address string (IPv4 or IPv6)

    Returns:
        Truncated IP subnet string

    Raises:
        ValueError: If IP address is invalid

    Examples:
        >>> truncate_ip_to_subnet('192.168.1.1')
        '192.168.1.0'
        >>> truncate_ip_to_subnet('2001:0db8:85a3:0000:0000:8a2e:0370:7334')
        '2001:db8:85a3::'

    """
    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError as err:
        raise ValueError(f'Invalid IP address: {ip}') from err

    if isinstance(ip_obj, ipaddress.IPv4Address):
        # Truncate to /24 (zero last octet)
        network_v4 = ipaddress.IPv4Network(f'{ip}/24', strict=False)
        return str(network_v4.network_address)
    else:
        # Truncate IPv6 to /48
        network_v6 = ipaddress.IPv6Network(f'{ip}/48', strict=False)
        return str(network_v6.network_address)


def parse_user_agent(
    user_agent: str | None,
) -> tuple[str, str]:
    """Parse user agent string to extract browser family and version.

    This function performs basic parsing without external dependencies.
    For production use, consider using the 'user-agents' package for more
    accurate parsing.

    Args:
        user_agent: User agent string from HTTP headers

    Returns:
        Tuple of (browser_family, version) where version is 'major.minor'
        Returns ('unknown', 'unknown') if parsing fails

    Examples:
        >>> parse_user_agent(
        ...     'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        ...     'AppleWebKit/537.36 (KHTML, like Gecko) '
        ...     'Chrome/91.0.4472.124 Safari/537.36'
        ... )
        ('Chrome', '91.0')

    Note:
        This is a simplified parser. For better accuracy, integrate
        a dedicated user agent parsing library like 'user-agents' or
        'ua-parser'.

    """
    if not user_agent:
        return ('unknown', 'unknown')

    ua_lower = user_agent.lower()

    # Simple heuristic-based parsing
    browser_patterns: list[tuple[str, str]] = [
        ('edg/', 'Edge'),
        ('chrome/', 'Chrome'),
        ('firefox/', 'Firefox'),
        ('safari/', 'Safari'),
        ('opera/', 'Opera'),
    ]

    for pattern, family in browser_patterns:
        if pattern in ua_lower:
            try:
                # Extract version after pattern
                start = ua_lower.index(pattern) + len(pattern)
                version_str = user_agent[start:].split()[0]
                # Get major.minor only
                parts = version_str.split('.')
                if len(parts) >= 2:
                    version = f'{parts[0]}.{parts[1]}'
                else:
                    version = parts[0]
                return (family, version)
            except (IndexError, ValueError):
                return (family, 'unknown')

    return ('unknown', 'unknown')


def sanitize_metadata(metadata: dict[str, typing.Any]) -> str:
    """Sanitize metadata dictionary to ensure no PII is included.

    Removes or redacts fields that commonly contain PII:
    - email, password, token, api_key, secret
    - Any field containing 'email', 'password', 'token', 'secret'

    Args:
        metadata: Dictionary of metadata to sanitize

    Returns:
        JSON string with PII fields redacted

    Example:
        >>> sanitize_metadata({
        ...     'endpoint': '/api/users',
        ...     'email': 'user@example.com',
        ...     'status': 200
        ... })
        '{"endpoint": "/api/users", "email": "[REDACTED]", "status": 200}'

    """
    import json

    pii_keywords = ['email', 'password', 'token', 'secret', 'api_key']

    sanitized = {}
    for key, value in metadata.items():
        key_lower = key.lower()
        if any(keyword in key_lower for keyword in pii_keywords):
            sanitized[key] = '[REDACTED]'
        elif isinstance(value, dict):
            # Recursively sanitize nested dicts
            sanitized[key] = json.loads(sanitize_metadata(value))
        elif isinstance(value, str) and any(
            keyword in value.lower() for keyword in pii_keywords
        ):
            # Redact string values that look like they contain PII
            sanitized[key] = '[REDACTED]'
        else:
            sanitized[key] = value

    return json.dumps(sanitized)
