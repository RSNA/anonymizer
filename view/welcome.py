import customtkinter as ctk
from PIL import Image
from utils.translate import _


class WelcomeView(ctk.CTkFrame):
    PAD = 10
    WELCOME_TITLE = _("Welcome")
    WELCOME_TITLE_FONT = ("DIN Alternate", 28)
    WELCOME_TEXT = _(
        "The RSNA Anonymizer program is a free open-source tool for collecting and de-identifying DICOM studies to prepare them for submission.\n\n"
        "It may be used to ensure privacy by removing protected health information (PHI) from your DICOM imaging studies.\n\n"
        "Refer to Help/Instructions for more information.\n\n"
        "Select File/New Project to start."
    )
    WELCOME_TEXT_FONT = ("DIN Alternate", 20)
    TITLED_LOGO_FILE = "assets/images/rsna_titled_logo_alpha.png"  # alpha channel  / transparent background
    TITLED_LOGO_WIDTH = 255
    TITLED_LOGO_HEIGHT = 155
    TEXT_BOX_WIDTH = 800
    TEXT_BOX_HEIGHT = 400

    def __init__(self, parent: ctk.CTk):
        super().__init__(master=parent)
        self._create_widgets()
        self.grid(row=0, column=0, padx=self.PAD, pady=self.PAD)

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
            text=self.WELCOME_TITLE,
            font=self.WELCOME_TITLE_FONT,
        )
        label_welcome.grid(row=1, column=0, pady=self.PAD, sticky="n")

        # Welcome Text:
        text_box_welcome = ctk.CTkTextbox(
            master=self,
            width=self.TEXT_BOX_WIDTH,
            height=self.TEXT_BOX_HEIGHT,
            wrap="word",
            fg_color=tuple[str, str](self._fg_color),
            font=self.WELCOME_TEXT_FONT,
            activate_scrollbars=False,
        )

        text_box_welcome.insert("0.0", text=self.WELCOME_TEXT)
        text_box_welcome.configure(state="disabled")
        text_box_welcome.grid(row=2, column=0, padx=self.PAD, pady=self.PAD, sticky="nswe")
