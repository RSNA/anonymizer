import customtkinter as ctk
from PIL import Image
from utils.translate import _, language_to_code, get_current_language
from customtkinter import ThemeManager


class WelcomeView(ctk.CTkFrame):
    PAD = 20
    TITLE_FONT_SIZE = 28
    WELCOME_TEXT_FONT_SIZE = 20
    TITLED_LOGO_FILE = "assets/icons/rsna_titled_logo_alpha.png"  # alpha channel  / transparent background
    TITLED_LOGO_WIDTH = 255
    TITLED_LOGO_HEIGHT = 155
    WELCOME_TEXT_WRAP_LENGTH = 650

    def __init__(self, parent: ctk.CTk, change_language_callback):
        super().__init__(master=parent)
        self.title = _("Welcome")
        self.welcome_text = (
            _(
                "The RSNA DICOM Anonymizer program is a free open-source tool for curating and de-identifying DICOM studies."
            )
            + "\n\n"
            + _("Easy to use, advanced DICOM expertise not required!")
            + "\n\n"
            + _("Use it to ensure privacy by removing protected health information (PHI).")
            + "\n\n"
            + _("Go to Help/Overview for a quick overview.")
            + "\n\n"
            + _("Go to Help/Project settings for instructions on how to configure the program.")
            + "\n\n"
            + _("Go to Help/Operation for instructions on how to use the program.")
            + "\n\n"
            + _("Select File/New Project to start.")
        )
        self.change_language_callback = change_language_callback
        self.font_family = ThemeManager.theme["CTkFont"]["family"]
        self._create_widgets()
        self.grid(row=0, column=0)

    def _create_widgets(self):
        self.rowconfigure(3, weight=1)

        # Languages:
        language_buttons = ctk.CTkSegmentedButton(
            master=self, values=list(language_to_code.keys()), command=self.change_language_callback
        )
        language_buttons.set(get_current_language())
        language_buttons.grid(row=0, column=0, padx=self.PAD, pady=self.PAD, sticky="ne")

        # Titled RSNA Logo:
        titled_logo_image = ctk.CTkImage(
            light_image=Image.open(self.TITLED_LOGO_FILE),
            size=(self.TITLED_LOGO_WIDTH, self.TITLED_LOGO_HEIGHT),
        )
        logo_widget = ctk.CTkLabel(master=self, image=titled_logo_image, text="")
        logo_widget.grid(
            row=1,
            column=0,
            sticky="n",
        )

        # Welcome Label:
        label_welcome = ctk.CTkLabel(
            master=self,
            text=self.title,
            font=ctk.CTkFont(family=self.font_family, size=self.TITLE_FONT_SIZE),
        )
        label_welcome.grid(row=2, column=0, pady=self.PAD, sticky="n")

        # Welcome Text:
        label_welcome_text = ctk.CTkLabel(
            master=self,
            text=self.welcome_text,
            font=ctk.CTkFont(family=self.font_family, size=self.WELCOME_TEXT_FONT_SIZE),
            justify="left",
            wraplength=self.WELCOME_TEXT_WRAP_LENGTH,
        )
        label_welcome_text.grid(row=3, column=0, padx=self.PAD * 2, pady=(self.PAD, self.PAD * 2))
