import os
from datetime import datetime
import logging
from queue import Queue, Empty, Full
import customtkinter as ctk
from controller.project import ProjectController
from utils.translate import _
from utils.storage import count_dcm_files_and_studies


logger = logging.getLogger(__name__)

DASHBOARD_TITLE_FONT = ("DIN Alternate", 28)
DASHBOARD_LABEL_FONT = ("DIN Alternate", 24)
DASHBOARD_DATA_FONT = ("DIN Alternate", 32)


class Dashboard(ctk.CTkFrame):
    def __init__(self, parent, controller: ProjectController):
        super().__init__(parent)
        self.parent = parent
        self.controller = controller
        self.create_widgets()
        self.update_dashboard()

    def query_button_click(self):
        logger.info(f"query_button_click")
        self.parent.master.query_retrieve()

    def export_button_click(self):
        logger.info(f"export_button_click")
        self.parent.master.export()

    def create_widgets(self):
        PAD = 20
        # TODO: manage fonts using theme
        # self.columnconfigure(3, weight=1)
        # self.rowconfigure(0, weight=1)
        # self.rowconfigure(1, weight=1)

        # self.title_site_id = ctk.CTkLabel(
        #     self,
        #     font=DASHBOARD_TITLE_FONT,
        #     text=f"Site: {self.controller.model.site_id} ",
        # )
        # self.title_trial_name = ctk.CTkLabel(
        #     self,
        #     font=DASHBOARD_TITLE_FONT,
        #     text=f"Trial: {self.controller.model.trial_name} ",
        # )

        # self.title_site_id.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nw")
        # self.title_trial_name.grid(row=0, column=2, padx=PAD, pady=PAD, sticky="ne")
        row = 0

        self.query_button = ctk.CTkButton(
            self, width=100, text=_("Query"), command=self.query_button_click
        )
        self.query_button.grid(row=row, column=0, padx=PAD, pady=(PAD, 0), sticky="w")

        self.export_button = ctk.CTkButton(
            self, width=100, text=_("Export"), command=self.export_button_click
        )
        self.export_button.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="w")

        row += 1

        # TODO: parameterize / enum labels and data
        self.label_patients = ctk.CTkLabel(
            self, font=DASHBOARD_LABEL_FONT, text="Patients"
        )
        self.label_studies = ctk.CTkLabel(
            self, font=DASHBOARD_LABEL_FONT, text="Studies"
        )
        # self.label_series = ctk.CTkLabel(self, font=DASHBOARD_LABEL_FONT, text="Series")
        self.label_images = ctk.CTkLabel(self, font=DASHBOARD_LABEL_FONT, text="Images")

        self.label_patients.grid(row=row, column=0, padx=PAD, pady=PAD)
        self.label_studies.grid(row=row, column=1, padx=PAD, pady=PAD)
        # self.label_series.grid(row=row, column=2, padx=PAD, pady=PAD)
        self.label_images.grid(row=row, column=3, padx=PAD, pady=PAD)

        row += 1

        self._patients = ctk.CTkLabel(self, font=DASHBOARD_DATA_FONT, text="0")
        self._studies = ctk.CTkLabel(self, font=DASHBOARD_DATA_FONT, text="0")
        # self._series = ctk.CTkLabel(self, font=DASHBOARD_DATA_FONT, text="0")
        self._images = ctk.CTkLabel(self, font=DASHBOARD_DATA_FONT, text="0")

        self._patients.grid(row=row, column=0, padx=PAD, pady=PAD)
        self._studies.grid(row=row, column=1, padx=PAD, pady=PAD)
        # self._series.grid(row=row, column=2, padx=PAD, pady=PAD)
        self._images.grid(row=row, column=3, padx=PAD, pady=PAD)

    def update_dashboard(self):
        if self.controller.echo("QUERY"):
            self.query_button.configure(text_color="light green")
        else:
            self.query_button.configure(text_color="red")

        if self.controller.echo("EXPORT"):
            self.export_button.configure(text_color="light green")
        else:
            self.export_button.configure(text_color="red")

        dir = self.controller.model.storage_dir
        pts = os.listdir(dir)
        pts = [item for item in pts if not item.endswith(".pkl")]
        studies = 0
        images = 0

        for pt in pts:
            study_count, file_count = count_dcm_files_and_studies(os.path.join(dir, pt))
            studies += study_count
            images += file_count

        self._patients.configure(text=f"{len(pts)}")
        self._studies.configure(text=f"{studies}")
        # self._series.configure(text=f"{num_series}")
        self._images.configure(text=f"{images}")

        self.after(500, self.update_dashboard)
