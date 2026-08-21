"""Unit tests for app.monitoring.target.

No network access, no DNS resolution.
All cases are deterministic and offline.
"""

import pytest

from app.monitoring.target import InvalidTargetError, NetworkTarget, TargetType


# ---------------------------------------------------------------------------
# IPv4
# ---------------------------------------------------------------------------
class TestIPv4:
    def test_valid_private(self) -> None:
        t = NetworkTarget.parse("192.168.0.1")
        assert t.value == "192.168.0.1"
        assert t.type == TargetType.IPV4

    def test_valid_loopback(self) -> None:
        t = NetworkTarget.parse("127.0.0.1")
        assert t.value == "127.0.0.1"
        assert t.type == TargetType.IPV4

    def test_valid_another_private(self) -> None:
        t = NetworkTarget.parse("10.0.0.25")
        assert t.value == "10.0.0.25"
        assert t.type == TargetType.IPV4

    def test_invalid_octet_overflow(self) -> None:
        with pytest.raises(InvalidTargetError):
            NetworkTarget.parse("192.168.1.300")

    def test_invalid_all_octets_overflow(self) -> None:
        with pytest.raises(InvalidTargetError):
            NetworkTarget.parse("999.999.999.999")

    def test_strips_surrounding_whitespace(self) -> None:
        t = NetworkTarget.parse("  192.168.1.1  ")
        assert t.value == "192.168.1.1"
        assert t.type == TargetType.IPV4


# ---------------------------------------------------------------------------
# IPv6
# ---------------------------------------------------------------------------
class TestIPv6:
    def test_valid_loopback(self) -> None:
        t = NetworkTarget.parse("::1")
        assert t.value == "::1"
        assert t.type == TargetType.IPV6

    def test_valid_full_address(self) -> None:
        t = NetworkTarget.parse("2001:db8::1")
        assert t.value == "2001:db8::1"
        assert t.type == TargetType.IPV6

    def test_normalises_compressed_form(self) -> None:
        t = NetworkTarget.parse("2001:0db8:0000:0000:0000:0000:0000:0001")
        assert t.value == "2001:db8::1"
        assert t.type == TargetType.IPV6

    def test_invalid_ipv6(self) -> None:
        with pytest.raises(InvalidTargetError):
            NetworkTarget.parse("gggg::1")


# ---------------------------------------------------------------------------
# Hostname
# ---------------------------------------------------------------------------
class TestHostname:
    def test_simple_hostname(self) -> None:
        t = NetworkTarget.parse("localhost")
        assert t.value == "localhost"
        assert t.type == TargetType.HOSTNAME

    def test_dotted_domain(self) -> None:
        t = NetworkTarget.parse("example.com")
        assert t.value == "example.com"
        assert t.type == TargetType.HOSTNAME

    def test_local_domain(self) -> None:
        t = NetworkTarget.parse("server.local")
        assert t.value == "server.local"
        assert t.type == TargetType.HOSTNAME

    def test_uppercase_normalised_to_lowercase(self) -> None:
        t = NetworkTarget.parse("MyServer.Local")
        assert t.value == "myserver.local"
        assert t.type == TargetType.HOSTNAME

    def test_mixed_case_domain(self) -> None:
        t = NetworkTarget.parse("Example.COM")
        assert t.value == "example.com"
        assert t.type == TargetType.HOSTNAME

    def test_invalid_hostname_with_internal_space(self) -> None:
        with pytest.raises(InvalidTargetError):
            NetworkTarget.parse("host name")

    def test_invalid_hostname_starts_with_hyphen(self) -> None:
        with pytest.raises(InvalidTargetError):
            NetworkTarget.parse("-invalid.com")

    def test_invalid_hostname_with_underscore(self) -> None:
        # Underscores are not valid in hostnames per RFC 952/1123.
        with pytest.raises(InvalidTargetError):
            NetworkTarget.parse("bad_host")

    def test_url_http_rejected(self) -> None:
        with pytest.raises(InvalidTargetError):
            NetworkTarget.parse("http://example.com")

    def test_url_https_rejected(self) -> None:
        with pytest.raises(InvalidTargetError):
            NetworkTarget.parse("https://example.com")

    def test_host_with_port_rejected(self) -> None:
        with pytest.raises(InvalidTargetError):
            NetworkTarget.parse("192.168.1.1:8080")

    def test_hostname_with_port_rejected(self) -> None:
        with pytest.raises(InvalidTargetError):
            NetworkTarget.parse("example.com:443")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_empty_string(self) -> None:
        with pytest.raises(InvalidTargetError):
            NetworkTarget.parse("")

    def test_only_spaces(self) -> None:
        with pytest.raises(InvalidTargetError):
            NetworkTarget.parse("   ")

    def test_tab_character(self) -> None:
        with pytest.raises(InvalidTargetError):
            NetworkTarget.parse("host\tname")

    def test_error_contains_raw_value(self) -> None:
        with pytest.raises(InvalidTargetError) as exc_info:
            NetworkTarget.parse("not valid!")
        assert exc_info.value.raw == "not valid!"

    def test_error_contains_reason(self) -> None:
        with pytest.raises(InvalidTargetError) as exc_info:
            NetworkTarget.parse("")
        assert exc_info.value.reason != ""

    def test_network_target_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        t = NetworkTarget.parse("localhost")
        with pytest.raises(FrozenInstanceError):
            t.value = "other"  # type: ignore[misc]
