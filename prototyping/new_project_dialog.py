import customtkinter as ctk
from tkinter import filedialog
import logging
from utils.translate import _
import model.config as config
from utils.ux_fields import validate_entry, int_entry_change, str_entry_change
from model.project import SITEID, PROJECTNAME, TRIALNAME, UIDROOT

logger = logging.getLogger(__name__)


# class CreateNewProjectDialog(ctk.CTkToplevel):
#     def __init__(self, parent, title=_("Create New Project")):
#         super().__init__(parent, title=title)
#         self.init_ui()


#     def init_ui(self):


#     def create_view(self, view: ctk.CTkFrame):
#         PAD = 10
#         min_chars = 3
#         max_chars = 20
#         logger.info(f"Creating new_open_project View")

#         char_width_px = ctk.CTkFont().measure("A")
#         validate_entry_cmd = view.register(validate_entry)
#         logger.info(f"Font Character Width in pixels: ±{char_width_px}")
#         view.grid_rowconfigure(0, weight=1)
#         view.grid_columnconfigure(2, weight=1)

#         # TODO: Paremeterize these entries
#         # SITEID Entry:
#         siteid_label = ctk.CTkLabel(view, text=_("SITE ID:"))
#         siteid_label.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nw")
#         siteid_var = ctk.StringVar(view, value=SITEID)
#         siteid_entry = ctk.CTkEntry(
#             view,
#             width=int(max_chars * char_width_px),
#             textvariable=siteid_var,
#             validate="key",
#             validatecommand=(
#                 validate_entry_cmd,
#                 "%P",
#                 string.digits + string.ascii_uppercase,
#                 str(max_chars),
#             ),
#         )
#         entry_callback = lambda event: str_entry_change(
#             event, siteid_var, min_chars, max_chars, __name__, "siteid"
#         )
#         siteid_entry.bind("<Return>", entry_callback)
#         siteid_entry.bind("<FocusOut>", entry_callback)
#         siteid_entry.grid(row=0, column=1, padx=PAD, pady=PAD, sticky="nw")

#         # PROJECTNAME Entry:
#         projectname_label = ctk.CTkLabel(view, text=_("PROJECT NAME:"))
#         projectname_label.grid(row=1, column=0, padx=PAD, pady=PAD, sticky="nw")
#         projectname_var = ctk.StringVar(view, value=PROJECTNAME)
#         projectname_entry = ctk.CTkEntry(
#             view,
#             width=int(max_chars * char_width_px),
#             textvariable=projectname_var,
#             validate="key",
#             validatecommand=(
#                 validate_entry_cmd,
#                 "%P",
#                 string.digits + string.ascii_uppercase,
#                 str(max_chars),
#             ),
#         )
#         entry_callback = lambda event: str_entry_change(
#             event, projectname_var, min_chars, max_chars, __name__, "projectname"
#         )
#         projectname_entry.bind("<Return>", entry_callback)
#         projectname_entry.bind("<FocusOut>", entry_callback)
#         projectname_entry.grid(row=1, column=1, padx=PAD, pady=PAD, sticky="nw")

#         # TRIALNAME Entry:
#         trialname_label = ctk.CTkLabel(view, text=_("TRIAL NAME:"))
#         trialname_label.grid(row=2, column=0, padx=PAD, pady=PAD, sticky="nw")
#         trialname_var = ctk.StringVar(view, value=TRIALNAME)
#         trialname_entry = ctk.CTkEntry(
#             view,
#             width=int(max_chars * char_width_px),
#             textvariable=trialname_var,
#             validate="key",
#             validatecommand=(
#                 validate_entry_cmd,
#                 "%P",
#                 string.digits + string.ascii_uppercase,
#                 str(max_chars),
#             ),
#         )
#         entry_callback = lambda event: str_entry_change(
#             event, trialname_var, min_chars, max_chars, __name__, "trialname"
#         )
#         trialname_entry.bind("<Return>", entry_callback)
#         trialname_entry.bind("<FocusOut>", entry_callback)
#         trialname_entry.grid(row=2, column=1, padx=PAD, pady=PAD, sticky="nw")

#         # UIDROOT Entry:
#         uidroot_label = ctk.CTkLabel(view, text=_("UID ROOT:"))
#         uidroot_label.grid(row=3, column=0, padx=PAD, pady=PAD, sticky="nw")
#         uidroot_var = ctk.StringVar(view, value=UIDROOT)
#         uidroot_entry = ctk.CTkEntry(
#             view,
#             width=int(max_chars * char_width_px),
#             textvariable=uidroot_var,
#             validate="key",
#             validatecommand=(
#                 validate_entry_cmd,
#                 "%P",
#                 string.digits + string.ascii_uppercase,
#                 str(max_chars),
#             ),
#         )
#         entry_callback = lambda event: str_entry_change(
#             event, uidroot_var, min_chars, max_chars, __name__, "uidroot"
#         )
#         uidroot_entry.bind("<Return>", entry_callback)
#         uidroot_entry.bind("<FocusOut>", entry_callback)
#         uidroot_entry.grid(row=3, column=1, padx=PAD, pady=PAD, sticky="nw")

#         button = ctk.CTkButton(view, text=_("Create Project"), command=create_project)
#         button.grid(row=4, column=2, padx=PAD, pady=PAD, sticky="ne")

#         # button = ctk.CTkButton(
#         #     view, text=_("Open Project"), command=open_directory_dialog()
#         # )
#         # button.grid(row=2, column=0, pady=PAD, sticky="nw")
