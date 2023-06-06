import tkinter
import customtkinter as ctk
from PIL import Image

ctk.set_appearance_mode("Light")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme(
    "assets/rsna_color_scheme_font.json"
)  # sets all colors and default font

# Colors and font handled by custom color scheme in json file in assets folder
# RSNA Dicom Anonymizer Color Scheme & default font based on dark-blue
# RSNA_BLUE = "#005DA9"
# RSNA_DARK_BLUE = "#014F8F"
# APP_FONT_FAMILY = "Domine"  # TODO: load font if not on system
# APP_FONT_SIZE = 20
# APP_FONT_WEIGHT = "bold"

# Fixed Frame Dimensions:
APP_WINDOW_WIDTH = 1280  # 1440
APP_WINDOW_HEIGHT = 720  # 1024

HEADER_FRAME_HEIGHT = APP_WINDOW_HEIGHT / 10

CONTENT_FRAME_BORDER_WIDTH = HEADER_FRAME_HEIGHT / 6
CONTENT_FRAME_PAD = CONTENT_FRAME_BORDER_WIDTH

RSNA_LOGO_WIDTH = 150
RSNA_LOGO_HEIGHT = 40
APP_TITLE = "DICOM Anonymizer Version 17"


class RSNATabView(ctk.CTkTabview):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.tabview = ctk.CTkTabview(
            master,
            border_width=CONTENT_FRAME_BORDER_WIDTH,
            # width=master._getconfigure("width") - 2 * CONTENT_FRAME_PAD,
            # height=master._getconfigure("height") - 2 * CONTENT_FRAME_PAD,
        )

        self.tabview.grid(
            row=1,
            column=0,
            padx=CONTENT_FRAME_PAD,
            pady=CONTENT_FRAME_PAD,
            sticky="nsew",
        )
        self.tabview.add("     About     ")
        self.tabview.add("Storage")
        self.tabview.add("Settings")
        self.tabview.add("Import")
        self.tabview.add("Verify")
        self.tabview.add("Export")
        self.tabview.add("Admin")
        # configure grid of individual tabs
        # self.tabview.tab("About").grid_columnconfigure(0, weight=1)
        # self.tabview.tab("Storage").grid_columnconfigure(0, weight=1)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry(f"{APP_WINDOW_WIDTH}x{APP_WINDOW_HEIGHT}")
        self.font = ctk.CTkFont()  # get default font as defined in json file
        self.title_height = self.font.metrics("linespace")

        # Main Frame adjustability:
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Logo:
        self.logo_image = ctk.CTkImage(
            Image.open("assets/rsna_logo.png"), size=(RSNA_LOGO_WIDTH, RSNA_LOGO_HEIGHT)
        )
        self.logo = ctk.CTkLabel(self, image=self.logo_image, text="")
        self.logo.grid(
            row=0,
            column=0,
            padx=CONTENT_FRAME_PAD,
            pady=(CONTENT_FRAME_PAD, 0),
            sticky="w",
        )

        # Title:
        self.title_label = ctk.CTkLabel(
            self,  # .header_frame,
            text=APP_TITLE,
            font=self.font,
        )
        self.title_label.grid(
            row=0,
            column=0,
            pady=(RSNA_LOGO_HEIGHT + CONTENT_FRAME_PAD - self.title_height, 0),
            sticky="n",
        )

        # Content Frame:
        # self.content_frame = ctk.CTkFrame(
        #     self,
        #     # border_width=CONTENT_FRAME_BORDER_WIDTH,
        # )
        # self.content_frame.grid(
        #     row=1,
        #     column=0,
        #     padx=CONTENT_FRAME_PAD,
        #     pady=(0, CONTENT_FRAME_PAD),
        #     sticky="nsew",
        # )

        self.tab_view = RSNATabView(master=self)  # .content_frame)


if __name__ == "__main__":
    app = App()
    app.mainloop()
