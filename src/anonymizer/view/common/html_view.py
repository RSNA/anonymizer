# List of HTML Tags supported by tkhtmlview:
# see https://github.com/bauripalash/tkhtmlview?tab=readme-ov-file#html-support
import re
from collections.abc import Callable

import customtkinter as ctk
from tkhtmlview import HTMLScrolledText

from anonymizer.view.common.app_window import AppToplevel

HELP_LINK_PREFIX = "help:"


def is_ai_features_help(html_file_path: str) -> bool:
    normalized = html_file_path.replace("\\", "/").lower()
    return "ai features" in normalized or "/ai_features/" in normalized


class HTMLView(AppToplevel):
    """
    A custom Tkinter Toplevel window for displaying HTML content.

    Args:
        parent (ctk.CTk): The parent CTk object.
        title (str): The title of the HTMLView window.
        html_file_path (str): The file path to the HTML content.
        on_help_link (callable | None): Opens in-app help pages for ``help:`` links.

    Attributes:
        MIN_WIDTH_px (int): The minimum width of the HTMLView window in pixels.
        MAX_WIDTH_px (int): The maximum width of the HTMLView window in pixels.
        HEIGHT_LINES (int): The number of lines for the HTMLScrolledText widget.

    """

    MIN_WIDTH_px = 100
    MAX_WIDTH_px = 180
    AI_FEATURES_MIN_WIDTH_px = 120
    AI_FEATURES_MAX_WIDTH_px = 240
    HEIGHT_LINES = 40

    def __init__(
        self,
        parent: ctk.CTk,
        title: str,
        html_file_path: str,
        *,
        on_help_link: Callable[[str], None] | None = None,
        wide_layout: bool = False,
    ):
        super().__init__(master=parent)
        self._bg_color = parent._apply_appearance_mode(ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
        self._parent = parent
        self.title(title)
        self.html_file_path = html_file_path
        self._on_help_link = on_help_link
        self._wide_layout = wide_layout
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

        # Replace THEME_COLOR placeholder with theme color
        theme_color = self._parent._apply_appearance_mode(ctk.ThemeManager.theme["CTkLabel"]["text_color"])
        html_content = html_content.replace("THEME_COLOR", theme_color)

        # Find all <li> elements and their content
        li_elements = re.findall(r"<li>(.*?)</li>", html_content, re.DOTALL)
        li_texts = [re.sub(r"<.*?>", "", li).strip() for li in li_elements]  # Remove any nested HTML tags
        width_candidates = list(li_texts)
        if self._wide_layout:
            paragraph_elements = re.findall(r"<p>(.*?)</p>", html_content, re.DOTALL)
            for paragraph in paragraph_elements:
                plain_text = re.sub(r"<.*?>", "", paragraph)
                width_candidates.extend(line.strip() for line in plain_text.splitlines() if line.strip())

        longest_line = max(width_candidates, key=len, default="")
        min_width = self.AI_FEATURES_MIN_WIDTH_px if self._wide_layout else self.MIN_WIDTH_px
        max_width = self.AI_FEATURES_MAX_WIDTH_px if self._wide_layout else self.MAX_WIDTH_px
        required_width = len(longest_line) + 2  # Add some padding
        # Clip to max/min width
        required_width = max(min_width, min(required_width, max_width))

        html_widget = HTMLScrolledText(
            self._frame,
            width=required_width,
            height=self.HEIGHT_LINES,
            wrap="word",
            background=self._bg_color,
        )
        html_widget.set_html(html_content)
        self._bind_help_links(html_widget)
        html_widget.pack(fill="both", padx=10, pady=10, expand=True)
        html_widget.configure(state="disabled")

    def _bind_help_links(self, html_widget: HTMLScrolledText) -> None:
        if self._on_help_link is None:
            return
        for slot in html_widget.html_parser.hlink_slots:
            if not slot.URL.startswith(HELP_LINK_PREFIX):
                continue
            relative_path = slot.URL[len(HELP_LINK_PREFIX) :]

            def _open_help(event, path=relative_path) -> None:
                self._on_help_link(path)

            html_widget.tag_bind(slot.tag_name, "<Button-1>", _open_help)
            html_widget.tag_bind(slot.tag_name, "<Enter>", slot.enter)
            html_widget.tag_bind(slot.tag_name, "<Leave>", slot.leave)
