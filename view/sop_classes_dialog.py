import select
from typing import Dict, KeysView, Self, Union
import customtkinter as ctk
from tkinter import ttk
import logging
from pynetdicom.sop_class import _STORAGE_CLASSES
from utils.translate import _, insert_spaces_between_cases, insert_space_after_codes

logger = logging.getLogger(__name__)


class SOPClassesDialog(ctk.CTkToplevel):
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
        "ClassName": (_("Class Name"), 60, False),
        "ClassID": (_("Class UID"), 30, False),
    }

    def __init__(
        self,
        sop_classes: list[str],
        title: str = _("Select Storage Classes"),
    ):
        super().__init__()
        self.sop_classes = sop_classes
        self.title(title)
        self.attributes("-topmost", True)  # stay on top
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.geometry("750x600")
        self.resizable(True, True)
        self.grab_set()  # make dialog modal
        self._user_input: Union[list, None] = None
        self.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self._create_widgets()

    def on_item_select(self, event):
        selected_items = self.tree.selection()
        if len(selected_items) == 0:
            return
        selected_item = selected_items[0]
        self.tree.selection_remove(selected_item)
        if selected_item in self.sop_classes:
            logger.info(f"REMOVE {selected_item} to sop_classes")
            self.sop_classes.remove(selected_item)
            self.tree.item(selected_item, tags="")

        else:
            logger.info(f"ADD {selected_item} from sop_classes")
            self.sop_classes.append(selected_item)
            self.tree.item(selected_item, tags="green")

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

        for class_name in _STORAGE_CLASSES:
            class_id = _STORAGE_CLASSES[class_name]
            class_name = insert_space_after_codes(
                insert_spaces_between_cases(class_name), self.storage_codes
            ).replace("XRay", "X-Ray")
            tag = ""
            if class_id in self.sop_classes:
                tag = "green"
            try:
                self.tree.insert(
                    "", "end", iid=class_id, values=[class_name, class_id], tags=tag
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

    def _ok_event(self, event=None):
        self._user_input = self.sop_classes
        self.grab_release()
        self.destroy()

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def get_input(self):
        self.master.wait_window(self)
        return self._user_input
