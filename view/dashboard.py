import os
from datetime import datetime
import logging
from queue import Queue, Empty, Full
import customtkinter as ctk
from controller.project import ProjectController
from utils.translate import _
from utils.storage import count_studies_series_images


logger = logging.getLogger(__name__)

DASHBOARD_TITLE_FONT = ("DIN Alternate", 28)
DASHBOARD_LABEL_FONT = ("DIN Alternate", 32)
DASHBOARD_DATA_FONT = ("DIN Alternate", 48)


class Dashboard(ctk.CTkFrame):
    def __init__(self, parent, controller: ProjectController):
        super().__init__(parent)
        self.parent = parent
        self.controller = controller
        self.create_widgets()
        self.update_dashboard()

    def query_button_click(self):
        logger.info(f"query_button_click")
        if self.controller.echo("QUERY"):
            self.query_button.configure(text_color="light green")
            self.parent.master.query_retrieve()
        else:
            self.query_button.configure(text_color="red")

    def export_button_click(self):
        logger.info(f"export_button_click")
        if self.controller.echo("EXPORT"):
            self.export_button.configure(text_color="light green")
            self.parent.master.export()
        else:
            self.export_button.configure(text_color="red")

    def create_widgets(self):
        PAD = 20
        # TODO: manage fonts using theme

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
            self.parent, width=100, text=_("Query"), command=self.query_button_click
        )
        self.query_button.grid(row=row, column=0, padx=PAD, pady=(PAD, 0), sticky="w")

        self.export_button = ctk.CTkButton(
            self.parent, width=100, text=_("Export"), command=self.export_button_click
        )
        self.export_button.grid(row=row, column=3, padx=PAD, pady=(PAD, 0), sticky="e")

        row += 1

        self._databoard = ctk.CTkFrame(self.parent)
        db_row = 0

        self.label_patients = ctk.CTkLabel(
            self._databoard, font=DASHBOARD_LABEL_FONT, text="Patients"
        )
        self.label_studies = ctk.CTkLabel(
            self._databoard, font=DASHBOARD_LABEL_FONT, text="Studies"
        )
        self.label_series = ctk.CTkLabel(
            self._databoard, font=DASHBOARD_LABEL_FONT, text="Series"
        )
        self.label_images = ctk.CTkLabel(
            self._databoard, font=DASHBOARD_LABEL_FONT, text="Images"
        )

        self.label_patients.grid(row=db_row, column=0, padx=PAD, pady=(PAD, 0))
        self.label_studies.grid(row=db_row, column=1, padx=PAD, pady=(PAD, 0))
        self.label_series.grid(row=db_row, column=2, padx=PAD, pady=(PAD, 0))
        self.label_images.grid(row=db_row, column=3, padx=PAD, pady=(PAD, 0))

        db_row += 1

        self._patients = ctk.CTkLabel(
            self._databoard, font=DASHBOARD_DATA_FONT, text="0"
        )
        self._studies = ctk.CTkLabel(
            self._databoard, font=DASHBOARD_DATA_FONT, text="0"
        )
        self._series = ctk.CTkLabel(self._databoard, font=DASHBOARD_DATA_FONT, text="0")
        self._images = ctk.CTkLabel(self._databoard, font=DASHBOARD_DATA_FONT, text="0")

        self._patients.grid(row=db_row, column=0, padx=PAD, pady=(0, PAD))
        self._studies.grid(row=db_row, column=1, padx=PAD, pady=(0, PAD))
        self._series.grid(row=db_row, column=2, padx=PAD, pady=(0, PAD))
        self._images.grid(row=db_row, column=3, padx=PAD, pady=(0, PAD))

        self._databoard.grid(
            row=row, column=0, columnspan=4, padx=PAD, pady=PAD, sticky="n"
        )

    def update_dashboard(self):
        # if self.controller.echo("QUERY"):
        #     self.query_button.configure(text_color="light green")
        # else:
        #     self.query_button.configure(text_color="red")

        # if self.controller.echo("EXPORT"):
        #     self.export_button.configure(text_color="light green")
        # else:
        #     self.export_button.configure(text_color="red")

        dir = self.controller.model.storage_dir
        pts = os.listdir(dir)
        pts = [item for item in pts if not item.endswith(".pkl")]
        studies = 0
        series = 0
        images = 0

        for pt in pts:
            study_count, series_count, file_count = count_studies_series_images(
                os.path.join(dir, pt)
            )
            studies += study_count
            series += series_count
            images += file_count

        self._patients.configure(text=f"{len(pts)}")
        self._studies.configure(text=f"{studies}")
        self._series.configure(text=f"{series}")
        self._images.configure(text=f"{images}")

        self.after(500, self.update_dashboard)
