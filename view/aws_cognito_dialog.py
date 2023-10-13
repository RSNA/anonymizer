from typing import Union, Tuple
import customtkinter as ctk
import string
import logging
from model.project import AWSCognito
from utils.translate import _
from utils.ux_fields import str_entry

logger = logging.getLogger(__name__)


class AWSCognitoDialog(ctk.CTkToplevel):
    def __init__(
        self,
        export_to_aws: bool,
        aws_cognito: AWSCognito,
        title: str = _("AWS Cognito Credentials for Export to S3"),
    ):
        super().__init__()
        self.aws_cognito = aws_cognito
        self.export_to_aws = export_to_aws
        self.title(title)
        self.lift()  # lift window on top
        self.attributes("-topmost", True)  # stay on top
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.resizable(False, False)
        self.grab_set()  # make dialog modal
        self._user_input = None
        self._create_widgets()

    @property
    def user_input(self) -> Union[Tuple[bool, AWSCognito], None]:
        return self._user_input

    def _create_widgets(self):
        logger.info(f"_create_widgets")
        PAD = 10

        char_width_px = ctk.CTkFont().measure("A")
        logger.info(f"Font Character Width in pixels: ±{char_width_px}")

        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

        row = 0

        self.client_id_var = str_entry(
            view=self,
            label=_("Client ID:"),
            initial_value=self.aws_cognito.client_id,
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
            view=self,
            label=_("S3 Bucket:"),
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
            view=self,
            label=_("S3 Prefix:"),
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

        row += 1

        self.username_var = str_entry(
            view=self,
            label=_("Username:"),
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
            view=self,
            label=_("Password:"),
            initial_value=self.aws_cognito.password,
            min_chars=6,
            max_chars=64,
            charset=string.ascii_letters + string.digits + " !#$%&()#*+-.,:;_^@?~|",
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        row += 1

        self._export_to_aws_checkbox = ctk.CTkCheckBox(self, text=_("Export to AWS"))
        if self.export_to_aws:
            self._export_to_aws_checkbox.select()

        self._export_to_aws_checkbox.grid(
            row=row,
            column=0,
            padx=PAD,
            pady=PAD,
            sticky="w",
        )

        self._ok_button = ctk.CTkButton(
            self, width=100, text=_("Ok"), command=self._ok_event
        )
        self._ok_button.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=PAD,
            sticky="e",
        )

    def _ok_event(self, event=None):
        self._user_input = (
            self._export_to_aws_checkbox.get() == 1,
            AWSCognito(
                self.client_id_var.get(),
                self.s3_bucket_var.get(),
                self.s3_prefix_var.get(),
                self.username_var.get(),
                self.password_var.get(),
            ),
        )
        self.grab_release()
        self.destroy()

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def get_input(self):
        self.master.wait_window(self)
        return self._user_input
