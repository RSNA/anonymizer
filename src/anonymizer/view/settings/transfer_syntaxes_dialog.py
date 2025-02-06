import logging
import tkinter as tk
from tkinter import ttk
from typing import Union

import customtkinter as ctk
from customtkinter import ThemeManager

from anonymizer.model.project import ProjectModel
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class TransferSyntaxesDialog(tk.Toplevel):
    """
    A dialog window for selecting transfer syntaxes.

    Args:
        parent: The parent widget.
        transfer_syntaxes: A list of transfer syntaxes.

    Attributes:
        ts_lookup (dict[str, str]): A dictionary mapping transfer syntax UIDs to their descriptions.
        attr_map (dict[str, Tuple[str, int, bool]]): A dictionary mapping attribute names to their display properties.
        root (ctk.CTk): The root widget.
        transfer_syntaxes (list[str]): The list of selected transfer syntaxes.
        _user_input (Union[list, None]): The user-selected transfer syntaxes.
        _tree (ttk.Treeview): The treeview widget for displaying transfer syntaxes.
        _button_frame (ctk.CTkFrame): The frame widget for buttons.
        _select_all_button (ctk.CTkButton): The button for selecting all transfer syntaxes.
        _default_selection_button (ctk.CTkButton): The button for selecting default transfer syntaxes.
        _ok_button (ctk.CTkButton): The button for confirming the selection.

    Methods:
        _create_widgets(): Create the widgets for the dialog.
        _on_item_select(event): Handle the selection of a transfer syntax.
        _select_all_button_pressed(): Handle the press of the "Select All" button.
        _default_selection_button_pressed(): Handle the press of the "Default" button.
        _enter_keypress(event): Handle the press of the Enter key.
        _ok_event(event): Handle the press of the OK button.
        _escape_keypress(event): Handle the press of the Escape key.
        _on_cancel(): Handle the cancellation of the dialog.
        get_input(): Get the user-selected transfer syntaxes.

    """

    # description strings added to pynetdicom.globals.ALL_TRANSFER_SYNTAXES
    ts_lookup: dict[str, str] = {
        "1.2.840.10008.1.2": "Implicit VR Little Endian",
        "1.2.840.10008.1.2.1": "Explicit VR Little Endian",
        "1.2.840.10008.1.2.1.99": "Deflated Explicit VR Little Endian",
        "1.2.840.10008.1.2.2": "Explicit VR Big Endian",
        "1.2.840.10008.1.2.4.50": "JPEG Baseline",
        "1.2.840.10008.1.2.4.51": "JPEG Extended",
        "1.2.840.10008.1.2.4.57": "JPEG Lossless P14",
        "1.2.840.10008.1.2.4.70": "JPEG Lossless",
        "1.2.840.10008.1.2.4.80": "JPEG-LS Lossless",
        "1.2.840.10008.1.2.4.81": "JPEG-LS Lossy",
        "1.2.840.10008.1.2.4.90": "JPEG 2000 Lossless",
        "1.2.840.10008.1.2.4.91": "JPEG 2000",
        "1.2.840.10008.1.2.4.92": "JPEG 2000 Multi-Component Lossless",
        "1.2.840.10008.1.2.4.93": "JPEG 2000 Multi-Component",
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
    ):
        super().__init__(master=parent)
        self.attr_map = {
            "SyntaxName": (_("Transfer Syntax Name"), 35, False),
            "SyntaxUID": (_("Transfer Syntax UID"), 30, False),
        }
        self.root: ctk.CTk = parent.master
        self.transfer_syntaxes = transfer_syntaxes
        self.title(_("Select Transfer Syntaxes"))
        self.resizable(False, True)
        self._user_input: Union[list, None] = None
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)
        self._create_widgets()
        self.wait_visibility()
        self.lift()
        self.grab_set()  # make dialog modal

    def _create_widgets(self):
        logger.info("_create_widgets")
        PAD = 10
        ButtonWidth = 100
        char_width_px = ctk.CTkFont().measure("A")

        self._tree = ttk.Treeview(
            self,
            show="headings",
            style="Treeview",
            columns=list(self.attr_map.keys()),
            selectmode="browse",  # single selection
        )
        # Bind a callback function to item selection
        self._tree.bind("<<TreeviewSelect>>", self._on_item_select)
        selected_bg_color = self.root._apply_appearance_mode(ThemeManager.theme["Treeview"]["selected_bg_color"])
        selected_color = self.root._apply_appearance_mode(ThemeManager.theme["Treeview"]["selected_color"])
        self._tree.tag_configure("green", foreground=selected_color, background=selected_bg_color)

        self._tree.grid(row=0, column=0, columnspan=2, sticky="nswe")
        # Set tree column headers, width and justifications
        for col in self._tree["columns"]:
            self._tree.heading(col, text=self.attr_map[col][0])
            self._tree.column(
                col,
                width=self.attr_map[col][1] * char_width_px,
                anchor="center" if self.attr_map[col][2] else "w",
            )

        # Create a Scrollbar and associate it with the Treeview
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        scrollbar.grid(row=0, column=2, sticky="ns")
        self._tree.configure(yscrollcommand=scrollbar.set)

        for transfer_syntax in self.ts_lookup:
            syntax_name = self.ts_lookup[transfer_syntax]
            tag = ""
            if transfer_syntax in self.transfer_syntaxes:
                tag = "green"
            try:
                self._tree.insert(
                    "",
                    "end",
                    iid=transfer_syntax,
                    values=[syntax_name, transfer_syntax],
                    tags=tag,
                )
            except Exception as e:
                logger.error(f"Exception: {e}")  # _tkinter.TclError: Item {iid} already exists

        self._button_frame = ctk.CTkFrame(self)
        self._button_frame.grid(row=1, column=0, sticky="we")
        self._button_frame.grid_columnconfigure(2, weight=1)

        self._select_all_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("Select All"),
            command=self._select_all_button_pressed,
        )
        self._select_all_button.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="w")

        self._default_selection_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("Default"),
            command=self._default_selection_button_pressed,
        )
        self._default_selection_button.grid(row=0, column=1, padx=PAD, pady=PAD, sticky="w")

        self._ok_button = ctk.CTkButton(self._button_frame, width=100, text=_("Ok"), command=self._ok_event)
        self._ok_button.grid(
            row=0,
            column=2,
            padx=PAD,
            pady=PAD,
            sticky="e",
        )

    def _on_item_select(self, event):
        selected_items = self._tree.selection()
        if len(selected_items) == 0:
            return
        selected_item = selected_items[0]
        self._tree.selection_remove(selected_item)
        if selected_item in self.transfer_syntaxes:
            logger.info(f"REMOVE {selected_item} to transfer_syntaxes")
            self.transfer_syntaxes.remove(selected_item)
            self._tree.item(selected_item, tags="")

        else:
            logger.info(f"ADD {selected_item} to transfer_syntaxes")
            self.transfer_syntaxes.append(selected_item)
            self._tree.item(selected_item, tags="green")

    def _select_all_button_pressed(self):
        logger.info("_select_all_button_pressed")
        self.transfer_syntaxes.clear()
        for item in self._tree.get_children():
            self.transfer_syntaxes.append(item)
            self._tree.item(item, tags="green")

    def _default_selection_button_pressed(self):
        logger.info("_default_selection_button_pressed")
        self.transfer_syntaxes.clear()
        self.transfer_syntaxes = [ts for ts in ProjectModel.default_transfer_syntaxes()]
        for item in self._tree.get_children():
            self._tree.item(item, tags="")
            if item in self.transfer_syntaxes:
                self._tree.item(item, tags="green")

    def _enter_keypress(self, event):
        logger.info("_enter_pressed")
        self._ok_event()

    def _ok_event(self, event=None):
        self._user_input = self.transfer_syntaxes
        self.grab_release()
        self.destroy()

    def _escape_keypress(self, event):
        logger.info("_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def get_input(self):
        self.focus()
        self.master.wait_window(self)
        return self._user_input
