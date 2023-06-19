import tkinter as tk
import netifaces
import customtkinter as ctk
import logging

logger = logging.getLogger(__name__)
DICOM_STORAGE_SCP = _("DICOM Storage SCP:")
PORT = _("Port:")
AET = _("AET:")
ERR_NO_LOCAL_IP_ADDR = _("No local IP addresses found.")
DEFAULT_IP_PORT = 104
DEFAULT_AET = "ANONSTORE"
PAD = 10


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


def create_view(view: ctk.CTkFrame):
    logger.info(f"Creating Configure DICOM Storage SCP View")
    # view.grid_rowconfigure(0, weight=1)

    local_ips = get_local_ip_addresses()
    if local_ips:
        logger.info(f"Local IP addresses: {local_ips}")
    else:
        local_ips = [ERR_NO_LOCAL_IP_ADDR]
        logger.error(local_ips[0])

    dicom_scp_label = ctk.CTkLabel(view, text=DICOM_STORAGE_SCP)
    dicom_scp_label.grid(row=0, column=0, pady=(PAD, 0), sticky="nw")

    local_ips_optionmenu = ctk.CTkOptionMenu(
        view,
        dynamic_resizing=False,
        values=local_ips,
    )
    local_ips_optionmenu.grid(row=0, column=1, pady=(PAD, 0), padx=PAD, sticky="nw")

    port_label = ctk.CTkLabel(view, text=PORT)
    port_label.grid(row=0, column=2, pady=(PAD, 0), sticky="nw")
    port_stringvar = tk.StringVar(view, str(DEFAULT_IP_PORT))
    port_entry = ctk.CTkEntry(view, width=40, textvariable=port_stringvar)
    port_entry.grid(row=0, column=3, pady=(PAD, 0), padx=PAD, sticky="nw")

    aet_label = ctk.CTkLabel(view, text=AET)
    aet_label.grid(row=0, column=4, pady=(PAD, 0), sticky="nw")
    aet_stringvar = tk.StringVar(view, DEFAULT_AET)
    aet_entry = ctk.CTkEntry(view, width=120, textvariable=aet_stringvar)
    aet_entry.grid(row=0, column=5, pady=(PAD, 0), padx=PAD, sticky="nw")
