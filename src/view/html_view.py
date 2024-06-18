# List of HTML Tags supported by tkhtmlview:
# see https://github.com/bauripalash/tkhtmlview?tab=readme-ov-file#html-support
import tkinter as tk
import customtkinter as ctk
from tkhtmlview import HTMLScrolledText, RenderHTML
from utils.translate import _


class HTMLView(tk.Toplevel):
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

    def _create_widgets(self):
        html_widget = HTMLScrolledText(
            self._frame,
            width=140,  # characters
            height=40,  # lines
            wrap="word",
            html=RenderHTML(self.html_file_path),
        )
        html_widget.pack(fill="both", padx=10, pady=10, expand=True)
        html_widget.configure(state="disabled")
