import tkinter
import customtkinter
from PIL import Image

customtkinter.set_appearance_mode(
    "Light"
)  # Modes: "System" (standard), "Dark", "Light"
customtkinter.set_default_color_theme(
    "blue"
)  # Themes: "blue" (standard), "green", "dark-blue", "dark-green", "light-blue", "light-green"

# Custom Colors:
RSNA_BLUE = "#005DA9"
RSNA_DARK_BLUE = "#014F8F"
APP_BACKGROUND_COLOR = "white"
APP_TITLE_COLOR = RSNA_DARK_BLUE

# Fixed Frame Dimensions:
APP_WINDOW_WIDTH = 1280  # 1440
APP_WINDOW_HEIGHT = 720  # 1024

HEADER_FRAME_HEIGHT = APP_WINDOW_HEIGHT / 10

CONTENT_FRAME_HEIGHT = APP_WINDOW_HEIGHT - HEADER_FRAME_HEIGHT
CONTENT_FRAME_BORDER_WIDTH = HEADER_FRAME_HEIGHT / 6
CONTENT_FRAME_PAD = 20
CONTENT_FRAME_BORDER_COLOR = RSNA_DARK_BLUE

APP_TITLE = "DICOM Anonymizer Version 17"

# Font:
APP_FONT_FAMILY = "Domine"  # TODO: load font if not on system
APP_FONT_SIZE = 20
APP_FONT_WEIGHT = "bold"


class App(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        # configure App main window
        self.title(APP_TITLE)
        self.geometry(f"{APP_WINDOW_WIDTH}x{APP_WINDOW_HEIGHT}")
        self.font = customtkinter.CTkFont(
            family=APP_FONT_FAMILY, size=APP_FONT_SIZE, weight=APP_FONT_WEIGHT
        )

        # set Main App Frame Grid layout : 2 Rows for Header and Content, 1 Column
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.logo_image = customtkinter.CTkImage(
            Image.open("assets/rsna_logo.png"), size=(154, 42)
        )

        # Header Frame
        self.header_frame = customtkinter.CTkFrame(
            self,
            height=HEADER_FRAME_HEIGHT,
            border_color="red",
            border_width=2,
        )
        self.header_frame.grid(row=0, column=0, padx=CONTENT_FRAME_PAD, sticky="ew")

        self.logo = customtkinter.CTkLabel(
            self.header_frame, image=self.logo_image, text=""
        )
        self.logo.grid(
            row=0, column=0, padx=CONTENT_FRAME_PAD, pady=CONTENT_FRAME_PAD, sticky="nw"
        )

        self.title_label = customtkinter.CTkLabel(
            self.header_frame,
            text=APP_TITLE,
            font=self.font,
            text_color=APP_TITLE_COLOR,
        )
        self.title_label.grid(
            row=0,
            column=1,
            pady=CONTENT_FRAME_PAD,
            sticky="n",
        )

        # Content Frame:
        self.content_frame = customtkinter.CTkFrame(
            self,
            border_color=CONTENT_FRAME_BORDER_COLOR,
            border_width=CONTENT_FRAME_BORDER_WIDTH,
        )
        self.content_frame.grid(
            row=1,
            column=0,
            padx=CONTENT_FRAME_PAD,
            pady=(0, CONTENT_FRAME_PAD),
            sticky="nsew",
        )


if __name__ == "__main__":
    app = App()
    app.mainloop()
