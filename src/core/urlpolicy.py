# --------------------------------------------------------------------------
# Destination policy for registered upstream services
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import ipaddress
import re
import socket
from typing import List, Optional, Union
from urllib.parse import urlsplit

from src.core.config import settings

IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

ALLOWED_SCHEMES = ("http", "https")

# Host names that must never be registered as an upstream. Private ranges such
# as 10/8, 172.16/12 and 192.168/16 stay allowed because the gateway exists to
# reach internal services.
BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)


class ServiceUrlPolicyError(ValueError):
    """Raised when an upstream URL violates the destination policy."""


# A label that is purely decimal, octal or 0x hexadecimal. A host made only of
# such labels is an address literal in one of the forms inet_aton accepts
# (decimal, octal, hexadecimal, shortened), not a DNS name. Treating those as
# opaque host names is what lets 2130706433 or 0x7f000001 reach 127.0.0.1.
_NUMERIC_LABEL = re.compile(r"^(?:0[xX][0-9a-fA-F]+|[0-9]+)$")


def _looks_like_ip_literal(host: str) -> bool:
    """True when the host cannot be a DNS name and must parse as an address."""
    if not host:
        return False
    if ":" in host:
        return True
    return all(_NUMERIC_LABEL.match(label) for label in host.split("."))


def _resolve_literal(host: str) -> Optional[IPAddress]:
    """Parse an address literal, including the shortened IPv4 forms."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        packed = socket.inet_aton(host)
    except OSError:
        return None
    return ipaddress.IPv4Address(packed)


def _classify_address(ip: IPAddress) -> Optional[str]:
    """Return a rejection reason for an address, or None when it is allowed."""
    candidate: IPAddress = ip
    mapped = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) else None
    if mapped is not None:
        # An IPv4-mapped IPv6 literal is judged by the address it maps to, so
        # a legitimate private destination is not blocked by accident.
        candidate = mapped

    if candidate.is_loopback:
        return "loopback addresses are not allowed"
    if candidate.is_link_local:
        return "link-local and metadata addresses are not allowed"
    if candidate.is_unspecified:
        return "unspecified addresses are not allowed"
    if candidate.is_multicast:
        return "multicast addresses are not allowed"
    if candidate.is_reserved:
        return "reserved addresses are not allowed"
    return None


def _check_host_address(host: str) -> Optional[str]:
    """Reject address literals that point at a forbidden destination.

    Returns a reason string when the host is a rejected address literal, and
    None when the host is either an allowed address or a DNS name.
    """
    ip = _resolve_literal(host)
    if ip is not None:
        return _classify_address(ip)
    if _looks_like_ip_literal(host):
        # It cannot be a host name and it did not parse as an address, so the
        # destination cannot be judged. Refusing is the safe answer.
        return "the host is not a valid address literal"
    return None


def _configured(values: List[str]) -> List[str]:
    return [value.strip().lower() for value in values if value.strip()]


def validate_service_url(value: str) -> str:
    """Validate an upstream service URL and return it normalised.

    Allowed: http and https, any resolvable host name including Docker service
    names, and private network addresses.
    Rejected: other schemes, missing host, embedded credentials, loopback,
    link-local and cloud metadata destinations, and address literals written in
    a shortened, octal or hexadecimal form that resolve to those.

    This is a registration time check on the literal value. A host name is not
    resolved here, so a name that later resolves to a forbidden address (DNS
    rebinding, or a record changed after registration) is not caught by this
    function. Egress filtering at the network layer remains necessary.
    """
    if not isinstance(value, str) or not value.strip():
        raise ServiceUrlPolicyError("Service URL must be a non-empty string")

    candidate = value.strip()

    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        raise ServiceUrlPolicyError(f"Service URL is not parsable: {exc}") from exc

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise ServiceUrlPolicyError(
            "Service URL scheme must be one of " + ", ".join(ALLOWED_SCHEMES)
        )

    if parts.username or parts.password or "@" in parts.netloc:
        raise ServiceUrlPolicyError("Service URL must not contain userinfo")

    try:
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise ServiceUrlPolicyError(f"Service URL has an invalid port: {exc}") from exc

    if not hostname:
        raise ServiceUrlPolicyError("Service URL must contain a host")

    if port is not None and not (1 <= port <= 65535):
        raise ServiceUrlPolicyError("Service URL port is out of range")

    if parts.query or parts.fragment:
        raise ServiceUrlPolicyError(
            "Service URL must not contain a query string or fragment"
        )

    # A trailing dot is a fully qualified form of the same name, so it must
    # not be a way around the blocked name list.
    host = hostname.lower().rstrip(".")
    if not host:
        raise ServiceUrlPolicyError("Service URL must contain a host")

    if host in BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise ServiceUrlPolicyError(f"Host '{hostname}' is not an allowed destination")

    reason = _check_host_address(host)
    if reason:
        raise ServiceUrlPolicyError(f"Host '{hostname}' rejected: {reason}")

    denied = _configured(list(settings.SERVICE_URL_DENIED_HOSTS))
    if host in denied:
        raise ServiceUrlPolicyError(f"Host '{hostname}' is on the denylist")

    allowed = _configured(list(settings.SERVICE_URL_ALLOWED_HOSTS))
    if allowed and host not in allowed:
        raise ServiceUrlPolicyError(f"Host '{hostname}' is not on the allowlist")

    normalised = candidate.rstrip("/")
    return normalised


def validate_health_check_path(value: str) -> str:
    """Validate the health check path of a registered service."""
    if not isinstance(value, str) or not value.strip():
        raise ServiceUrlPolicyError("Health check path must be a non-empty string")

    candidate = value.strip()
    if not candidate.startswith("/"):
        raise ServiceUrlPolicyError("Health check path must start with '/'")
    if "://" in candidate or candidate.startswith("//"):
        raise ServiceUrlPolicyError("Health check path must not be an absolute URL")
    if ".." in candidate:
        raise ServiceUrlPolicyError("Health check path must not contain '..'")
    return candidate
