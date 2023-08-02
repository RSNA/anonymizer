import netifaces

# TODO: provide UX and persistence for network timeout
_network_timeout = 5  # seconds


def get_network_timeout():
    return _network_timeout


def get_local_ip_addresses():
    ip_addresses = []
    interfaces = netifaces.interfaces()
    for interface in interfaces:
        addresses = netifaces.ifaddresses(interface)
        if netifaces.AF_INET in addresses:
            for address_info in addresses[netifaces.AF_INET]:
                ip_address = address_info["addr"]
                ip_addresses.append(ip_address)
    return ip_addresses
