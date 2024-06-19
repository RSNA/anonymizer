from typing import Union
import tkinter as tk
import customtkinter as ctk
from tkinter import ttk
import logging
from pynetdicom.sop_class import _STORAGE_CLASSES
from utils.translate import _, insert_spaces_between_cases, insert_space_after_codes
from utils.modalities import MODALITIES
from model.project import ProjectModel

logger = logging.getLogger(__name__)


class SOPClassesDialog(tk.Toplevel):
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
    attr_map = {
        "ClassName": (_("Class Name"), 45, False),
        "ClassID": (_("Class UID"), 30, False),
    }
    sc_lookup = {value: key for key, value in _STORAGE_CLASSES.items()}

    def __init__(
        self,
        parent,
        sop_classes: list[str],
        modalities: list[str],
        title: str = _("Select Storage Classes"),
    ):
        super().__init__(master=parent)
        self.sop_classes = sop_classes
        self.modalities = modalities
        self.title(title)
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
        logger.info(f"_create_widgets")
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
        self._tree.tag_configure("green", background="limegreen")

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
            self.sop_classes += MODALITIES[modality][1]
        for item in self._tree.get_children():
            self._tree.item(item, tags="")
            if item in self.sop_classes:
                self._tree.item(item, tags="green")

    def _enter_keypress(self, event):
        logger.info(f"_enter_pressed")
        self._ok_event()

    def _ok_event(self, event=None):
        self._user_input = self.sop_classes
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
