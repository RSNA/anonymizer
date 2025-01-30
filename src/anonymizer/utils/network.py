"""
This module provides utility functions related to network operations.
"""

import ipaddress
import socket

import ifaddr


def get_local_ip_addresses() -> list[str]:
    """
    Get the list of local IP addresses.

    Returns:
        list: A list of local IP addresses as strings.
    """
    ip_addresses = []
    adapters = ifaddr.get_adapters()
    for adapter in adapters:
        for ip in adapter.ips:
            if isinstance(ip.ip, str) and not ip.ip.startswith("169."):
                ip_addresses.append(ip.ip)
    return ip_addresses


def dns_lookup(domain_name) -> str:
    """
    Performs a DNS lookup for the given domain name.

    Args:
        domain_name (str): The domain name to perform the DNS lookup for.

    Returns:
        str: The IP address associated with the domain name, or "_DNS Lookup Failed" if the lookup fails.
    """
    try:
        return socket.gethostbyname(domain_name)
    except Exception:
        return "_DNS Lookup Failed"


def is_valid_ip(ip_str) -> bool:
    """
    Check if the given IP address is valid.

    Args:
        ip_str (str): The IP address to be checked.

    Returns:
        bool: True if the IP address is valid, False otherwise.
    """
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False
