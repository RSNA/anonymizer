import logging
import string
import tkinter as tk
from typing import Tuple, Union

import customtkinter as ctk

from anonymizer.model.project import AWSCognito
from anonymizer.utils.translate import _
from anonymizer.view.ux_fields import str_entry

logger = logging.getLogger(__name__)


class AWSCognitoDialog(tk.Toplevel):
    """
    A dialog window for entering AWS Cognito credentials for exporting to S3.

    Args:
        parent: The parent widget.
        export_to_aws (bool): Flag indicating whether to export to AWS.
        aws_cognito (AWSCognito): An instance of the AWSCognito class.

    Attributes:
        user_input (Union[Tuple[bool, AWSCognito], None]): The user input containing the export flag and AWSCognito instance.

    Methods:
        _create_widgets: Create the widgets for the dialog.
        _enter_keypress: Event handler for the Enter key press.
        _ok_event: Event handler for the Ok button click.
        _escape_keypress: Event handler for the Escape key press.
        _on_cancel: Event handler for canceling the dialog.
        get_input: Get the user input from the dialog.
    """

    def __init__(
        self,
        parent,
        export_to_aws: bool,
        aws_cognito: AWSCognito,
    ):
        super().__init__(master=parent)
        self.aws_cognito = aws_cognito
        self.export_to_aws = export_to_aws
        self.title(_("AWS Cognito Credentials for Export to S3"))
        self.resizable(False, False)
        self._user_input: Union[Tuple[bool, AWSCognito], None] = None
        self._create_widgets()
        self.wait_visibility()
        self.lift()
        self.grab_set()  # make dialog modal
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)

    @property
    def user_input(self) -> Union[Tuple[bool, AWSCognito], None]:
        return self._user_input

    def _create_widgets(self):
        logger.info("_create_widgets")
        PAD = 10

        char_width_px = ctk.CTkFont().measure("A")
        logger.info(f"Font Character Width in pixels: ±{char_width_px}")

        self._frame = ctk.CTkFrame(self)
        self._frame.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nswe")

        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

        row = 0

        self.account_id_var = str_entry(
            view=self._frame,
            label=_("AWS Account ID") + ":",
            initial_value=self.aws_cognito.account_id,
            min_chars=1,
            max_chars=64,
            charset=string.digits + "-. ^%$@!~+*&" + string.ascii_letters,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        row += 1

        self.region_name_var = str_entry(
            view=self._frame,
            label=_("Region Name") + ":",
            initial_value=self.aws_cognito.region_name,
            min_chars=5,
            max_chars=64,
            charset=string.digits + "-" + string.ascii_lowercase,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        row += 1

        self.app_client_id_var = str_entry(
            view=self._frame,
            label=_("Cognito Application Client ID") + ":",
            initial_value=self.aws_cognito.app_client_id,
            min_chars=5,
            max_chars=64,
            charset=string.digits + "-_" + string.ascii_letters,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        row += 1

        self.user_pool_id_var = str_entry(
            view=self._frame,
            label=_("Cognito User Pool ID") + ":",
            initial_value=self.aws_cognito.user_pool_id,
            min_chars=5,
            max_chars=64,
            charset=string.digits + "-_" + string.ascii_letters,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        row += 1

        self.identity_pool_id_var = str_entry(
            view=self._frame,
            label=_("Cognito Identity Pool ID") + ":",
            initial_value=self.aws_cognito.identity_pool_id,
            min_chars=5,
            max_chars=64,
            charset=string.digits + "-_" + string.ascii_letters,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        row += 1

        self.s3_bucket_var = str_entry(
            view=self._frame,
            label=_("S3 Bucket") + ":",
            initial_value=self.aws_cognito.s3_bucket,
            min_chars=5,
            max_chars=64,
            charset=string.digits + "-." + string.ascii_lowercase,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        row += 1

        self.s3_prefix_var = str_entry(
            view=self._frame,
            label=_("S3 Prefix") + ":",
            initial_value=self.aws_cognito.s3_prefix,
            min_chars=1,
            max_chars=64,
            charset=string.digits + "-. ^%$@!~+*&" + string.ascii_letters,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        # TODO: include check box for private user sub-directory via get_user UserAttributes = "sub" value

        row += 1

        self.username_var = str_entry(
            view=self._frame,
            label=_("Username") + ":",
            initial_value=self.aws_cognito.username,
            min_chars=3,
            max_chars=64,
            charset=string.digits + "-_." + string.ascii_letters,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        row += 1

        self.password_var = str_entry(
            view=self._frame,
            label=_("Password") + ":",
            initial_value=self.aws_cognito.password,
            min_chars=6,
            max_chars=64,
            charset=string.ascii_letters + string.digits + " !#$%&()#*+-.,:;_^@?~|",
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
            password=True,
        )

        row += 1

        export_to_aws_label = ctk.CTkLabel(self._frame, text=_("Export to AWS") + ":")
        export_to_aws_label.grid(row=row, column=0, padx=PAD, pady=(PAD, 0), sticky="nw")

        self._export_to_aws_checkbox = ctk.CTkCheckBox(self._frame, text="")
        if self.export_to_aws:
            self._export_to_aws_checkbox.select()

        self._export_to_aws_checkbox.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=PAD,
            sticky="w",
        )

        self._ok_button = ctk.CTkButton(self._frame, width=100, text=_("Ok"), command=self._ok_event)
        self._ok_button.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=PAD,
            sticky="e",
        )

    def _enter_keypress(self, event):
        logger.info("_enter_pressed")
        self._ok_event()

    def _ok_event(self, event=None):
        self._user_input = (
            self._export_to_aws_checkbox.get() == 1,
            AWSCognito(
                self.account_id_var.get(),
                self.region_name_var.get(),
                self.app_client_id_var.get(),
                self.user_pool_id_var.get(),
                self.identity_pool_id_var.get(),
                self.s3_bucket_var.get(),
                self.s3_prefix_var.get(),
                self.username_var.get(),
                self.password_var.get(),
            ),
        )
        self.grab_release()
        self.destroy()

    def _escape_keypress(self, event):
        logger.info("_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def get_input(self):
        self.focus()
        self.master.wait_window(self)
        return self._user_input
