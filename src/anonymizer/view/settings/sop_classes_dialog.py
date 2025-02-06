import logging
import tkinter as tk
from tkinter import ttk
from typing import Union

import customtkinter as ctk
from customtkinter import ThemeManager
from pynetdicom.sop_class import _STORAGE_CLASSES

from anonymizer.utils.modalities import get_modalities
from anonymizer.utils.translate import (
    _,
    insert_space_after_codes,
    insert_spaces_between_cases,
)

logger = logging.getLogger(__name__)


class SOPClassesDialog(tk.Toplevel):
    """
    A dialog window for selecting storage classes.

    Args:
        parent (tk.Tk): The parent window.
        sop_classes (list[str]): The list of selected storage classes.
        modalities (list[str]): The list of modalities.

    Attributes:
        storage_codes (list[str]): The list of storage codes.
        sc_lookup (dict): A dictionary mapping storage class values to keys.
        attr_map (dict): A dictionary mapping attribute names to their display names, width, and justification.
        root (ctk.CTk): The root window.
        sop_classes (list[str]): The list of selected storage classes.
        modalities (list[str]): The list of modalities.
        _user_input (Union[list, None]): The user input (selected storage classes).
        _tree (ttk.Treeview): The treeview widget for displaying storage classes.
        _button_frame (ctk.CTkFrame): The frame for buttons.
        _select_all_button (ctk.CTkButton): The button for selecting all storage classes.
        _from_modalities_selection_button (ctk.CTkButton): The button for selecting storage classes from modalities.
        _ok_button (ctk.CTkButton): The button for confirming the selection.

    Methods:
        _create_widgets(): Create the widgets for the dialog.
        _on_item_select(event): Callback function for item selection in the treeview.
        _select_all_button_pressed(): Event handler for the "Select All" button.
        _from_modalities_selection_button_pressed(): Event handler for the "From Modalities" button.
        _enter_keypress(event): Event handler for the Enter key press.
        _ok_event(event): Event handler for the Ok button.
        _escape_keypress(event): Event handler for the Escape key press.
        _on_cancel(): Event handler for canceling the dialog.
        get_input(): Get the user input (selected storage classes).

    """

    storage_codes = [
        "DX",
        "CR",
        "MR",
        "CT",
        "SC",
        "MPR",
        "PET",
        "US",
        "MG",
        "NM",
        "PT",
        "RT",
        "ECG",
        "VL",
        "SR",
        "PDF",
        "CDA",
        "STL",
        "OBJ",
        "MTL",
        "CAD",
        "3D",
        "XA",
        "XRF",
    ]

    sc_lookup = {value: key for key, value in _STORAGE_CLASSES.items()}

    def __init__(self, parent, sop_classes: list[str], modalities: list[str]):
        super().__init__(master=parent)
        self.attr_map = {
            "ClassName": (_("Class Name"), 45, False),
            "ClassID": (_("Class UID"), 30, False),
        }
        self.root: ctk.CTk = parent.master
        self.sop_classes = sop_classes
        self.modalities = modalities
        self.title(_("Select Storage Classes"))
        self.resizable(True, True)
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

        for class_id in _STORAGE_CLASSES.values():
            class_name = self.sc_lookup[class_id]
            class_name = insert_space_after_codes(insert_spaces_between_cases(class_name), self.storage_codes).replace(
                "XRay", "X-Ray"
            )
            tag = ""
            if class_id in self.sop_classes:
                tag = "green"
            try:
                self._tree.insert("", "end", iid=class_id, values=[class_name, class_id], tags=tag)
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

        self._from_modalities_selection_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("From Modalities"),
            command=self._from_modalities_selection_button_pressed,
        )
        self._from_modalities_selection_button.grid(row=0, column=1, padx=PAD, pady=PAD, sticky="w")
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
        if selected_item in self.sop_classes:
            logger.info(f"REMOVE {selected_item} from sop_classes")
            self.sop_classes.remove(selected_item)
            self._tree.item(selected_item, tags="")
        else:
            logger.info(f"ADD {selected_item} to sop_classes")
            self.sop_classes.append(selected_item)
            self._tree.item(selected_item, tags="green")

    def _select_all_button_pressed(self):
        logger.info("_select_all_button_pressed")
        self.sop_classes.clear()
        for item in self._tree.get_children():
            self.sop_classes.append(item)
            self._tree.item(item, tags="green")

    def _from_modalities_selection_button_pressed(self):
        logger.info("_from_modalities_selection_button_pressed")
        self.sop_classes.clear()
        for modality in self.modalities:
            self.sop_classes += get_modalities()[modality][1]
        for item in self._tree.get_children():
            self._tree.item(item, tags="")
            if item in self.sop_classes:
                self._tree.item(item, tags="green")

    def _enter_keypress(self, event):
        logger.info("_enter_pressed")
        self._ok_event()

    def _ok_event(self, event=None):
        self._user_input = self.sop_classes
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
