import customtkinter as ctk
from tkhtmlview import HTMLScrolledText
import logging
from utils.translate import _

logger = logging.getLogger(__name__)
HELP_FILE = "assets/help.html"


def create_view(view: ctk.CTkFrame):
    logger.info("Creating Help View")
    try:
        with open(HELP_FILE, "r") as file:
            logger.info(f"Reading help file: {HELP_FILE}")
            html = file.read()
    except FileNotFoundError:
        logger.error(f"Help file: {HELP_FILE} not found.")
        html = _("<h1>Help file not found.</h1>")

    html_widget = HTMLScrolledText(view, html=html, background=view._bg_color[0])
    # html_widget.grid(row=0, column=0, sticky="nswe") #TODO: why does this not work?
    html_widget.pack(fill="both", expand=True)
