"""
This module provides utility functions related to network operations.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import ssl

import ifaddr

logger = logging.getLogger(__name__)


def ensure_ssl_certifi() -> str:
    """
    Point Python's default HTTPS context at certifi's CA bundle.

    EasyOCR downloads models with ``urllib.request.urlretrieve``, which uses the
    default SSL context. On some Windows Python installs that trust store is
    incomplete and raises ``SSLCertVerificationError``. Certifi ships a Mozilla
    CA bundle that works reliably across platforms.
    """
    import certifi

    cafile = certifi.where()
    os.environ["SSL_CERT_FILE"] = cafile
    os.environ["REQUESTS_CA_BUNDLE"] = cafile

    def _https_context() -> ssl.SSLContext:
        return ssl.create_default_context(cafile=cafile)

    ssl._create_default_https_context = _https_context  # type: ignore[assignment]
    logger.debug("SSL default HTTPS context uses certifi CA bundle: %s", cafile)
    return cafile


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
