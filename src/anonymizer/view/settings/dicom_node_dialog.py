"""DICOM node settings: local SCP, or remote Query/Export (DIMSE SCP vs DICOMweb)."""

from __future__ import annotations

import contextlib
import logging
import string
import threading
import tkinter as tk
from dataclasses import dataclass
from queue import Queue
from typing import TYPE_CHECKING, Union

import customtkinter as ctk

from anonymizer.controller.dicom.requests import EchoResponse
from anonymizer.model.project import DICOMNode
from anonymizer.utils.network import dns_lookup, get_local_ip_addresses
from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppToplevel, install_modal_dismiss
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel
from anonymizer.view.common.fonts import default_char_width_px
from anonymizer.view.common.ux_fields import (
    aet_max_chars,
    aet_min_chars,
    int_entry,
    ip_max_chars,
    ip_min_chars,
    ip_port_max,
    ip_port_min,
    str_entry,
)

if TYPE_CHECKING:
    from anonymizer.controller.project import ProjectController

logger = logging.getLogger(__name__)

_PAD = 10

# Idle DICOMweb defaults when mode is SCP (kept on the model for JSON compatibility).
_IDLE_HTTP_PORT = 8042
_IDLE_HTTP_PATH = "/dicom-web"
_WEB_DEFAULT_AET = "WEB"
_HTTPS_DEFAULT_PORT = 443
_HTTP_DEFAULT_PORT = 80


@dataclass(frozen=True)
class RemoteNodeFormValues:
    """Snapshot of remote Query/Export dialog fields."""

    ip: str
    dicomweb: bool
    # Single Port widget value (DIMSE when SCP, HTTP when DICOMweb).
    port: int
    aet: str
    # Last known DIMSE port (restored when switching back to SCP).
    dimse_port: int
    http_path: str
    use_https: bool
    username: str
    password: str


def connection_status_category(error: str | None) -> str:
    """Map a detailed connection failure to a short status category (no host/URL)."""
    text = (error or "").lower()
    if any(s in text for s in ("401", "403", "authentication", "unauthorized", "forbidden")):
        return _("Authentication failed")
    if "timed out" in text or "timeout" in text:
        return _("Connection timed out")
    if "refused" in text:
        return _("Connection refused")
    if any(s in text for s in ("name or service not known", "nodename nor servname", "getaddrinfo", "name resolution")):
        return _("Host not found")
    return _("Connection error")


def apply_https_port_default(use_https: bool, port: int) -> int:
    """Industry-standard port nudge when toggling HTTPS; leave custom ports alone."""
    if use_https and port in (_HTTP_DEFAULT_PORT, _IDLE_HTTP_PORT):
        return _HTTPS_DEFAULT_PORT
    if not use_https and port == _HTTPS_DEFAULT_PORT:
        return _HTTP_DEFAULT_PORT
    return port


def dicomweb_fresh_defaults(*, previous_http_port: int) -> tuple[int, bool, str]:
    """Defaults when first selecting DICOMweb from SCP (HTTPS-first)."""
    if previous_http_port == _IDLE_HTTP_PORT:
        return _HTTPS_DEFAULT_PORT, True, _IDLE_HTTP_PATH
    return previous_http_port, True, _IDLE_HTTP_PATH


def remote_node_from_form(values: RemoteNodeFormValues) -> DICOMNode:
    """Map dialog fields to a DICOMNode (OK and Test Connection share this)."""
    ip = (values.ip or "").strip()
    if values.dicomweb:
        path = (values.http_path or "").strip() or _IDLE_HTTP_PATH
        if not path.startswith("/"):
            path = "/" + path
        user = (values.username or "").strip()
        pwd = values.password or ""
        aet = (values.aet or "").strip() or _WEB_DEFAULT_AET
        return DICOMNode(
            ip,
            int(values.dimse_port),
            aet,
            False,
            dicomweb=True,
            http_port=int(values.port),
            http_path=path,
            use_https=bool(values.use_https),
            username=user,
            password=pwd,
        )
    return DICOMNode(
        ip,
        int(values.port),
        (values.aet or "").strip(),
        False,
        dicomweb=False,
        http_port=_IDLE_HTTP_PORT,
        http_path=_IDLE_HTTP_PATH,
        use_https=False,
        username="",
        password="",
    )


