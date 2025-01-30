
# List of HTML Tags supported by tkhtmlview:
# see https://github.com/bauripalash/tkhtmlview?tab=readme-ov-file#html-support
import re
import tkinter as tk

import customtkinter as ctk
from tkhtmlview import HTMLScrolledText, RenderHTML


class HTMLView(tk.Toplevel):
    """
    A custom Tkinter Toplevel window for displaying HTML content.

    Args:
        parent (ctk.CTk): The parent CTk object.
        title (str): The title of the HTMLView window.
        html_file_path (str): The file path to the HTML content.

    Attributes:
        MIN_WIDTH_px (int): The minimum width of the HTMLView window in pixels.
        MAX_WIDTH_px (int): The maximum width of the HTMLView window in pixels.
        HEIGHT_LINES (int): The number of lines for the HTMLScrolledText widget.

    """

    MIN_WIDTH_px = 100
    MAX_WIDTH_px = 180
    HEIGHT_LINES = 40

    def __init__(self, parent: ctk.CTk, title: str, html_file_path):
        super().__init__(master=parent)
        self._bg_color = parent._apply_appearance_mode(ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
        self._parent = parent
        self.title(title)
        self.html_file_path = html_file_path
        self._frame = ctk.CTkFrame(self)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._frame.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
        self._create_widgets()

    def _create_widgets(self):
        """
        Create the widgets for the HTMLView window.

        Reads the HTML content from the file, finds all <li> elements and their content,
        determines the required width based on the longest <li> element, and creates
        an HTMLScrolledText widget to display the HTML content.

        """

        # Read the HTML content from the file
        with open(self.html_file_path, "r") as file:
            html_content = file.read()

        # Find all <li> elements and their content
        li_elements = re.findall(r"<li>(.*?)</li>", html_content, re.DOTALL)
        li_texts = [re.sub(r"<.*?>", "", li).strip() for li in li_elements]  # Remove any nested HTML tags
        longest_li = max(li_texts, key=len, default="")
        required_width = len(longest_li) + 2  # Add some padding
        # Clip to max/min width
        required_width = max(self.MIN_WIDTH_px, min(required_width, self.MAX_WIDTH_px))

        html_widget = HTMLScrolledText(
            self._frame,
            width=required_width,
            height=self.HEIGHT_LINES,
            wrap="word",
            background=self._bg_color,
            html=RenderHTML(self.html_file_path),
        )
        html_widget.pack(fill="both", padx=10, pady=10, expand=True)
        html_widget.configure(state="disabled")
