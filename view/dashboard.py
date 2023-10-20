import os
import logging
from turtle import st
import customtkinter as ctk
from CTkMessagebox import CTkMessagebox
from controller.project import ProjectController
from utils.translate import _
from utils.storage import count_studies_series_images


logger = logging.getLogger(__name__)

DASHBOARD_TITLE_FONT = ("DIN Alternate", 28)
DASHBOARD_LABEL_FONT = ("DIN Alternate Italic", 32)
DASHBOARD_DATA_FONT = ("DIN Alternate", 48)


class Dashboard(ctk.CTkFrame):
    dashboard_update_interval = 500  # milliseconds

    def __init__(self, parent, controller: ProjectController):
        super().__init__(parent)
        self._parent = parent
        self._last_qsize = 0
        self._latch_max_qsize = 1
        self._controller = controller
        self._create_widgets()
        self._update_dashboard()

    def _query_button_click(self):
        logger.info(f"_query_button_click")
        # This blocks for TCP connection timeout
        if not self._controller.echo("QUERY"):
            self._query_button.configure(text_color="red")
            CTkMessagebox(
                title=_("Connection Error"),
                message=_(
                    f"Query Server Failed DICOM C-ECHO, check Project Settings/Query Server"
                    " and ensure server is setup for local server: echo, query & move services."
                ),
                icon="cancel",
            )
            return
        self._query_button.configure(text_color="light green")
        self._parent.master.query_retrieve()

    def _export_button_click(self):
        logger.info(f"_export_button_click")
        # This blocks for TCP connection timeout
        if not self._controller.echo("EXPORT"):
            self._export_button.configure(text_color="red")
            CTkMessagebox(
                title=_("Connection Error"),
                message=_(
                    f"Export Server Failed DICOM C-ECHO, check Project Settings/Export Server"
                    " and ensure server is setup for local server: echo and storage services."
                ),
                icon="cancel",
            )
            return
        self._export_button.configure(text_color="light green")
        self._parent.master.export()

    def _create_widgets(self):
        logger.debug(f"_create_widgets")
        PAD = 20
        # TODO: manage fonts using theme

        row = 0

        self._query_button = ctk.CTkButton(
            self._parent, width=100, text=_("Query"), command=self._query_button_click
        )
        self._query_button.grid(row=row, column=0, padx=PAD, pady=(PAD, 0), sticky="w")

        self._export_button = ctk.CTkButton(
            self._parent, width=100, text=_("Export"), command=self._export_button_click
        )
        self._export_button.grid(row=row, column=3, padx=PAD, pady=(PAD, 0), sticky="e")

        row += 1

        self._databoard = ctk.CTkFrame(self._parent)
        db_row = 0

        self._label_patients = ctk.CTkLabel(
            self._databoard, font=DASHBOARD_LABEL_FONT, text=_("Patients")
        )
        self._label_studies = ctk.CTkLabel(
            self._databoard, font=DASHBOARD_LABEL_FONT, text=_("Studies")
        )
        self._label_series = ctk.CTkLabel(
            self._databoard, font=DASHBOARD_LABEL_FONT, text=_("Series")
        )
        self._label_images = ctk.CTkLabel(
            self._databoard, font=DASHBOARD_LABEL_FONT, text=_("Images")
        )

        self._label_patients.grid(row=db_row, column=0, padx=PAD, pady=(PAD, 0))
        self._label_studies.grid(row=db_row, column=1, padx=PAD, pady=(PAD, 0))
        self._label_series.grid(row=db_row, column=2, padx=PAD, pady=(PAD, 0))
        self._label_images.grid(row=db_row, column=3, padx=PAD, pady=(PAD, 0))

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

        row += 1

        self._status_frame = ctk.CTkFrame(self._parent)

        self.label_queue = ctk.CTkLabel(self._status_frame, text="Anonymizer Queue:")
        self.label_queue.grid(row=0, column=0, padx=PAD, sticky="w")

        self._qsize = ctk.CTkLabel(self._status_frame, text="0")
        self._qsize.grid(row=0, column=1, sticky="w")

        self._status_frame.grid(
            row=row, column=0, columnspan=4, sticky="nsew", padx=PAD
        )

    def _update_dashboard(self):
        dir = self._controller.model.storage_dir
        pts = os.listdir(dir)
        pts = [item for item in pts if os.path.isdir(os.path.join(dir, item))]
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

        self._qsize.configure(text=f"{self._controller.anonymizer._anon_Q.qsize()}")

        self.after(self.dashboard_update_interval, self._update_dashboard)
