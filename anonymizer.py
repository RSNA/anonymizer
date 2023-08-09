import os
from pathlib import Path
import customtkinter as ctk
from PIL import Image
import logging
from utils.translate import _
from utils.logging import init_logging
from __version__ import __version__
from pydicom._version import __version__ as pydicom_version
from pynetdicom._version import __version__ as pynetdicom_version

# All UX View Modules:
import view.welcome as welcome
import view.help as help
import view.storage_dir as storage_dir
import view.storage_scp as storage_scp
import view.select_local_files as select_local_files
import view.query_retrieve_scp as query_retrieve_scp
import view.export as export

# To ensure DICOM C-STORE SCP is stopped and socket is closed on exit:
import controller.dicom_storage_scp as dicom_storage_scp
from controller.anonymize import init as init_anonymizer

APP_TITLE = _("RSNA DICOM Anonymizer Version " + __version__)
APP_MIN_WIDTH = 1200
APP_MIN_HEIGHT = 800
LOGO_WIDTH = 75
LOGO_HEIGHT = 20
PAD = 10

# View Names:
WELCOME_VIEW = _("Welcome")
HELP_VIEW = _("Help")
SET_STORAGE_DIR_VIEW = _("Set Storage Directory")
CONFIGURE_STORAGE_SCP_VIEW = _("Configure Local Storage Server")
ANONYMIZER_SCRIPT_VIEW = _("Anonymizer Script")
FILTER_SETTINGS_VIEW = _("Filter Settings")
SELECT_LOCAL_FILES_VIEW = _("Select Local Files")
QUERY_SCP_STORAGE_VIEW = _("Query Remote Storage Server")
PATIENT_INDEX_LIST_VIEW = _("Patient Index List")
EXPORT_TO_AWS_VIEW = _("Export to AWS")
EXPORT_TO_SCP_STORAGE_VIEW = _("Export to Remote Storage Server")
IMPORT_LOG_VIEW = _("Import Log")
EXPORT_LOG_VIEW = _("Export Log")

APP_TABS = {
    _("About"): [WELCOME_VIEW, HELP_VIEW],
    _("Storage"): [SET_STORAGE_DIR_VIEW, CONFIGURE_STORAGE_SCP_VIEW],
    # _("Settings"): [ANONYMIZER_SCRIPT_VIEW, FILTER_SETTINGS_VIEW],
    _("Import"): [SELECT_LOCAL_FILES_VIEW, QUERY_SCP_STORAGE_VIEW],
    # _("Verify"): [PATIENT_INDEX_LIST_VIEW],
    _("Export"): [EXPORT_TO_SCP_STORAGE_VIEW, EXPORT_TO_AWS_VIEW],
    # _("Admin"): [IMPORT_LOG_VIEW, EXPORT_LOG_VIEW],
}


class TabViewNested(ctk.CTkTabview):
    def __init__(self, master, tabs, **kwargs):
        super().__init__(master, **kwargs)
        for tab in tabs:
            tabview = self.add(tab)

            # TODO: move all view modules in /views and import them here using importlib, move embedded tabs into APP_TABS with tuple of (view_module, view_name)
            # instead of calling create_view, automatically call the create_view function in the view module when initialised via importlib
            if tab == WELCOME_VIEW:
                welcome.create_view(tabview)
            elif tab == HELP_VIEW:
                help.create_view(tabview)
            elif tab == SET_STORAGE_DIR_VIEW:
                storage_dir.create_view(tabview, tab)
            elif tab == CONFIGURE_STORAGE_SCP_VIEW:
                storage_scp.create_view(tabview)
            elif tab == SELECT_LOCAL_FILES_VIEW:
                select_local_files.create_view(tabview)
            elif tab == QUERY_SCP_STORAGE_VIEW:
                query_retrieve_scp.create_view(tabview, PAD)
            elif tab == EXPORT_TO_SCP_STORAGE_VIEW:
                export.create_view(tabview, PAD)


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
        ctk.set_default_color_theme(color_theme)  # colors and default font

        self.geometry(f"{APP_MIN_WIDTH}x{APP_MIN_HEIGHT}")
        self.minsize(APP_MIN_WIDTH, APP_MIN_HEIGHT)  # width, height
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


def main():
    # TODO: handle command line arguments, implement command line interface
    install_dir = os.path.dirname(os.path.realpath(__file__))
    init_logging(install_dir)
    os.chdir(install_dir)

    logger = logging.getLogger()  # get root logger
    logger.info("Starting ANONYMIZER GUI Version %s", __version__)
    logger.info(f"Running from {os.getcwd()}")
    logger.info(
        f"pydicom Version: {pydicom_version}, pynetdicom Version: {pynetdicom_version}"
    )

    # Initialise controller.anonymize module:
    if not init_anonymizer():
        logger.error("Failed to initialise controller.anonymize module")
        return

    # GUI
    app = App(
        color_theme=install_dir + "/assets/themes/rsna_color_scheme_font.json",
        title=APP_TITLE,
        logo_file=install_dir + "/assets/images/rsna_logo_alpha.png",
        logo_width=LOGO_WIDTH,
        logo_height=LOGO_HEIGHT,
        tabs=APP_TABS,
        pad=PAD,
    )

    app.mainloop()

    # Ensure DICOM C-STORE SCP is stopped and socket is closed:
    if dicom_storage_scp.server_running():
        logger.info("Final shutdown: Stop DICOM C-STORE SCP and close socket")
        dicom_storage_scp.stop(True)

    logger.info("ANONYMIZER GUI Stop.")


if __name__ == "__main__":
    main()
