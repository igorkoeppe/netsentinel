"""Network target representation and validation.

This module is intentionally free of I/O.
It does not perform DNS resolution, ping or socket connections.
"""

import ipaddress
import re
from dataclasses import dataclass
from enum import StrEnum


class TargetType(StrEnum):
    """Classification of a validated network target."""

    IPV4 = "ipv4"
    IPV6 = "ipv6"
    HOSTNAME = "hostname"


class InvalidTargetError(ValueError):
    """Raised when a network target string cannot be parsed or is unsafe."""

    def __init__(self, raw: str, reason: str) -> None:
        self.raw = raw
        self.reason = reason
        super().__init__(f"Invalid target {raw!r}: {reason}")


# RFC 1123 label: 1–63 chars, starts/ends with alphanumeric, hyphens allowed in between.
_LABEL = r"[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
_HOSTNAME_RE = re.compile(rf"^{_LABEL}(?:\.{_LABEL})*\.?$")

# Reject anything that looks like a URL scheme or contains a port.
_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://")
_PORT_RE = re.compile(r":\d+$")

# Matches strings that look like IPv4 notation (digits and dots only).
# Used to reject malformed IPv4 before falling through to hostname parsing.
_DOTTED_DECIMAL_RE = re.compile(r"^\d+(\.\d+)+$")


def _looks_like_url(value: str) -> bool:
    return bool(_URL_SCHEME_RE.match(value))


def _is_ipv6_like(value: str) -> bool:
    """Return True if the value contains multiple colons (IPv6 notation)."""
    return value.count(":") > 1


def _looks_like_host_with_port(value: str) -> bool:
    # IPv6 addresses may contain multiple colons; skip the port check for them.
    if _is_ipv6_like(value):
        return False
    return bool(_PORT_RE.search(value))


def _looks_like_dotted_decimal(value: str) -> bool:
    """Return True if the value looks like an IPv4 literal (digits and dots)."""
    return bool(_DOTTED_DECIMAL_RE.match(value))


def _has_internal_spaces(value: str) -> bool:
    return " " in value or "\t" in value


def _parse_ip(value: str) -> tuple[str, TargetType] | None:
    """Return (normalised_value, type) if *value* is a valid IP address, else None."""
    try:
        addr = ipaddress.ip_address(value)
        if isinstance(addr, ipaddress.IPv4Address):
            return str(addr), TargetType.IPV4
        return addr.compressed, TargetType.IPV6
    except ValueError:
        return None


def _parse_hostname(value: str) -> str:
    """Return normalised hostname or raise InvalidTargetError."""
    # Strip trailing dot (FQDN notation) before matching.
    normalised = value.lower()
    if not _HOSTNAME_RE.match(normalised):
        raise InvalidTargetError(value, "not a valid hostname")
    return normalised


@dataclass(frozen=True)
class NetworkTarget:
    """A validated and normalised network target (IP or hostname).

    Do not instantiate directly — use :meth:`parse`.

    Attributes:
        value: Normalised string representation of the target.
        type:  Classification of the target (:class:`TargetType`).
    """

    value: str
    type: TargetType

    @classmethod
    def parse(cls, raw: str) -> "NetworkTarget":
        """Parse and validate a raw network target string.

        Accepted formats:
        - IPv4 address  (e.g. ``192.168.0.1``)
        - IPv6 address  (e.g. ``::1``, ``2001:db8::1``)
        - Hostname      (e.g. ``localhost``, ``server.local``, ``example.com``)

        Raises:
            InvalidTargetError: If the input is empty, contains spaces,
                looks like a URL, includes a port, or fails validation.
        """
        stripped = raw.strip()

        if not stripped:
            raise InvalidTargetError(raw, "target must not be empty")

        if _looks_like_url(stripped):
            raise InvalidTargetError(raw, "URLs are not accepted; provide a host only")

        if _looks_like_host_with_port(stripped):
            raise InvalidTargetError(raw, "ports are not accepted; provide a host only")

        if _has_internal_spaces(stripped):
            raise InvalidTargetError(raw, "target must not contain spaces")

        result = _parse_ip(stripped)
        if result is not None:
            value, target_type = result
            return cls(value=value, type=target_type)

        # A dotted-decimal that failed IP parsing is a malformed IP, not a hostname.
        if _looks_like_dotted_decimal(stripped):
            raise InvalidTargetError(stripped, "not a valid IP address")

        # Fall through to hostname validation.
        normalised = _parse_hostname(stripped)
        return cls(value=normalised, type=TargetType.HOSTNAME)
