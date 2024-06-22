import os
import logging
from queue import Queue
from typing import Any
import customtkinter as ctk
from tkinter import messagebox
from controller.project import ProjectController, EchoRequest, EchoResponse
from model.anonymizer import Totals
from utils.translate import _
from utils.storage import count_studies_series_images

logger = logging.getLogger(__name__)


class Dashboard(ctk.CTkFrame):
    AWS_AUTH_TIMEOUT_SECONDS = 15  # must be > 2 secs
    LABEL_FONT_SIZE = 32
    DATA_FONT_SIZE = 48
    PAD = 20
    BUTTON_WIDTH = 100

    def __init__(self, parent, query_callback, export_callback, controller: ProjectController):
        super().__init__(master=parent)
        self._label_font = ctk.CTkFont(family=ctk.CTkFont().cget("family"), size=self.LABEL_FONT_SIZE, weight="normal")
        self._data_font = ctk.CTkFont(family=parent.mono_font.cget("family"), size=self.DATA_FONT_SIZE, weight="normal")
        self._last_qsize = 0
        self._latch_max_qsize = 1
        self._query_callback = query_callback
        self._export_callback = export_callback
        self._controller: ProjectController = controller
        self._timer = 0
        self._query_ux_Q: Queue[EchoResponse] = Queue()
        self._export_ux_Q: Queue[EchoResponse] = Queue()
        self._patients = 0
        self._studies = 0
        self._series = 0
        self._images = 0
        self._create_widgets()
        self.grid(row=0, column=0, padx=self.PAD, pady=self.PAD)

    def _create_widgets(self):
        logger.debug(f"_create_widgets")

        row = 0

        self._query_button = ctk.CTkButton(
            self,
            width=self.BUTTON_WIDTH,
            text=_("Query"),
            command=self._query_button_click,
        )
        self._query_button.grid(row=row, column=0, padx=self.PAD, pady=(self.PAD, 0), sticky="w")

        self._export_button = ctk.CTkButton(
            self,
            width=self.BUTTON_WIDTH,
            text=_("Export"),
            command=self._export_button_click,
        )
        self._export_button.grid(row=row, column=3, padx=self.PAD, pady=(self.PAD, 0), sticky="e")

        row += 1

        self._databoard = ctk.CTkFrame(self)
        db_row = 0

        self._label_patients = ctk.CTkLabel(self._databoard, font=self._label_font, text=_("Patients"))
        self._label_studies = ctk.CTkLabel(self._databoard, font=self._label_font, text=_("Studies"))
        self._label_series = ctk.CTkLabel(self._databoard, font=self._label_font, text=_("Series"))
        self._label_images = ctk.CTkLabel(self._databoard, font=self._label_font, text=_("Images"))

        self._label_patients.grid(row=db_row, column=0, padx=self.PAD, pady=(self.PAD, 0))
        self._label_studies.grid(row=db_row, column=1, padx=self.PAD, pady=(self.PAD, 0))
        self._label_series.grid(row=db_row, column=2, padx=self.PAD, pady=(self.PAD, 0))
        self._label_images.grid(row=db_row, column=3, padx=self.PAD, pady=(self.PAD, 0))

        db_row += 1

        self._patients_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")
        self._studies_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")
        self._series_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")
        self._images_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")

        self._patients_label.grid(row=db_row, column=0, padx=self.PAD, pady=(0, self.PAD))
        self._studies_label.grid(row=db_row, column=1, padx=self.PAD, pady=(0, self.PAD))
        self._series_label.grid(row=db_row, column=2, padx=self.PAD, pady=(0, self.PAD))
        self._images_label.grid(row=db_row, column=3, padx=self.PAD, pady=(0, self.PAD))

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

        self.label_queue = ctk.CTkLabel(self._status_frame, text=_("Anonymizer Queue:"))
        self.label_queue.grid(row=0, column=0, padx=self.PAD, sticky="w")

        self._qsize = ctk.CTkLabel(self._status_frame, text="0")
        self._qsize.grid(row=0, column=1, sticky="w")

        self._status = ctk.CTkLabel(self._status_frame, text="")
        self._status.grid(row=0, column=3, padx=self.PAD, sticky="e")

    def _wait_for_scp_echo(self, scp_name: str, button: ctk.CTkButton, ux_Q: Queue[EchoResponse], callback: Any):
        if ux_Q.empty():
            self.after(500, self._wait_for_scp_echo, scp_name, button, ux_Q, callback)
            return

        er: EchoResponse = ux_Q.get()
        logger.info(er)
        if er.success:
            button.configure(state="normal", text_color="light green")
            self._status.configure(text=f"{scp_name} server online")
            callback()
        else:
            messagebox.showerror(
                title=_("Connection Error"),
                message=f"{scp_name} "
                + _("Server Failed DICOM ECHO")
                + "\n\n"
                + _("Check Project Settings")
                + f"/{scp_name} "
                + _("Server")
                + "\n\n"
                + _("Ensure the remote server is setup to allow the local server for echo and storage services."),
                parent=self,
            )
            self._status.configure(text=f"{scp_name} " + _("Server offline"))
            button.configure(state="normal", text_color="red")

    def set_status(self, text: str):
        self._status.configure(text=text)

    def _query_button_click(self):
        logger.info(f"_query_button_click")
        self._query_button.configure(state="disabled")
        self._controller.echo_ex(EchoRequest(scp="QUERY", ux_Q=self._query_ux_Q))
        self.after(500, self._wait_for_scp_echo, "Query", self._query_button, self._query_ux_Q, self._query_callback)
        self._status.configure(text=_("Checking Query DICOM Server is online..."))

    def _export_button_click(self):
        logger.info(f"_export_button_click")
        self._export_button.configure(state="disabled")

        if self._controller.model.export_to_AWS:
            self._controller.AWS_authenticate_ex()  # Authenticate to AWS in background
            self._timer = self.AWS_AUTH_TIMEOUT_SECONDS
            self.after(1000, self._wait_for_aws)
            self._status.configure(text=_("Waiting for AWS Authentication..."))
        else:
            self._controller.echo_ex(EchoRequest(scp="EXPORT", ux_Q=self._export_ux_Q))
            self.after(
                1000, self._wait_for_scp_echo, "Export", self._export_button, self._export_ux_Q, self._export_callback
            )
            self._status.configure(text=_("Checking Export DICOM Server is online..."))

    def _wait_for_aws(self):
        self._timer -= 1
        if self._timer <= 0:  # TIMEOUT
            if self._controller._aws_last_error is None:
                self._controller._aws_last_error = "AWS Response Timeout"
            messagebox.showerror(
                title=_("Connection Error"),
                message=_("AWS Authentication Failed:")
                + f"\n\n{self._controller._aws_last_error}"
                + "\n\n"
                + "Check Project Settings/AWS Cognito and ensure all parameters are correct.",
                parent=self,
            )
            self._status.configure(text="")
            self._export_button.configure(state="normal", text_color="red")
            return

        if self._controller.AWS_credentials_valid():
            self._export_button.configure(state="normal", text_color="light green")
            self._export_callback()
            self._status.configure(text=_("AWS Authenticated"))
            return

        self.after(1000, self._wait_for_aws)

    def update_anonymizer_queue(self, queue_size: int):
        self._qsize.configure(text=f"{queue_size}")

    def update_totals(self, totals: Totals):
        self._patients_label.configure(text=f"{totals.patients}")
        self._studies_label.configure(text=f"{totals.studies}")
        self._series_label.configure(text=f"{totals.series}")
        self._images_label.configure(text=f"{totals.instances}")

    def _update_dashboard_from_file_system(self):
        if not self._controller:
            return

        dir = self._controller.model.images_dir()
        pts = os.listdir(dir)
        pts = [item for item in pts if dir.joinpath(item).is_dir()]

        self._patients = len(pts)
        self._studies = 0
        self._series = 0
        self._images = 0

        for pt in pts:
            study_count, series_count, file_count = count_studies_series_images(os.path.join(dir, pt))
            self._studies += study_count
            self._series += series_count
            self._images += file_count

        self._patients_label.configure(text=f"{self._patients}")
        self._studies_label.configure(text=f"{self._studies}")
        self._series_label.configure(text=f"{self._series}")
        self._images_label.configure(text=f"{self._images}")
