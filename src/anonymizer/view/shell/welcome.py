import customtkinter as ctk
from PIL import Image

from anonymizer.utils.translate import _, get_current_language, language_to_code
from anonymizer.view.common.ctk_safe import release_ctk_label_image
from anonymizer.view.common.fonts import AppFonts


class WelcomeView(ctk.CTkFrame):
    """Welcome view of the RSNA DICOM Anonymizer program."""

    PAD = 20
    TITLED_LOGO_FILE = "assets/icons/rsna_titled_logo_alpha.png"
    TITLED_LOGO_WIDTH = 255
    TITLED_LOGO_HEIGHT = 155
    WELCOME_TEXT_WRAP_LENGTH = 650
    WELCOME_WINDOW_WIDTH = WELCOME_TEXT_WRAP_LENGTH + PAD * 4
    WELCOME_WINDOW_HEIGHT = 920

    def __init__(self, parent: ctk.CTk, change_language_callback, ai_features_callback, *, fonts: AppFonts):
        super().__init__(master=parent)
        self._fonts = fonts
        self.title = _("Welcome")
        self.welcome_text = (
            _(
                "The RSNA DICOM Anonymizer program is a free open-source tool for curating and de-identifying DICOM studies."
            )
            + "\n\n"
            + _("Easy to use, advanced DICOM expertise not required!")
            + "\n\n"
            + _(
                "Use it to ensure privacy by removing protected identity & health information (PHI/PII) from both metadata and burnt into pixel data."
            )
            + "\n\n"
            + _("Go to Help/Overview for a quick overview.")
            + "\n\n"
            + _("Go to Help/Project settings for instructions on how to configure the program.")
            + "\n\n"
            + _("Go to Help/Operation for instructions on how to use the program.")
            + "\n\n"
            + _("Select File/New Project to start.")
        )
        self.sponsor_text = _("SPONSOR MESSAGE")
        self.change_language_callback = change_language_callback
        self.ai_features_callback = ai_features_callback
        self._logo_widget: ctk.CTkLabel | None = None
        self._logo_image: ctk.CTkImage | None = None
        self._create_widgets()

    def release_images(self) -> None:
        """Drop logo PhotoImage references on the main thread before destroy."""
        if self._logo_widget is not None:
            release_ctk_label_image(self._logo_widget)
        self._logo_widget = None
        self._logo_image = None

    def _create_widgets(self):
        # Let content rows define height naturally (v18-style behavior).

        language_buttons = ctk.CTkSegmentedButton(
            master=self,
            values=list(language_to_code.keys()),
            command=self.change_language_callback,
        )
        language_buttons.set(get_current_language())
        language_buttons.grid(row=0, column=0, padx=self.PAD, pady=self.PAD, sticky="ne")

        self._ai_features_button = ctk.CTkButton(
            master=self,
            text=_("AI Features"),
            command=self.ai_features_callback,
        )
        self._ai_features_button.grid(row=0, column=0, padx=self.PAD, pady=(52, 0), sticky="ne")

        self._logo_image = ctk.CTkImage(
            light_image=Image.open(self.TITLED_LOGO_FILE),
            dark_image=Image.open(self.TITLED_LOGO_FILE),
            size=(self.TITLED_LOGO_WIDTH, self.TITLED_LOGO_HEIGHT),
        )
        self._logo_widget = ctk.CTkLabel(master=self, image=self._logo_image, text="")
        self._logo_widget.grid(row=1, column=0, sticky="n")

        label_welcome = ctk.CTkLabel(master=self, text=self.title, font=self._fonts.title)
        label_welcome.grid(row=2, column=0, pady=self.PAD, sticky="n")

        label_welcome_text = ctk.CTkLabel(
            master=self,
            text=self.welcome_text,
            font=self._fonts.body,
            justify="left",
            wraplength=self.WELCOME_TEXT_WRAP_LENGTH,
        )
        label_welcome_text.grid(row=3, column=0, padx=self.PAD * 2, pady=(self.PAD, self.PAD * 2))

        label_sponsor_text = ctk.CTkLabel(
            master=self,
            text=self.sponsor_text,
            font=self._fonts.small,
            justify="left",
            wraplength=self.WELCOME_TEXT_WRAP_LENGTH,
        )
        label_sponsor_text.grid(row=4, column=0, padx=self.PAD * 2, pady=(self.PAD, self.PAD * 2))
