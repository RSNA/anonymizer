from typing import Union
import tkinter as tk
import customtkinter as ctk
from tkinter import ttk
import logging
from utils.translate import _

logger = logging.getLogger(__name__)

class TransferSyntaxesDialog(tk.Toplevel):
#class TransferSyntaxesDialog(ctk.CTkToplevel):
    attr_map = {
        "SyntaxName": (_("Transfer Syntax Name"), 35, False),
        "SyntaxUID": (_("Transfer Syntax UID"), 30, False),
    }
    # description strings added to pynetdicom.globals.ALL_TRANSFER_SYNTAXES
    ts_lookup = {
        "1.2.840.10008.1.2": "Implicit VR Little Endian",
        "1.2.840.10008.1.2.1": "Explicit VR Little Endian",
        "1.2.840.10008.1.2.1.99": "Deflated Explicit VR Little Endian",
        "1.2.840.10008.1.2.2": "Explicit VR Big Endian",
        # "1.2.840.10008.1.2.4.50": "JPEG Baseline",
        # "1.2.840.10008.1.2.4.51": "JPEG Extended",
        # "1.2.840.10008.1.2.4.57": "JPEG Lossless P14",
        # "1.2.840.10008.1.2.4.70": "JPEG Lossless",
        # "1.2.840.10008.1.2.4.80": "JPEG-LS Lossless",
        # "1.2.840.10008.1.2.4.81": "JPEG-LS Lossy",
        # "1.2.840.10008.1.2.4.90": "JPEG 2000 Lossless",
        # "1.2.840.10008.1.2.4.91": "JPEG 2000",
        # "1.2.840.10008.1.2.4.92": "JPEG 2000 Multi-Component Lossless",
        # "1.2.840.10008.1.2.4.93": "JPEG 2000 Multi-Component",
        # "1.2.840.10008.1.2.4.94": "JPIP Referenced",
        # "1.2.840.10008.1.2.4.95": "JPIP Referenced Deflate",
        # "1.2.840.10008.1.2.4.100": "MPEG2 Main Profile / Main Level",
        # "1.2.840.10008.1.2.4.101": "MPEG2 Main Profile / High Level",
        # "1.2.840.10008.1.2.4.102": "MPEG-4 AVC/H.264 High Profile / Level 4.1",
        # "1.2.840.10008.1.2.4.103": "MPEG-4 AVC/H.264 BD-compatible High Profile",
        # "1.2.840.10008.1.2.4.104": "MPEG-4 AVC/H.264 High Profile For 2D Video",
        # "1.2.840.10008.1.2.4.105": "MPEG-4 AVC/H.264 High Profile For 3D Video",
        # "1.2.840.10008.1.2.4.106": "MPEG-4 AVC/H.264 Stereo High Profile",
        # "1.2.840.10008.1.2.4.107": "HEVC/H.265 Main Profile / Level 5.1",
        # "1.2.840.10008.1.2.4.108": "HEVC/H.265 Main 10 Profile / Level 5.1",
        # "1.2.840.10008.1.2.5": "RLE Lossless",
    }

    def __init__(
        self,
        parent,
        transfer_syntaxes: list[str],
        title: str = _("Select Transfer Syntaxes"),
    ):
        super().__init__(master=parent)
        self.transfer_syntaxes = transfer_syntaxes
        self.title(title)
        self.geometry("600x200")  # 550")
        self.resizable(False, False)
        self.grab_set()  # make dialog modal
        self._user_input: Union[list, None] = None
        self.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)
        self._create_widgets()

    def _create_widgets(self):
        logger.info(f"_create_widgets")
        PAD = 10
        char_width_px = ctk.CTkFont().measure("A")

        self.tree = ttk.Treeview(
            self,
            show="headings",
            style="Treeview",
            columns=list(self.attr_map.keys()),
            selectmode="browse",  # single selection
        )
        # Bind a callback function to item selection
        self.tree.bind("<<TreeviewSelect>>", self.on_item_select)
        self.tree.tag_configure("green", background="limegreen")

        self.tree.grid(row=0, column=0, columnspan=2, sticky="nswe")
        # Set tree column headers, width and justifications
        for col in self.tree["columns"]:
            self.tree.heading(col, text=self.attr_map[col][0])
            self.tree.column(
                col,
                width=self.attr_map[col][1] * char_width_px,
                anchor="center" if self.attr_map[col][2] else "w",
            )

        # Create a Scrollbar and associate it with the Treeview
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=2, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        for transfer_syntax in self.ts_lookup:
            syntax_name = self.ts_lookup[transfer_syntax]
            tag = ""
            if transfer_syntax in self.transfer_syntaxes:
                tag = "green"
            try:
                self.tree.insert(
                    "",
                    "end",
                    iid=transfer_syntax,
                    values=[syntax_name, transfer_syntax],
                    tags=tag,
                )
            except Exception as e:
                logger.error(
                    f"Exception: {e}"
                )  # _tkinter.TclError: Item {iid} already exists

        self._ok_button = ctk.CTkButton(
            self, width=100, text=_("Ok"), command=self._ok_event
        )
        self._ok_button.grid(
            row=1,
            column=1,
            padx=PAD,
            pady=PAD,
            sticky="e",
        )

    def on_item_select(self, event):
        selected_items = self.tree.selection()
        if len(selected_items) == 0:
            return
        selected_item = selected_items[0]
        self.tree.selection_remove(selected_item)
        if selected_item in self.transfer_syntaxes:
            logger.info(f"REMOVE {selected_item} to transfer_syntaxes")
            self.transfer_syntaxes.remove(selected_item)
            self.tree.item(selected_item, tags="")

        else:
            logger.info(f"ADD {selected_item} to transfer_syntaxes")
            self.transfer_syntaxes.append(selected_item)
            self.tree.item(selected_item, tags="green")

    def _enter_keypress(self, event):
        logger.info(f"_enter_pressed")
        self._ok_event()

    def _ok_event(self, event=None):
        self._user_input = self.transfer_syntaxes
        self.grab_release()
        self.destroy()

    def _escape_keypress(self, event):
        logger.info(f"_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def get_input(self):
        self.focus()
        self.master.wait_window(self)
        return self._user_input
