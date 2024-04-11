import os
import logging
from queue import Queue
import customtkinter as ctk
from tkinter import messagebox
from controller.project import ProjectController
from utils.translate import _
from utils.storage import count_studies_series_images
from view.progress_dialog import ProgressDialog

logger = logging.getLogger(__name__)


class Dashboard(ctk.CTkFrame):
    DASHBOARD_UPDATE_INTERVAL = 500  # milliseconds
    AWS_AUTH_TIMEOUT = 10  # seconds

    # TODO: manage fonts using theme manager
    TITLE_FONT = ("DIN Alternate", 28)
    LABEL_FONT = ("DIN Alternate Italic", 32)
    DATA_FONT = ("DIN Alternate", 48)
    PAD = 20
    button_width = 100

    def __init__(self, parent: ctk.CTk, controller: ProjectController):
        super().__init__(master=parent)
        self._parent = parent
        self._last_qsize = 0
        self._latch_max_qsize = 1
        self._controller = controller
        self._timer = 0
        self._create_widgets()
        self.grid(row=0, column=0, padx=self.PAD, pady=self.PAD)
        self._update_dashboard()

    def _create_widgets(self):
        logger.debug(f"_create_widgets")

        row = 0

        self._query_button = ctk.CTkButton(
            self,
            width=self.button_width,
            text=_("Query"),
            command=self._query_button_click,
        )
        self._query_button.grid(row=row, column=0, padx=self.PAD, pady=(self.PAD, 0), sticky="w")

        self._export_button = ctk.CTkButton(
            self,
            width=self.button_width,
            text=_("Export"),
            command=self._export_button_click,
        )
        self._export_button.grid(row=row, column=3, padx=self.PAD, pady=(self.PAD, 0), sticky="e")

        row += 1

        self._databoard = ctk.CTkFrame(self)
        db_row = 0

        self._label_patients = ctk.CTkLabel(self._databoard, font=self.LABEL_FONT, text=_("Patients"))
        self._label_studies = ctk.CTkLabel(self._databoard, font=self.LABEL_FONT, text=_("Studies"))
        self._label_series = ctk.CTkLabel(self._databoard, font=self.LABEL_FONT, text=_("Series"))
        self._label_images = ctk.CTkLabel(self._databoard, font=self.LABEL_FONT, text=_("Images"))

        self._label_patients.grid(row=db_row, column=0, padx=self.PAD, pady=(self.PAD, 0))
        self._label_studies.grid(row=db_row, column=1, padx=self.PAD, pady=(self.PAD, 0))
        self._label_series.grid(row=db_row, column=2, padx=self.PAD, pady=(self.PAD, 0))
        self._label_images.grid(row=db_row, column=3, padx=self.PAD, pady=(self.PAD, 0))

        db_row += 1

        self._patients = ctk.CTkLabel(self._databoard, font=self.DATA_FONT, text="0")
        self._studies = ctk.CTkLabel(self._databoard, font=self.DATA_FONT, text="0")
        self._series = ctk.CTkLabel(self._databoard, font=self.DATA_FONT, text="0")
        self._images = ctk.CTkLabel(self._databoard, font=self.DATA_FONT, text="0")

        self._patients.grid(row=db_row, column=0, padx=self.PAD, pady=(0, self.PAD))
        self._studies.grid(row=db_row, column=1, padx=self.PAD, pady=(0, self.PAD))
        self._series.grid(row=db_row, column=2, padx=self.PAD, pady=(0, self.PAD))
        self._images.grid(row=db_row, column=3, padx=self.PAD, pady=(0, self.PAD))

        self._databoard.grid(
            row=row,
            column=0,
            columnspan=4,
            padx=self.PAD,
            pady=(self.PAD, 0),
            sticky="n",
        )

        row += 1

        self._status_frame = ctk.CTkFrame(self)
        self._status_frame.columnconfigure(3, weight=1)
        self._status_frame.grid(
            row=row,
            column=0,
            columnspan=4,
            sticky="nsew",
            padx=self.PAD,
            pady=(self.PAD, 0),
        )

        self.label_queue = ctk.CTkLabel(self._status_frame, text="Anonymizer Queue:")
        self.label_queue.grid(row=0, column=0, padx=self.PAD, sticky="w")

        self._qsize = ctk.CTkLabel(self._status_frame, text="0")
        self._qsize.grid(row=0, column=1, sticky="w")

        # self.label_status = ctk.CTkLabel(self._status_frame, text="Status:")
        # self.label_status.grid(row=0, column=2, padx=self.PAD, sticky="w")

        self._status = ctk.CTkLabel(self._status_frame, text="")
        self._status.grid(row=0, column=3, padx=self.PAD, sticky="e")

    def _query_button_click(self):
        logger.info(f"_query_button_click")
        # This blocks for TCP connection timeout
        if not self._controller.echo("QUERY"):
            self._query_button.configure(text_color="red")
            messagebox.showerror(
                title=_("Connection Error"),
                message=_(
                    f"Query Server Failed DICOM C-ECHO, check Project Settings/Query Server"
                    " and ensure server is setup for local server: echo, query & move services."
                ),
                parent=self,
            )
            return
        self._query_button.configure(text_color="light green")
        self._parent.query_retrieve()

    def _export_button_click(self):
        logger.info(f"_export_button_click")
        # This blocks for TCP connection timeout
        # TODO: create background task for this, how to notify user of status?
        if self._controller.model.export_to_AWS:
            if not self._controller.AWS_credentials_valid():
                self._controller.AWS_authenticate_ex()  # Authenticate to AWS in background
                # Wait for up to AWS_AUTH_TIMEOUT for AWS response
                self._timer = self.AWS_AUTH_TIMEOUT
                self.after(1000, self._wait_for_aws)
                self._status.configure(text="Waiting for AWS Authentication...")
                return

        if not self._controller.echo("EXPORT"):
            self._export_button.configure(text_color="red")
            messagebox.showerror(
                title=_("Connection Error"),
                message=_(
                    f"Export Server Failed DICOM C-ECHO, check Project Settings/Export Server"
                    " and ensure server is setup for local server: echo and storage services."
                ),
                parent=self,
            )
            return
        self._export_button.configure(text_color="light green")
        self._parent.export()

    def _wait_for_aws(self):
        self._timer -= 1
        if self._timer == 0:
            self._export_button.configure(text_color="red")
            messagebox.showerror(
                title=_("Connection Error"),
                message=_(
                    f"AWS Authentication Failed:\n\n{self._controller._aws_last_error}"
                    "\n\nCheck Project Settings/AWS Cognito and ensure all parameters are correct."
                ),
                parent=self,
            )
            self._status.configure(text="")
            return

        if self._controller.AWS_credentials_valid():
            self._export_button.configure(text_color="light green")
            self._parent.export()
            self._status.configure(text="AWS Authenticated")
            return

        self.after(1000, self._wait_for_aws)

    def _update_dashboard(self):
        if not self._controller:
            return

        dir = self._controller.model.storage_dir
        pts = os.listdir(dir)
        pts = [item for item in pts if os.path.isdir(os.path.join(dir, item))]
        studies = 0
        series = 0
        images = 0

        for pt in pts:
            study_count, series_count, file_count = count_studies_series_images(os.path.join(dir, pt))
            studies += study_count
            series += series_count
            images += file_count

        self._patients.configure(text=f"{len(pts)}")
        self._studies.configure(text=f"{studies}")
        self._series.configure(text=f"{series}")
        self._images.configure(text=f"{images}")

        if self._controller and self._controller.anonymizer:
            self._qsize.configure(text=f"{self._controller.anonymizer._anon_Q.qsize()}")
            self.after(self.DASHBOARD_UPDATE_INTERVAL, self._update_dashboard)
