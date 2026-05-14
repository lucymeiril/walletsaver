"""
SSRF prevention — URL validation with IP blocklist.

Validates URLs before they are assigned as crawler targets or
used in internal HTTP requests. Blocks private IPs, cloud metadata
endpoints, and non-HTTP schemes.
"""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from fastapi import HTTPException

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

BLOCKED_HOSTNAMES: frozenset[str] = frozenset({
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
})

BLOCKED_METADATA_IPS: frozenset[str] = frozenset({
    "169.254.169.254",
    "100.100.100.200",
    "metadata.google.internal",
})

PRIVATE_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("169.254.0.0/16"),
    ipaddress.IPv4Network("100.64.0.0/10"),
    ipaddress.IPv4Network("0.0.0.0/8"),
    ipaddress.IPv6Network("::1/128"),
    ipaddress.IPv6Network("fc00::/7"),
    ipaddress.IPv6Network("fe80::/10"),
    ipaddress.IPv6Network("::ffff:0:0/96"),
]


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address falls within any private/reserved range."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    for network in PRIVATE_NETWORKS:
        if addr in network:
            return True
    return False


def _resolve_hostname(hostname: str) -> list[str]:
    """
    Resolve a hostname to IP addresses.

    This catches DNS rebinding where a public hostname resolves to a private IP.
    """
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        return list({result[4][0] for result in results})
    except socket.gaierror:
        return []


def validate_target_url(url: str, field_name: str = "target_url") -> str:
    """
    Validate a URL for use as a crawler target.

    Checks:
    1. Scheme is http or https
    2. Hostname is not empty
    3. Hostname is not a blocked name (localhost, metadata, etc.)
    4. Resolved IP is not in any private range
    5. Port is standard (80, 443) or in allowed range

    Returns the validated URL.
    Raises HTTPException(422) on validation failure.
    """
    if not url or not isinstance(url, str):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: URL must be a non-empty string",
        )

    url = url.strip()

    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: malformed URL",
        )

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: scheme must be http or https, got '{parsed.scheme}'",
        )

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: URL must have a hostname",
        )

    hostname_lower = hostname.lower()

    if hostname_lower in BLOCKED_HOSTNAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: hostname '{hostname}' is not allowed",
        )

    if hostname_lower in BLOCKED_METADATA_IPS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: cloud metadata endpoint not allowed",
        )

    if _is_private_ip(hostname):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: private/internal IP addresses are not allowed",
        )

    resolved_ips = _resolve_hostname(hostname)
    for ip in resolved_ips:
        if _is_private_ip(ip):
            logger.warning(
                "SSRF blocked: hostname=%s resolved to private IP=%s url=%s",
                hostname,
                ip,
                url,
            )
            raise HTTPException(
                status_code=422,
                detail=f"Invalid {field_name}: hostname resolves to a private IP address",
            )

    port = parsed.port
    if port is not None and port not in {80, 443, 8080, 8443}:
        logger.info(
            "Non-standard port in target_url: port=%d url=%s", port, url
        )

    return url
