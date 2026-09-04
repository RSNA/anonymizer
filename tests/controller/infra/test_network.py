import socket
from unittest.mock import Mock, patch

import pytest

from src.anonymizer.utils.network import dns_lookup, get_local_ip_addresses, is_valid_ip


def test_get_local_ip_addresses_localhost() -> None:
    """Test that localhost IP is included in the returned addresses"""
    ip_addrs = get_local_ip_addresses()
    assert ip_addrs
    assert "127.0.0.1" in ip_addrs


def test_get_local_ip_addresses_excludes_link_local() -> None:
    """Test that link-local addresses (169.*) are excluded"""
    mock_adapter = Mock()
    mock_adapter.ips = [Mock(ip="169.254.1.1"), Mock(ip="192.168.1.1"), Mock(ip="127.0.0.1")]

    with patch("ifaddr.get_adapters", return_value=[mock_adapter]):
        ip_addrs = get_local_ip_addresses()
        assert "169.254.1.1" not in ip_addrs
        assert "192.168.1.1" in ip_addrs


def test_get_local_ip_addresses_handles_non_str_ips() -> None:
    """Test handling of non-string IP addresses from adapters"""
    mock_adapter = Mock()
    mock_adapter.ips = [
        Mock(ip=("2001:db8::", 64)),  # IPv6 tuple representation
        Mock(ip="192.168.1.1"),  # Regular IPv4 string
    ]

    with patch("ifaddr.get_adapters", return_value=[mock_adapter]):
        ip_addrs = get_local_ip_addresses()
        assert len(ip_addrs) == 1
        assert "192.168.1.1" in ip_addrs


def test_dns_lookup_valid_domain() -> None:
    """Test DNS lookup with a valid domain"""
    with patch("socket.gethostbyname", return_value="93.184.216.34"):
        result = dns_lookup("example.com")
        assert result == "93.184.216.34"


def test_dns_lookup_invalid_domain() -> None:
    """Test DNS lookup with an invalid domain"""
    with patch("socket.gethostbyname", side_effect=socket.gaierror):
        result = dns_lookup("invalid.domain.that.does.not.exist")
        assert result == "_DNS Lookup Failed"


@pytest.mark.parametrize(
    "ip_address,expected",
    [
        ("192.168.1.1", True),
        ("256.256.256.256", False),
        ("2001:0db8:85a3:0000:0000:8a2e:0370:7334", True),
        ("not_an_ip", False),
        ("192.168.1", False),
        ("", False),
    ],
)
def test_is_valid_ip(ip_address: str, expected: bool) -> None:
    """Test IP validation with various inputs"""
    assert is_valid_ip(ip_address) == expected


def test_is_valid_ip_none_input() -> None:
    """Test IP validation with None input"""
    assert is_valid_ip(None) is False


def test_dns_lookup_not_domain() -> None:
    """Test DNS lookup with an empty domain string"""
    result = dns_lookup("not.a.domain")
    assert result == "_DNS Lookup Failed"
