import customtkinter as ctk
from PIL import Image
from utils.translate import _

WELCOME_TITLE = _("Welcome")
WELCOME_TITLE_FONT = ("DIN Alternate", 28)
WELCOME_TEXT = _(
    "The RSNA Anonymizer program is a free open-source tool for collecting and de-identifying DICOM studies to prepare them for submission.\n\n"
    "It may be used to ensure privacy by removing protected health information from your DICOM imaging studies.\n\n"
    "Refer to Help/Instructions for more information.\n\n"
    "Select File/New Project to start."
)
WELCOME_TEXT_FONT = ("DIN Alternate", 20)
TITLED_LOGO_FILE = "assets/images/rsna_titled_logo_alpha.png"  # alpha channel  / transparent background
TITLED_LOGO_WIDTH = 255
TITLED_LOGO_HEIGHT = 155


def create_view(view: ctk.CTkFrame):
    PAD = 10

    view.columnconfigure(0, weight=1)
    view.rowconfigure(2, weight=1)

    # Titled RSNA Logo:
    titled_logo_image = ctk.CTkImage(
        light_image=Image.open(TITLED_LOGO_FILE),
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
        master=view,
        text=WELCOME_TITLE,
        font=WELCOME_TITLE_FONT,
    )
    label_welcome.grid(row=1, column=0, pady=PAD, sticky="n")

    # Welcome Text:
    text_box_welcome = ctk.CTkTextbox(view, wrap="word", fg_color=view._fg_color, font=WELCOME_TEXT_FONT, activate_scrollbars=False, width=800, height=400)  # type: ignore
    text_box_welcome.insert("0.0", text=WELCOME_TEXT)
    text_box_welcome.configure(state="disabled")
    text_box_welcome.grid(row=2, column=0, padx=PAD, pady=PAD, sticky="nswe")
