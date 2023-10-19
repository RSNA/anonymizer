import ifaddr
import socket
import ipaddress


def get_local_ip_addresses():
    ip_addresses = []
    adapters = ifaddr.get_adapters()
    for adapter in adapters:
        for ip in adapter.ips:
            if isinstance(ip.ip, str) and not ip.ip.startswith("169."):
                ip_addresses.append(ip.ip)
    return ip_addresses


def dns_lookup(domain_name) -> str:
    try:
        return socket.gethostbyname(domain_name)
    except:
        return "_(DNS Lookup Failed)"


def is_valid_ip(ip_str):
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False
