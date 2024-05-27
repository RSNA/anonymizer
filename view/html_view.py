# List of HTML Tags supported by tkhtmlview:
# see https://github.com/bauripalash/tkhtmlview?tab=readme-ov-file#html-support
import os
import tkinter as tk
import customtkinter as ctk
from tkhtmlview import HTMLScrolledText, RenderHTML
import logging
from utils.translate import _

logger = logging.getLogger(__name__)


class HTMLView(tk.Toplevel):
    # class HTMLView(ctk.CTkToplevel):
    def __init__(self, parent, title, html_file_path):
        super().__init__(master=parent)
        self._parent = parent
        self.title(title)
        self.html_file_path = html_file_path
        self._frame = ctk.CTkFrame(self)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._frame.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
        self._create_widgets()
        # if sys.platform.startswith("win"):
        #     # override CTkTopLevel which sets icon after 200ms
        #     self.after(250, self._win_post_init)

    # def _win_post_init(self):
    #     self.iconbitmap("assets\\images\\rsna_icon.ico")
    #     self.lift()
    #     self.focus()

    def _create_widgets(self):
        logger.debug("_create_widgets")

        html_widget = HTMLScrolledText(
            self._frame,
            width=140,  # characters
            height=40,  # lines
            wrap="word",
            html=RenderHTML(self.html_file_path),
        )
        html_widget.pack(fill="both", padx=10, pady=10, expand=True)
        html_widget.configure(state="disabled")
