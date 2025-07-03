import logging
import os
from queue import Queue
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from anonymizer.controller.project import EchoRequest, EchoResponse, ProjectController
from anonymizer.model.anonymizer import Totals
from anonymizer.utils.storage import count_quarantine_images, count_studies_series_images
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class Dashboard(ctk.CTkFrame):
    """
    A class representing the dashboard view of the anonymizer application.

    Args:
        parent: The parent widget.
        query_callback: The callback function for the query button.
        export_callback: The callback function for the export button.
        controller: The project controller.

    Attributes:
        AWS_AUTH_TIMEOUT_SECONDS (int): The timeout duration for AWS authentication.
        LABEL_FONT_SIZE (int): The font size for labels.
        DATA_FONT_SIZE (int): The font size for data.
        PAD (int): The padding value.
        BUTTON_WIDTH (int): The width of buttons.
        _label_font (ctk.CTkFont): The font for labels.
        _data_font (ctk.CTkFont): The font for data.
        _last_qsize (int): The previous size of the queue.
        _latch_max_qsize (int): The maximum size of the queue.
        _query_callback (Any): The callback function for the query button.
        _export_callback (Any): The callback function for the export button.
        _controller (ProjectController): The project controller.
        _timer (int): The timer for AWS authentication.
        _query_ux_Q (Queue[EchoResponse]): The queue for query responses.
        _export_ux_Q (Queue[EchoResponse]): The queue for export responses.
        _patients (int): The number of patients.
        _studies (int): The number of studies.
        _series (int): The number of series.
        _images (int): The number of images.
    """

    AWS_AUTH_TIMEOUT_SECONDS = 15  # must be > 2 secs
    LABEL_FONT_SIZE = 32
    DATA_FONT_SIZE = 48
    PAD = 20
    BUTTON_WIDTH = 100

    def __init__(self, parent, query_callback, export_callback, view_callback, controller: ProjectController):
        super().__init__(master=parent)
        self._label_font = ctk.CTkFont(
            family=ctk.CTkFont().cget("family"),
            size=self.LABEL_FONT_SIZE,
            weight="normal",
        )
        self._data_font = ctk.CTkFont(
            family=parent.mono_font.cget("family"),
            size=self.DATA_FONT_SIZE,
            weight="normal",
        )
        self._mono_font = parent.mono_font
        self._last_qsize = 0
        self._latch_max_qsize = 1
        self._query_callback = query_callback
        self._export_callback = export_callback
        self._view_callback = view_callback
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
        logger.debug("_create_widgets")

        row = 0

        self._query_button = ctk.CTkButton(
            self,
            width=self.BUTTON_WIDTH,
            text=_("Search"),
            command=self._query_button_click,
        )
        self._query_button.grid(row=row, column=0, padx=self.PAD, pady=(self.PAD, 0), sticky="w")

        self._view_button = ctk.CTkButton(
            self,
            width=self.BUTTON_WIDTH,
            text=_("View"),
            command=self._view_button_click,
        )
        self._view_button.grid(row=row, column=1, padx=self.PAD, pady=(self.PAD, 0), sticky="e")

        self._send_button = ctk.CTkButton(
            self,
            width=self.BUTTON_WIDTH,
            text=_("Send"),
            command=self._send_button_click,
        )
        self._send_button.grid(row=row, column=3, padx=self.PAD, pady=(self.PAD, 0), sticky="e")

        row += 1

        self._databoard = ctk.CTkFrame(self)
        db_row = 0

        self._label_patients = ctk.CTkLabel(self._databoard, font=self._label_font, text=_("Patients"))
        self._label_studies = ctk.CTkLabel(self._databoard, font=self._label_font, text=_("Studies"))
        self._label_series = ctk.CTkLabel(self._databoard, font=self._label_font, text=_("Series"))
        self._label_images = ctk.CTkLabel(self._databoard, font=self._label_font, text=_("Images"))
        self._label_quarantine = ctk.CTkLabel(self._databoard, font=self._label_font, text=_("Quarantine"))

        self._label_patients.grid(row=db_row, column=0, padx=self.PAD, pady=(self.PAD, 0))
        self._label_studies.grid(row=db_row, column=1, padx=self.PAD, pady=(self.PAD, 0))
        self._label_series.grid(row=db_row, column=2, padx=self.PAD, pady=(self.PAD, 0))
        self._label_images.grid(row=db_row, column=3, padx=self.PAD, pady=(self.PAD, 0))
        self._label_quarantine.grid(row=db_row, column=4, padx=self.PAD, pady=(self.PAD, 0))

        db_row += 1

        self._patients_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")
        self._studies_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")
        self._series_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")
        self._images_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")
        self._quarantined_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")

        self._patients_label.grid(row=db_row, column=0, padx=self.PAD, pady=(0, self.PAD))
        self._studies_label.grid(row=db_row, column=1, padx=self.PAD, pady=(0, self.PAD))
        self._series_label.grid(row=db_row, column=2, padx=self.PAD, pady=(0, self.PAD))
        self._images_label.grid(row=db_row, column=3, padx=self.PAD, pady=(0, self.PAD))
        self._quarantined_label.grid(row=db_row, column=4, padx=self.PAD, pady=(0, self.PAD))

        db_row += 1

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

        self.label_metadata_queue = ctk.CTkLabel(self._status_frame, text=_("Metadata Queue") + ":")
        self.label_metadata_queue.grid(row=0, column=0, padx=self.PAD, sticky="w")

        self._meta_qsize = ctk.CTkLabel(self._status_frame, text="0")
        self._meta_qsize.grid(row=0, column=1, sticky="w")

        if self._controller.model.remove_pixel_phi:
            self.label_pixel_queue = ctk.CTkLabel(self._status_frame, text=_("Pixel PHI Queue") + ":")
            self.label_pixel_queue.grid(row=0, column=2, padx=self.PAD, sticky="w")

            self._pixel_qsize = ctk.CTkLabel(self._status_frame, text="0")
            self._pixel_qsize.grid(row=0, column=3, sticky="w")

        self._status = ctk.CTkLabel(self._status_frame, text="")
        self._status.grid(row=0, column=4, padx=self.PAD, sticky="e")

    def _wait_for_scp_echo(
        self,
        scp_name: str,
        button: ctk.CTkButton,
        ux_Q: Queue[EchoResponse],
        callback: Any,
    ):
        if ux_Q.empty():
            self.after(500, self._wait_for_scp_echo, scp_name, button, ux_Q, callback)
            return

        er: EchoResponse = ux_Q.get()
        logger.info(er)
        if er.success:
            button.configure(state="normal", text_color="light green")
            self._status.configure(text=f"{scp_name} " + _("online"))
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
            self._status.configure(text=f"{scp_name} " + _("offline"))
            button.configure(state="normal", text_color="red")

    def set_status(self, text: str):
        self._status.configure(text=text)

    def _query_button_click(self):
        logger.info("_query_button_click")
        self._query_button.configure(state="disabled")
        self._controller.echo_ex(EchoRequest(scp=_("QUERY"), ux_Q=self._query_ux_Q))
        self.after(
            500,
            self._wait_for_scp_echo,
            _("Query Server"),
            self._query_button,
            self._query_ux_Q,
            self._query_callback,
        )
        self._status.configure(text=_("Checking Query DICOM Server is online") + "...")

    def _send_button_click(self):
        logger.info("_export_button_click")
        self._send_button.configure(state="disabled")

        if self._controller.model.export_to_AWS:
            self._controller.AWS_authenticate_ex()  # Authenticate to AWS in background
            self._timer = self.AWS_AUTH_TIMEOUT_SECONDS
            self.after(1000, self._wait_for_aws)
            self._status.configure(text=_("Waiting for AWS Authentication") + "...")
        else:
            self._controller.echo_ex(EchoRequest(scp="EXPORT", ux_Q=self._export_ux_Q))
            self.after(
                1000,
                self._wait_for_scp_echo,
                _("Export Server"),
                self._send_button,
                self._export_ux_Q,
                self._export_callback,
            )
            self._status.configure(text=_("Checking Export DICOM Server is online") + "...")

    def _view_button_click(self):
        logger.info("_view_button_click")
        self._view_callback()

    def _wait_for_aws(self):
        self._timer -= 1
        if self._timer <= 0 or self._controller._aws_last_error:  # Error or TIMEOUT
            if self._controller._aws_last_error is None:
                self._controller._aws_last_error = "AWS Response Timeout"
            messagebox.showerror(
                title=_("Connection Error"),
                message=_("AWS Authentication Failed")
                + ":"
                + f"\n\n{self._controller._aws_last_error}"
                + "\n\n"
                + _("Check Project Settings/AWS Cognito and ensure all parameters are correct."),
                parent=self,
            )
            self._status.configure(text="")
            self._send_button.configure(state="normal", text_color="red")
            return

        if self._controller.AWS_credentials_valid():
            self._send_button.configure(state="normal", text_color="light green")
            self._export_callback()
            self._status.configure(text=_("AWS Authenticated"))
            return

        self.after(1000, self._wait_for_aws)

    def update_anonymizer_queues(self, ds_Q_size: int, px_Q_size: int):
        self._meta_qsize.configure(text=f"{ds_Q_size}")
        if hasattr(self, "_pixel_qsize"):
            self._pixel_qsize.configure(text=f"{px_Q_size}")

    def update_totals(self, totals: Totals):
        self._patients_label.configure(text=f"{totals.patients}")
        self._studies_label.configure(text=f"{totals.studies}")
        self._series_label.configure(text=f"{totals.series}")
        self._images_label.configure(text=f"{totals.instances}")
        self._quarantined_label.configure(
            text=f"{count_quarantine_images(self._controller.anonymizer.get_quarantine_path())}"
        )

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
