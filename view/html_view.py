from typing import Union
import customtkinter as ctk
from tkhtmlview import HTMLScrolledText
import logging
from utils.translate import _

logger = logging.getLogger(__name__)


class HTMLView(ctk.CTkToplevel):
    def __init__(self, parent, title, width, height, html_file_path):
        super().__init__(parent)
        self.geometry(f"{width}x{height}")
        self.title(title)
        self.html_file_path = html_file_path
        self.lift()
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._frame = ctk.CTkFrame(self)
        self._frame.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
        self._create_widgets()

    def _create_widgets(self):
        logger.info("_create_widgets")
        try:
            with open(self.html_file_path, "r") as file:
                html = file.read()
        except FileNotFoundError:
            logger.error(f"Help file: {self.html_file_path} not found.")
            html = _("<h1>Help file not found.</h1>")

        html_widget = HTMLScrolledText(
            self._frame, html=html, background=self._frame._bg_color[0]
        )
        # html_widget.grid(row=0, column=0, sticky="nswe") #TODO: why does this not work?
        html_widget.pack(fill="both", expand=True)
