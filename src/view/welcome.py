import customtkinter as ctk
from PIL import Image
from utils.translate import _
from customtkinter import ThemeManager


class WelcomeView(ctk.CTkFrame):
    PAD = 20
    TITLE = _("Welcome")
    TITLE_FONT_SIZE = 28
    WELCOME_TEXT = _(
        "The RSNA DICOM Anonymizer program is a free open-source tool for curating and de-identifying DICOM studies.\n\n"
        "Easy to use, DICOM expertise not required!\n\n"
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
    TEXT_BOX_WIDTH = 700
    TEXT_BOX_HEIGHT = 400

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
        text_box_welcome = ctk.CTkTextbox(
            master=self,
            width=self.TEXT_BOX_WIDTH,
            height=self.TEXT_BOX_HEIGHT,
            wrap="word",
            font=ctk.CTkFont(family=self.font_family, size=self.WELCOME_TEXT_FONT_SIZE),
            activate_scrollbars=False,
        )

        text_box_welcome.insert("0.0", text=self.WELCOME_TEXT)
        text_box_welcome.configure(state="disabled")
        text_box_welcome.grid(row=2, column=0, padx=self.PAD * 2, pady=self.PAD)
