import ifaddr


def get_local_ip_addresses():
    ip_addresses = []

    adapters = ifaddr.get_adapters()

    for adapter in adapters:
        print("IPs of network adapter " + adapter.nice_name)
        for ip in adapter.ips:
            print("   %s/%s" % (ip.ip, ip.network_prefix))
            if isinstance(ip.ip, str) and not ip.ip.startswith('169.'):
                ip_addresses.append(ip.ip)

    return ip_addresses
