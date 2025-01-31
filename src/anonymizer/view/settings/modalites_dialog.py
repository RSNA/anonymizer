import logging
import tkinter as tk
from tkinter import ttk
from typing import Union

import customtkinter as ctk
from customtkinter import ThemeManager

from anonymizer.model.project import ProjectModel
from anonymizer.utils.modalities import get_modalities
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class ModalitiesDialog(tk.Toplevel):
    """
    A dialog window for selecting modalities.

    Args:
        parent (tk.Tk): The parent window.
        modalities (list[str]): The list of modalities.

    Attributes:
        attr_map (dict): A dictionary mapping attribute names to their display names, width, and justification.
        root (ctk.CTk): The root window.
        modalities (list[str]): The list of modalities.
        _user_input (Union[list, None]): The user-selected modalities.
        _tree (ttk.Treeview): The treeview widget for displaying modalities.
        _button_frame (ctk.CTkFrame): The frame for buttons.
        _select_all_button (ctk.CTkButton): The button for selecting all modalities.
        _default_selection_button (ctk.CTkButton): The button for selecting default modalities.
        _ok_button (ctk.CTkButton): The button for confirming the selection.

    Methods:
        _create_widgets(): Create the widgets for the dialog.
        on_item_select(event): Callback function for item selection in the treeview.
        _default_selection_button_pressed(): Event handler for the default selection button.
        _select_all_button_pressed(): Event handler for the select all button.
        _enter_keypress(event): Event handler for the Enter key press.
        _ok_event(event): Event handler for the OK button press.
        _escape_keypress(event): Event handler for the Escape key press.
        _on_cancel(): Event handler for canceling the dialog.
        get_input(): Get the user-selected modalities.

    """

    def __init__(self, parent, modalities: list[str]):
        super().__init__(master=parent)
        self.attr_map = {
            "Code": (_("Code"), 5, True),
            "Modality": (_("Description"), 30, False),
        }
        self.root: ctk.CTk = parent.master
        self.modalities = modalities
        self.title(_("Select Modalities"))
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
            columns=list(self.attr_map.keys()),
            selectmode="browse",  # single selection
        )
        # Bind a callback function to item selection
        self._tree.bind("<<TreeviewSelect>>", self.on_item_select)
        selected_bg_color = self.root._apply_appearance_mode(
            ThemeManager.theme["Treeview"]["selected_bg_color"]
        )
        selected_color = self.root._apply_appearance_mode(
            ThemeManager.theme["Treeview"]["selected_color"]
        )
        self._tree.tag_configure(
            "green", foreground=selected_color, background=selected_bg_color
        )
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

        for code in get_modalities():
            tag = ""
            if code in self.modalities:
                tag = "green"
            try:
                self._tree.insert(
                    "",
                    "end",
                    iid=code,
                    values=[code, get_modalities()[code][0]],
                    tags=tag,
                )
            except Exception as e:
                logger.error(f"Exception: {e}")

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
        self._default_selection_button.grid(
            row=0, column=1, padx=PAD, pady=PAD, sticky="w"
        )

        self._ok_button = ctk.CTkButton(
            self._button_frame, width=100, text=_("Ok"), command=self._ok_event
        )
        self._ok_button.grid(
            row=0,
            column=2,
            padx=PAD,
            pady=PAD,
            sticky="e",
        )

    def on_item_select(self, event):
        selected_items = self._tree.selection()
        if len(selected_items) == 0:
            return
        selected_item = selected_items[0]
        self._tree.selection_remove(selected_item)
        if selected_item in self.modalities:
            logger.info(f"REMOVE {selected_item} from modalities")
            self.modalities.remove(selected_item)
            self._tree.item(selected_item, tags="")
        else:
            logger.info(f"ADD {selected_item} to modalities")
            self.modalities.append(selected_item)
            self._tree.item(selected_item, tags="green")

    def _default_selection_button_pressed(self):
        logger.info("_default_selection_button_pressed")
        self.modalities.clear()
        self.modalities = [mod for mod in ProjectModel.default_modalities()]
        for item in self._tree.get_children():
            self._tree.item(item, tags="")
            if item in self.modalities:
                self._tree.item(item, tags="green")

    def _select_all_button_pressed(self):
        logger.info("_select_all_button_pressed")
        self.modalities.clear()
        for item in self._tree.get_children():
            self.modalities.append(item)
            self._tree.item(item, tags="green")

    def _enter_keypress(self, event):
        logger.info("_enter_pressed")
        self._ok_event()

    def _ok_event(self, event=None):
        self._user_input = self.modalities
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
