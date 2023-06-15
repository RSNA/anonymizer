import customtkinter as ctk
from PIL import Image
import logging

logger = logging.getLogger(__name__)

WELCOME_TITLE = _("Welcome")
WELCOME_TITLE_FONT = ("DIN Alternate", 28)
WELCOME_TEXT = _(
    "RSNA is assembling a repository of de-identified COVID-19-related imaging data for research and education. "
    "Medical institutions interested in joining this international collaboration are invited to submit de-identified imaging data for inclusion in this repository. "
    "The RSNA Anonymizer program is a free open-source tool for collecting and de-identifying DICOM studies to prepare them for submission. "
    "It may be used to ensure privacy by removing protected health information from your DICOM imaging studies."
)
TITLED_LOGO_FILE = "assets/images/rsna_titled_logo_alpha.png"  # alpha channel  / transparent background
TITLED_LOGO_WIDTH = 255
TITLED_LOGO_HEIGHT = 155
PAD = 10


def create_view(view: ctk.CTkFrame):
    logger.info("Creating Welcome View")
    view.grid_rowconfigure(1, weight=1)
    view.grid_columnconfigure(0, weight=1)
    # Titled RSNA Logo:
    titled_logo_image = ctk.CTkImage(
        light_image=Image.open(TITLED_LOGO_FILE),
        dark_image=None,
        size=(TITLED_LOGO_WIDTH, TITLED_LOGO_HEIGHT),
    )
    logo_widget = ctk.CTkLabel(view, image=titled_logo_image, text="")
    logo_widget.grid(
        row=0,
        column=0,
        sticky="n",
    )
    # Welcome Label:
    label_welcome = ctk.CTkLabel(
        master=view, text=WELCOME_TITLE, font=WELCOME_TITLE_FONT
    )
    label_welcome.grid(row=1, column=0, pady=PAD, sticky="n")
    # Welcome Text:
    text_box_welcome = ctk.CTkTextbox(view, wrap="word", fg_color=view._fg_color)
    text_box_welcome.insert("0.0", text=WELCOME_TEXT)
    text_box_welcome.grid(row=2, column=0, pady=PAD, sticky="nwe")
