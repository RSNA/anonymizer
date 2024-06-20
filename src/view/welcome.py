import customtkinter as ctk
from PIL import Image
from utils.translate import _
from customtkinter import ThemeManager


class WelcomeView(ctk.CTkFrame):
    PAD = 20
    TITLE = _("Welcome")
    TITLE_FONT_SIZE = 28
    WELCOME_TEXT = _(
        "The RSNA DICOM Anonymizer program is a free open-source tool for curating\nand de-identifying DICOM studies.\n\n"
        "Easy to use, advanced DICOM expertise not required!\n\n"
        "Use it to ensure privacy by removing protected health information (PHI).\n\n"
        "Go to Help/Overview for a quick overview.\n\n"
        "Go to Help/Project settings for instructions on how to configure the program.\n\n"
        "Go to Help/Operation for instructions on how to use the program.\n\n"
        "Select File/New Project to start."
    )
    WELCOME_TEXT_FONT_SIZE = 20
    TITLED_LOGO_FILE = "assets/images/rsna_titled_logo_alpha.png"  # alpha channel  / transparent background
    TITLED_LOGO_WIDTH = 255
    TITLED_LOGO_HEIGHT = 155

    def __init__(self, parent: ctk.CTk):
        super().__init__(master=parent)
        self.font_family = ThemeManager.theme["CTkFont"]["family"]
        self._create_widgets()
        self.grid(row=0, column=0)

    def _create_widgets(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Titled RSNA Logo:
        titled_logo_image = ctk.CTkImage(
            light_image=Image.open(self.TITLED_LOGO_FILE),
            size=(self.TITLED_LOGO_WIDTH, self.TITLED_LOGO_HEIGHT),
        )
        logo_widget = ctk.CTkLabel(master=self, image=titled_logo_image, text="")
        logo_widget.grid(
            row=0,
            column=0,
            sticky="n",
        )
        # Welcome Label:
        label_welcome = ctk.CTkLabel(
            master=self,
            text=self.TITLE,
            font=ctk.CTkFont(family=self.font_family, size=self.TITLE_FONT_SIZE),
        )
        label_welcome.grid(row=1, column=0, pady=self.PAD, sticky="n")

        # Welcome Text:

        label_welcome_text = ctk.CTkLabel(
            master=self,
            text=self.WELCOME_TEXT,
            font=ctk.CTkFont(family=self.font_family, size=self.WELCOME_TEXT_FONT_SIZE),
            justify="left",
        )
        label_welcome_text.grid(row=2, column=0, padx=self.PAD * 2, pady=(self.PAD, self.PAD * 2))
