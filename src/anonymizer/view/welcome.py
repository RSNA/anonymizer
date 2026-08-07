import customtkinter as ctk
from customtkinter import ThemeManager
from PIL import Image

from anonymizer.utils.translate import _, get_current_language, language_to_code
from anonymizer.view.ctk_safe import release_ctk_label_image


class WelcomeView(ctk.CTkFrame):
    """
    A class representing the welcome view of the RSNA DICOM Anonymizer program.

    This view displays a welcome message and provides options for language selection.

    Args:
        parent (ctk.CTk): The parent widget.
        change_language_callback (callable): A callback function to handle language change.
        ai_features_callback (callable): Opens the AI Features Setup dialog.

    Attributes:
    All dimensions in pixels.
        PAD (int): The padding value.
        TITLE_FONT_SIZE (int): The font size for the title.
        SPONSOR_TEXT_FONT_SIZE (int): The font size for the sponsor text.
        WELCOME_TEXT_FONT_SIZE (int): The font size for the welcome text.
        TITLED_LOGO_FILE (str): The file path of the titled RSNA logo.
        TITLED_LOGO_WIDTH (int): The width of the titled RSNA logo.
        TITLED_LOGO_HEIGHT (int): The height of the titled RSNA logo.
        WELCOME_TEXT_WRAP_LENGTH (int): The wrap length for the welcome text.

    """

    PAD = 20
    TITLE_FONT_SIZE = 28
    WELCOME_TEXT_FONT_SIZE = 20
    SPONSOR_TEXT_FONT_SIZE = 12
    TITLED_LOGO_FILE = "assets/icons/rsna_titled_logo_alpha.png"  # alpha channel  / transparent background
    TITLED_LOGO_WIDTH = 255
    TITLED_LOGO_HEIGHT = 155
    WELCOME_TEXT_WRAP_LENGTH = 650
    WELCOME_WINDOW_WIDTH = WELCOME_TEXT_WRAP_LENGTH + PAD * 4 + 80
    WELCOME_WINDOW_HEIGHT = 920

    def __init__(self, parent: ctk.CTk, change_language_callback, ai_features_callback):
        """
        Initialize the WelcomeView.

        Args:
            parent (ctk.CTk): The parent widget.
            change_language_callback (callable): A callback function to handle language change.
            ai_features_callback (callable): Opens the AI Features Setup dialog.

        """
        super().__init__(master=parent)
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
        self.font_family = ThemeManager.theme["CTkFont"]["family"]
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
        """
        Create the widgets for the WelcomeView.

        """
        self.rowconfigure(4, weight=1)

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=0, column=0, padx=self.PAD, pady=self.PAD, sticky="ne")

        language_buttons = ctk.CTkSegmentedButton(
            master=controls,
            values=list(language_to_code.keys()),
            command=self.change_language_callback,
        )
        language_buttons.set(get_current_language())
        language_buttons.grid(row=0, column=0, sticky="e")

        self._ai_features_button = ctk.CTkButton(
            master=controls,
            text=_("AI Features"),
            command=self.ai_features_callback,
        )
        self._ai_features_button.grid(row=1, column=0, pady=(8, 0), sticky="e")

        # Titled RSNA Logo:
        self._logo_image = ctk.CTkImage(
            light_image=Image.open(self.TITLED_LOGO_FILE),
            dark_image=Image.open(self.TITLED_LOGO_FILE),
            size=(self.TITLED_LOGO_WIDTH, self.TITLED_LOGO_HEIGHT),
        )
        self._logo_widget = ctk.CTkLabel(master=self, image=self._logo_image, text="")
        self._logo_widget.grid(
            row=1,
            column=0,
            sticky="n",
        )

        # Welcome Label:
        label_welcome = ctk.CTkLabel(
            master=self,
            text=self.title,
            font=ctk.CTkFont(family=self.font_family, weight="normal", size=self.TITLE_FONT_SIZE),
        )
        label_welcome.grid(row=2, column=0, pady=self.PAD, sticky="n")

        # Welcome Text:
        label_welcome_text = ctk.CTkLabel(
            master=self,
            text=self.welcome_text,
            font=ctk.CTkFont(family=self.font_family, weight="normal", size=self.WELCOME_TEXT_FONT_SIZE),
            justify="left",
            wraplength=self.WELCOME_TEXT_WRAP_LENGTH,
        )
        label_welcome_text.grid(row=3, column=0, padx=self.PAD * 2, pady=(self.PAD, self.PAD * 2))

        # Sponsor Text:
        label_sponsor_text = ctk.CTkLabel(
            master=self,
            text=self.sponsor_text,
            font=ctk.CTkFont(family=self.font_family, weight="normal", size=self.SPONSOR_TEXT_FONT_SIZE),
            justify="left",
            wraplength=self.WELCOME_TEXT_WRAP_LENGTH,
        )
        label_sponsor_text.grid(row=4, column=0, padx=self.PAD * 2, pady=(self.PAD, self.PAD * 2))