def validate_remote_form(values: RemoteNodeFormValues) -> str | None:
    """Return an error message, or None if the form is OK to save/test."""
    if not (values.ip or "").strip():
        return _("IP Address is required")
    if values.dicomweb:
        path = (values.http_path or "").strip()
        if not path:
            return _("Path is required when DICOMweb is enabled")
        user = (values.username or "").strip()
        pwd = values.password or ""
        if bool(user) != bool(pwd):
            return _("Username and password must both be set or both empty")
    else:
        if not (values.aet or "").strip():
            return _("AE Title is required")
    return None


class DICOMNodeDialog(AppToplevel):
    """Configure a local SCP or a remote Query/Export node (DIMSE or DICOMweb)."""

    def __init__(
        self,
        parent,
        address: DICOMNode,
        title: str | None = None,
        controller: ProjectController | None = None,
    ):
        super().__init__(master=parent)
        self.address = address
        self._controller = controller
        if title is None:
            title = _("DICOM Node")
        self.title(title)
        self.resizable(False, False)
        self._user_input: Union[DICOMNode, None] = None
        self._testing = False
        # Remember DIMSE port when switching to DICOMweb so SCP mode can restore it.
        self._dimse_port = int(address.port)
        self._http_port = int(address.http_port)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)
        self._create_widgets()
        self.wait_visibility()
        install_modal_dismiss(self, self._on_cancel)
        self.grab_set()

    def _create_widgets(self) -> None:
        logger.debug("_create_widgets")
        char_width_px = default_char_width_px()
        logger.debug(f"Font Character Width in pixels: ±{char_width_px}")

        self._frame = ctk.CTkFrame(self)
        self._frame.grid(row=0, column=0, padx=_PAD, pady=_PAD, sticky="nswe")
        self.columnconfigure(1, weight=1)

        if self.address.local:
            self._create_local_widgets()
        else:
            self._create_remote_widgets()

    def _create_local_widgets(self) -> None:
        """Local Anonymizer SCP — address / DIMSE port / AET only."""
        row = 0
        local_ips = get_local_ip_addresses()
        if local_ips:
            logger.info(f"Local IP addresses: {local_ips}")
        else:
            local_ips = [_("No local IP addresses found.")]
            logger.error(local_ips[0])

        all_ips = "0.0.0.0"
        if all_ips not in local_ips:
            local_ips.append(all_ips)

        ctk.CTkLabel(self._frame, text=_("Address") + ":").grid(
            row=row, column=0, padx=_PAD, pady=(_PAD, 0), sticky="nw"
        )
        self.ip_var = ctk.StringVar(self._frame, value=self.address.ip)
        local_ips_optionmenu = ctk.CTkOptionMenu(
            self._frame,
            dynamic_resizing=False,
            values=sorted(local_ips),
            variable=self.ip_var,
        )
        local_ips_optionmenu.grid(row=row, column=1, padx=_PAD, pady=(_PAD, 0), sticky="nw")
        local_ips_optionmenu.focus_set()
        row += 1

        self.port_var = int_entry(
            view=self._frame,
            label=_("Port") + ":",
            initial_value=self.address.port,
            min=ip_port_min,
            max=ip_port_max,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=_PAD,
            sticky="nw",
        )
        row += 1

        self.aet_var = str_entry(
            view=self._frame,
            label=_("AE Title") + ":",
            initial_value=self.address.aet,
            min_chars=aet_min_chars,
            max_chars=aet_max_chars,
            charset=string.ascii_letters + string.digits + " !#$%&()#*+-.,:;_^@?~|",
            tooltipmsg=None,
            row=row,
            col=0,
            pad=_PAD,
            sticky="nw",
        )
        row += 1

        self._ok_button = ctk.CTkButton(self._frame, width=100, text=_("Ok"), command=self._ok_event)
        self._ok_button.grid(row=row, column=1, padx=_PAD, pady=_PAD, sticky="e")

    def _create_remote_widgets(self) -> None:
        """Query/Export: exclusive SCP vs DICOMweb, single Port, Test Connection."""
        row = 0

        # --- Server type (first, mutually exclusive) ---
        ctk.CTkLabel(self._frame, text=_("Server type") + ":").grid(
            row=row, column=0, padx=_PAD, pady=(_PAD, 0), sticky="nw"
        )
        type_host = ctk.CTkFrame(self._frame, fg_color="transparent")
        type_host.grid(row=row, column=1, padx=_PAD, pady=(_PAD, 0), sticky="nw")
        self._server_type_var = tk.StringVar(
            value="dicomweb" if self.address.dicomweb else "scp"
        )
        ctk.CTkRadioButton(
            type_host,
            text=_("DICOM SCP"),
            variable=self._server_type_var,
            value="scp",
            command=self._sync_mode_ui,
        ).pack(side="left", padx=(0, _PAD))
        ctk.CTkRadioButton(
            type_host,
            text=_("DICOMweb"),
            variable=self._server_type_var,
            value="dicomweb",
            command=self._sync_mode_ui,
        ).pack(side="left")
        row += 1

        # --- Shared host ---
        self.domain_name_var = str_entry(
            view=self._frame,
            label=_("Domain Name") + ":",
            initial_value="",
            min_chars=3,
            max_chars=255,
            width_chars=40,
            charset=string.digits + ".-" + string.ascii_lowercase + string.ascii_uppercase,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=_PAD,
            sticky="nw",
            focus_set=True,
        )
        row += 1

        self._dns_lookup_button = ctk.CTkButton(
            self._frame, width=100, text=_("DNS Lookup"), command=self._dns_lookup_event
        )
        self._dns_lookup_button.grid(row=row, column=1, padx=_PAD, pady=_PAD, sticky="w")
        row += 1

        self.ip_var = str_entry(
            view=self._frame,
            label=_("IP Address") + ":",
            initial_value=self.address.ip,
            min_chars=ip_min_chars,
            max_chars=ip_max_chars,
            charset=string.digits + ".",
            tooltipmsg=None,
            row=row,
            col=0,
            pad=_PAD,
            sticky="nw",
        )
        row += 1

        # Single Port — meaning depends on mode (DIMSE vs HTTP).
        initial_port = (
            int(self.address.http_port) if self.address.dicomweb else int(self.address.port)
        )
        self.port_var = int_entry(
            view=self._frame,
            label=_("Port") + ":",
            initial_value=initial_port,
            min=ip_port_min,
            max=ip_port_max,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=_PAD,
            sticky="nw",
        )
        row += 1

        # SCP-only: AE Title on the main grid so columns align with IP/Port.
        self._aet_row = row
        self.aet_var = str_entry(
            view=self._frame,
            label=_("AE Title") + ":",
            initial_value=self.address.aet,
            min_chars=aet_min_chars,
            max_chars=aet_max_chars,
            charset=string.ascii_letters + string.digits + " !#$%&()#*+-.,:;_^@?~|",
            tooltipmsg=None,
            row=row,
            col=0,
            pad=_PAD,
            sticky="nw",
        )
        # Keep refs — grid_slaves() omits widgets after grid_remove().
        self._aet_widgets = list(self._frame.grid_slaves(row=row))
        row += 1

        # DICOMweb-only rows (same main grid for column alignment).
        self._web_widgets: list[tk.Misc] = []

        ctk.CTkLabel(self._frame, text=_("Use HTTPS") + ":").grid(
            row=row, column=0, padx=_PAD, pady=(_PAD, 0), sticky="nw"
        )
        initial_https = bool(self.address.use_https) if self.address.dicomweb else True
        self._use_https_var = tk.BooleanVar(value=initial_https)
        ctk.CTkCheckBox(
            self._frame,
            text="",
            variable=self._use_https_var,
            command=self._on_https_toggle,
        ).grid(row=row, column=1, padx=_PAD, pady=(_PAD, 0), sticky="nw")
        self._web_widgets.extend(self._frame.grid_slaves(row=row))
        row += 1

        self.http_path_var = str_entry(
            view=self._frame,
            label=_("Path") + ":",
            initial_value=self.address.http_path or "/dicom-web",
            min_chars=1,
            max_chars=255,
            width_chars=40,
            charset=string.ascii_letters + string.digits + "/-_~.%",
            tooltipmsg=None,
            row=row,
            col=0,
            pad=_PAD,
            sticky="nw",
        )
        self._web_widgets.extend(self._frame.grid_slaves(row=row))
        row += 1

        self.username_var = str_entry(
            view=self._frame,
            label=_("Username") + ":",
            initial_value=self.address.username or "",
            min_chars=0,
            max_chars=128,
            width_chars=40,
            charset=string.printable,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=_PAD,
            sticky="nw",
        )
        self._web_widgets.extend(self._frame.grid_slaves(row=row))
        row += 1

        self.password_var = str_entry(
            view=self._frame,
            label=_("Password") + ":",
            initial_value=self.address.password or "",
            min_chars=0,
            max_chars=128,
            width_chars=40,
            charset=string.printable,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=_PAD,
            sticky="nw",
            password=True,
        )
        self._web_widgets.extend(self._frame.grid_slaves(row=row))
        row += 1

        # Test Connection in the edit column; status + Ok share the full footer row.
        self._test_button = ctk.CTkButton(
            self._frame, width=140, text=_("Test Connection"), command=self._test_connection
        )
        self._test_button.grid(row=row, column=1, padx=_PAD, pady=(_PAD, 0), sticky="w")
        if self._controller is None:
            self._test_button.configure(state="disabled")
        row += 1

        footer = ctk.CTkFrame(self._frame, fg_color="transparent")
        footer.grid(row=row, column=0, columnspan=2, padx=_PAD, pady=_PAD, sticky="ew")
        footer.columnconfigure(0, weight=1)

        self._status_label = ctk.CTkLabel(footer, text="", anchor="w", justify="left")
        self._status_label.grid(row=0, column=0, sticky="w")
        if self._controller is None:
            self._set_status(_("Open settings from a project to test the connection"))

        self._ok_button = ctk.CTkButton(footer, width=100, text=_("Ok"), command=self._ok_event)
        self._ok_button.grid(row=0, column=1, sticky="e", padx=(_PAD, 0))

        self._sync_mode_ui(initial=True)

    @staticmethod
    def _set_widgets_visible(widgets: list[tk.Misc], visible: bool) -> None:
        for widget in widgets:
            if visible:
                widget.grid()
            else:
                widget.grid_remove()

    def _is_dicomweb(self) -> bool:
        return getattr(self, "_server_type_var", None) is not None and self._server_type_var.get() == "dicomweb"

    def _sync_mode_ui(self, initial: bool = False) -> None:
        if self.address.local:
            return
        web = self._is_dicomweb()
        if web:
            if not initial:
                with contextlib.suppress(Exception):
                    self._dimse_port = int(self.port_var.get())
                port, https, path = dicomweb_fresh_defaults(previous_http_port=self._http_port)
                self.port_var.set(port)
                self._use_https_var.set(https)
                if not (self.http_path_var.get() or "").strip():
                    self.http_path_var.set(path)
            self._set_widgets_visible(self._aet_widgets, False)
            self._set_widgets_visible(self._web_widgets, True)
        else:
            if not initial:
                with contextlib.suppress(Exception):
                    self._http_port = int(self.port_var.get())
                self.port_var.set(int(self._dimse_port))
            self._set_widgets_visible(self._web_widgets, False)
            self._set_widgets_visible(self._aet_widgets, True)
            self._set_status("")
        self.update_idletasks()

    def _on_https_toggle(self) -> None:
        if not self._is_dicomweb():
            return
        try:
            current = int(self.port_var.get())
        except Exception:
            return
        self.port_var.set(apply_https_port_default(bool(self._use_https_var.get()), current))

    def _form_values(self) -> RemoteNodeFormValues:
        web = self._is_dicomweb()
        try:
            port = int(self.port_var.get())
        except Exception:
            port = self._http_port if web else self._dimse_port
        return RemoteNodeFormValues(
            ip=self.ip_var.get(),
            dicomweb=web,
            port=port,
            aet=self.aet_var.get() if hasattr(self, "aet_var") else self.address.aet,
            dimse_port=self._dimse_port,
            http_path=self.http_path_var.get() if hasattr(self, "http_path_var") else "/dicom-web",
            use_https=bool(self._use_https_var.get()) if hasattr(self, "_use_https_var") else False,
            username=self.username_var.get() if hasattr(self, "username_var") else "",
            password=self.password_var.get() if hasattr(self, "password_var") else "",
        )

    def _dialog_alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _set_status(self, message: str, *, error: bool = False) -> None:
        """Update status text only — CTkLabel text_color flips can segfault on redraw."""
        _ = error  # kept for call-site clarity; color stays theme default
        label = getattr(self, "_status_label", None)
        if label is None or not self._dialog_alive():
            return
        try:
            label.configure(text=(message or "").strip())
        except tk.TclError:
            return

    def _dns_lookup_event(self, event=None) -> None:
        self.ip_var.set(dns_lookup(self.domain_name_var.get()))

    def _enter_keypress(self, event) -> None:
        logger.info("_enter_pressed")
        self._ok_event()

    def _ok_event(self, event=None) -> None:
        if self.address.local:
            self._user_input = DICOMNode(
                self.ip_var.get(),
                int(self.port_var.get()),
                self.aet_var.get(),
                True,
            )
            teardown_ctk_toplevel(self, parent=self.master)
            return

        values = self._form_values()
        err = validate_remote_form(values)
        if err:
            self._set_status(err, error=True)
            return
        self._user_input = remote_node_from_form(values)
        teardown_ctk_toplevel(self, parent=self.master)

    def _test_connection(self) -> None:
        """C-ECHO (+ Study-Root C-GET/C-MOVE probe for DIMSE) or DICOMweb QIDO probe."""
        if self.address.local or self._testing:
            return
        if self._controller is None:
            self._set_status(_("Open settings from a project to test the connection"), error=True)
            return
        values = self._form_values()
        err = validate_remote_form(values)
        if err:
            self._set_status(err, error=True)
            return
        node = remote_node_from_form(values)
        self._testing = True
        self._test_was_web = bool(node.dicomweb)
        self._test_ux_Q: Queue[EchoResponse] = Queue()
        self._test_button.configure(state="disabled")
        self._set_status(_("Testing connection…"))

        def worker() -> None:
            try:
                if node.dicomweb:
                    from anonymizer.controller.dicom import dicomweb as dicomweb_api

                    ok, message = dicomweb_api.probe_connection(
                        node, self._controller.model.network_timeouts
                    )
                    self._test_ux_Q.put(
                        EchoResponse(success=ok, error=None if ok else message)
                    )
                    return

                if not self._controller.echo(node):
                    self._test_ux_Q.put(
                        EchoResponse(success=False, error=_("Connection error"))
                    )
                    return

                get_ok, move_ok = self._controller.probe_study_root_qr_support(node)
                get_txt = _("C-GET accepted") if get_ok else _("C-GET not accepted")
                move_txt = _("C-MOVE accepted") if move_ok else _("C-MOVE not accepted")
                detail = f"{_('Connected')} — {get_txt}, {move_txt}"
                logger.info(
                    "Test Connection OK: C-GET=%s C-MOVE=%s node=%s",
                    get_ok,
                    move_ok,
                    node,
                )
                # EchoResponse.error carries success detail for the status line.
                self._test_ux_Q.put(EchoResponse(success=True, error=detail))
            except Exception as e:
                logger.exception("Test Connection failed")
                self._test_ux_Q.put(EchoResponse(success=False, error=str(e)))

        threading.Thread(target=worker, name="NODE-TEST", daemon=True).start()
        self.after(200, self._poll_test_connection)

    def _poll_test_connection(self) -> None:
        """Poll echo/probe queue on the UI thread (same as Dashboard._wait_for_scp_echo)."""
        if not self._dialog_alive():
            return
        ux_Q = getattr(self, "_test_ux_Q", None)
        if ux_Q is None:
            return
        if ux_Q.empty():
            self.after(200, self._poll_test_connection)
            return

        er: EchoResponse = ux_Q.get()
        self._testing = False
        if self._controller is not None:
            try:
                self._test_button.configure(state="normal")
            except tk.TclError:
                return
        if er.success:
            if er.error:
                message = er.error
            elif getattr(self, "_test_was_web", False):
                message = _("DICOMweb connection successful")
            else:
                message = _("C-ECHO successful")
        else:
            if er.error:
                logger.info("Test Connection failed: %s", er.error)
            message = connection_status_category(er.error)
        self._set_status(message, error=not er.success)

    def _escape_keypress(self, event) -> None:
        logger.info("_escape_pressed")
        self._on_cancel()

    def _on_cancel(self) -> None:
        teardown_ctk_toplevel(self, parent=self.master)

    def get_input(self):
        self.focus()
        self.master.wait_window(self)
        return self._user_input
