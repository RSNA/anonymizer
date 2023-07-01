import os
import customtkinter as ctk
from PIL import Image
import logging
import logging.handlers
from translate import _

# All UX View Modules:
import welcome
import help
import storage_dir
import storage_scp

LOGS_DIR = "/logs/"
LOG_FILENAME = "dicom_scrub.log"
LOG_SIZE = 1024 * 1024
LOG_BACKUP_COUNT = 10
LOG_DEFAULT_LEVEL = logging.INFO
logger = logging.getLogger()

APP_TITLE = _("DICOM Anonymizer Version 17")
APP_START_GEOMETRY = "1200x800"
__version__ = "17.1.0.1"
LOGO_WIDTH = 75
LOGO_HEIGHT = 20
PAD = 10

# View Names:
WELCOME_VIEW = _("Welcome")
HELP_VIEW = _("Help")
SET_STORAGE_DIR_VIEW = _("Set Storage Directory")
CONFIGURE_STORAGE_SCP_VIEW = _("Configure Storage SCP")
ANONYMIZER_SCRIPT_VIEW = _("Anonymizer Script")
FILTER_SETTINGS_VIEW = _("Filter Settings")
SELECT_LOCAL_FILES_VIEW = _("Select Local Files")
QUERY_SCP_STORAGE_VIEW = _("Query SCP Storage")
PATIENT_INDEX_LIST_VIEW = _("Patient Index List")
EXPORT_TO_HTTPS_VIEW = _("Export to HTTPS")
EXPORT_TO_SCP_STORAGE_VIEW = _("Export to SCP Storage")
IMPORT_LOG_VIEW = _("Import Log")
EXPORT_LOG_VIEW = _("Export Log")

APP_TABS = {
    # _("About"): [WELCOME_VIEW, HELP_VIEW],
    _("Storage"): [SET_STORAGE_DIR_VIEW, CONFIGURE_STORAGE_SCP_VIEW],
    _("Settings"): [ANONYMIZER_SCRIPT_VIEW, FILTER_SETTINGS_VIEW],
    _("Import"): [SELECT_LOCAL_FILES_VIEW, QUERY_SCP_STORAGE_VIEW],
    _("Verify"): [PATIENT_INDEX_LIST_VIEW],
    _("Export"): [EXPORT_TO_HTTPS_VIEW, EXPORT_TO_SCP_STORAGE_VIEW],
    _("Admin"): [IMPORT_LOG_VIEW, EXPORT_LOG_VIEW],
}


class TabViewNested(ctk.CTkTabview):
    def __init__(self, master, tabs, **kwargs):
        super().__init__(master, **kwargs)
        for tab in tabs:
            tabview = self.add(tab)

            # TODO: move all view modules in /views and import them here using importlib, move embedded tabs into APP_TABS with tuple of (view_module, view_name)
            if tab == WELCOME_VIEW:
                welcome.create_view(tabview)
            elif tab == HELP_VIEW:
                help.create_view(tabview)
            elif tab == SET_STORAGE_DIR_VIEW:
                storage_dir.create_view(tabview, tab)
            elif tab == CONFIGURE_STORAGE_SCP_VIEW:
                storage_scp.create_view(tabview)


class TabViewMain(ctk.CTkTabview):
    def __init__(
        self,
        master,
        tabs,
        border_width,
        **kwargs,
    ):
        super().__init__(master, border_width=border_width, **kwargs)

        for main_tab, embedded_tabs in tabs.items():
            # Get the parent widget for the nested TabView
            parent = self.add(main_tab)

            # Configure the parent widget to distribute extra space to the nested TabView
            parent.rowconfigure(0, weight=1)
            parent.columnconfigure(0, weight=1)

            # Create and grid the nested TabViews
            tabview_nested = TabViewNested(master=parent, tabs=embedded_tabs)
            tabview_nested.grid(row=0, column=0, sticky="nswe")


class App(ctk.CTk):
    def __init__(
        self,
        color_theme,
        title,
        logo_file,
        logo_width,
        logo_height,
        tabs,
        pad,
    ):
        super().__init__()

        ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
        # sets all colors and default font:
        ctk.set_default_color_theme(color_theme)

        self.geometry(APP_START_GEOMETRY)
        self.font = ctk.CTkFont()  # get default font as defined in json file
        self.title(title)
        self.title_height = self.font.metrics("linespace")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Logo:
        self.logo = ctk.CTkImage(
            light_image=Image.open(logo_file),
            size=(logo_width, logo_height),
        )
        self.logo = ctk.CTkLabel(self, image=self.logo, text="")
        self.logo.grid(
            row=0,
            column=0,
            padx=pad,
            pady=(pad, 0),
            sticky="nw",
        )

        # Title:
        self.title_label = ctk.CTkLabel(
            self,
            text=title,
            # font=self.font,
        )
        self.title_label.grid(
            row=0,
            column=0,
            pady=(logo_height + pad - self.title_height, 0),
            sticky="n",
        )

        # Content (TabView):
        self.tab_view = TabViewMain(
            master=self,
            tabs=tabs,
            border_width=pad,
        )
        self.tab_view.grid(row=1, column=0, padx=pad, pady=(0, pad), sticky="nswe")


def setup_logging(logs_dir) -> None:
    # TODO: allow setup from log.config file
    os.makedirs(logs_dir, exist_ok=True)
    # Setup  rotating log file:
    logFormatter = logging.Formatter(
        "{asctime} {levelname} {module}.{funcName}.{lineno} {message}", style="{"
    )
    fileHandler = logging.handlers.RotatingFileHandler(
        logs_dir + LOG_FILENAME, maxBytes=LOG_SIZE, backupCount=LOG_BACKUP_COUNT
    )
    fileHandler.setFormatter(logFormatter)
    logger.addHandler(fileHandler)
    # Setup stderr console output:
    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(logFormatter)
    logger.addHandler(consoleHandler)
    logger.setLevel(logging.INFO)


def main():
    install_dir = os.path.dirname(os.path.realpath(__file__))
    setup_logging(install_dir + LOGS_DIR)
    os.chdir(install_dir)

    logger.info("Starting DICOM ANONYMIZER GUI Version %s", __version__)
    logger.info(f"Running from {os.getcwd()}")

    app = App(
        color_theme=install_dir + "/assets/rsna_color_scheme_font.json",
        title=APP_TITLE,
        logo_file=install_dir + "/assets/images/rsna_logo_alpha.png",
        logo_width=LOGO_WIDTH,
        logo_height=LOGO_HEIGHT,
        tabs=APP_TABS,
        pad=PAD,
    )

    app.mainloop()

    logger.info("DICOM ANONYMIZER GUI Stop.")


if __name__ == "__main__":
    main()
