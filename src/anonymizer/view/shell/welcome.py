import contextlib
import logging
import webbrowser

import customtkinter as ctk
from PIL import Image

from anonymizer.utils.dicom import DICOM_CONFIDENTIALITY_PROFILE_URL
from anonymizer.utils.translate import _, get_current_language, language_to_code
from anonymizer.view.common.ctk_safe import release_ctk_label_image
from anonymizer.view.common.fonts import AppFonts
from anonymizer.view.common.ux_fields import button_width_for_label

logger = logging.getLogger(__name__)

LOINC_URL = (
    "https://docs.google.com/spreadsheets/d/1YFz3_dHfmkPBL923wUos-uQb0kiT3Tcj/edit?gid=1702394391#gid=1702394391"
)
RADLEX_URL = "https://www.rsna.org/practice-tools/data-tools-and-standards/radlex-playbook-series"
OPENMED_NER_URL = "https://github.com/maziyarpanahi/openmed"
TOTALSEGMENTATOR_URL = "https://github.com/wasserth/TotalSegmentator"


class WelcomeView(ctk.CTkFrame):
    """Welcome view of the RSNA DICOM Anonymizer program."""

    PAD = 20
    TITLED_LOGO_FILE = "assets/icons/rsna_titled_logo_alpha.png"
    TITLED_LOGO_WIDTH = 255
    TITLED_LOGO_HEIGHT = 155
    WELCOME_TEXT_WRAP_LENGTH = 650
    WELCOME_WINDOW_WIDTH = WELCOME_TEXT_WRAP_LENGTH + PAD * 4
    WELCOME_WINDOW_HEIGHT = 1100

    def __init__(self, parent: ctk.CTk, change_language_callback, ai_features_callback, *, fonts: AppFonts):
        super().__init__(master=parent)
        self._fonts = fonts
        self.title = _("Welcome")
        # Intro paragraph; de-id / PHI / face / Harmonize sentences follow with links under each.
        self.welcome_text_top = _(
            "Free, open-source DICOM curation and de-identification — entirely on "
            "your workstation, with no cloud processing. Use it offline; connect "
            "only to download AI models or open online documentation and links."
        )
        self.welcome_text_dicom = _(
            "Select from the full set of DICOM confidentiality options for your project — "
            "what to remove, what to retain."
        )
        self.welcome_text_phi = _(
            "Detect PHI in embedded text or pixels and then either remove or replace with synthetic data."
        )
        self.welcome_text_face = _(
            "De-identify faces on head CT and MR: accurately segment the face, not the skull, then blur that region."
        )
        # Harmonize sentence; LOINC / RadLex links sit under this block.
        self.welcome_text_harmonize = _(
            "Harmonize maps study descriptions to LOINC study names and series descriptions "
            "to the RSNA RadLex Playbook."
        )
        self.welcome_text_bottom = (
            _("Open Help → User Manual → Start here for how to configure and use the program.")
            + "\n\n"
            + _(
                "Use the AI Features button on this screen to download models and set the "
                "resolution for anatomy segmentation used in Harmonize."
            )
            + "\n\n"
            + _("Select File → New Project to start.")
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

    @staticmethod
    def _open_url(url: str) -> None:
        try:
            webbrowser.open(url)
        except Exception:
            logger.exception("Failed to open URL %s", url)

    def _link_button(self, master: ctk.CTkFrame, text: str, url: str, *, width: int = 90) -> ctk.CTkButton:
        button = ctk.CTkButton(
            master=master,
            text=text,
            width=width,
            height=28,
            fg_color="transparent",
            hover_color=("gray80", "gray30"),
            text_color=("#1a5fb4", "#62a0ea"),
            anchor="w",
            command=lambda: self._open_url(url),
        )
        with contextlib.suppress(Exception):
            button.configure(cursor="hand2")
        return button

    def _body_label(self, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            master=self,
            text=text,
            font=self._fonts.body,
            justify="left",
            anchor="w",
            wraplength=self.WELCOME_TEXT_WRAP_LENGTH,
        )

    def _single_link_row(self, text: str, url: str) -> ctk.CTkFrame:
        row = ctk.CTkFrame(master=self, fg_color="transparent")
        self._link_button(
            row,
            text,
            url,
            width=button_width_for_label(text, minimum=90),
        ).grid(row=0, column=0)
        return row

    def _create_widgets(self):
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

        self._body_label(self.welcome_text_top).grid(
            row=3, column=0, padx=self.PAD * 2, pady=(self.PAD, 0), sticky="ew"
        )

        self._body_label(self.welcome_text_dicom).grid(
            row=4, column=0, padx=self.PAD * 2, pady=(self.PAD // 2, 0), sticky="ew"
        )
        self._single_link_row(
            _("DICOM Confidentiality Profile Options"),
            DICOM_CONFIDENTIALITY_PROFILE_URL,
        ).grid(row=5, column=0, padx=self.PAD * 2, pady=(2, self.PAD // 2), sticky="w")

        self._body_label(self.welcome_text_phi).grid(row=6, column=0, padx=self.PAD * 2, pady=(0, 0), sticky="ew")
        self._single_link_row(
            _("OpenMed Named Entity Recognizer"),
            OPENMED_NER_URL,
        ).grid(row=7, column=0, padx=self.PAD * 2, pady=(2, self.PAD // 2), sticky="w")

        self._body_label(self.welcome_text_face).grid(row=8, column=0, padx=self.PAD * 2, pady=(0, 0), sticky="ew")
        self._single_link_row(
            _("TotalSegmentator"),
            TOTALSEGMENTATOR_URL,
        ).grid(row=9, column=0, padx=self.PAD * 2, pady=(2, self.PAD // 2), sticky="w")

        self._body_label(self.welcome_text_harmonize).grid(
            row=10, column=0, padx=self.PAD * 2, pady=(0, 0), sticky="ew"
        )
        links = ctk.CTkFrame(master=self, fg_color="transparent")
        links.grid(row=11, column=0, padx=self.PAD * 2, pady=(2, self.PAD // 2), sticky="w")
        self._link_button(links, _("LOINC"), LOINC_URL).grid(row=0, column=0, padx=(0, self.PAD))
        self._link_button(links, _("RSNA RadLex Playbook"), RADLEX_URL, width=180).grid(row=0, column=1)

        self._body_label(self.welcome_text_bottom).grid(
            row=12, column=0, padx=self.PAD * 2, pady=(0, self.PAD), sticky="ew"
        )

        label_sponsor_text = ctk.CTkLabel(
            master=self,
            text=self.sponsor_text,
            font=self._fonts.small,
            justify="left",
            anchor="w",
            wraplength=self.WELCOME_TEXT_WRAP_LENGTH,
        )
        label_sponsor_text.grid(row=13, column=0, padx=self.PAD * 2, pady=(self.PAD, self.PAD * 2), sticky="ew")
        self.grid_columnconfigure(0, weight=1)
