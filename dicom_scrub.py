import tkinter
import customtkinter
from PIL import Image

RSNA_BLUE = "#005DA9"
RSNA_DARK_BLUE = "#014F8F"

APP_WINDOW_WIDTH = 1440
APP_WINDOW_HEIGHT = 1024
APP_TITLE = "DICOM Anonymizer Version 17"
APP_TITLE_COLOR = RSNA_DARK_BLUE
APP_BACKGROND_COLOR = "white"
APP_FONT_FAMILY = "Domine"  # TODO: load font if not on system
APP_FONT_SIZE = 24
APP_FONT_WEIGHT = "bold"

customtkinter.set_appearance_mode(
    "system"
)  # Modes: "System" (standard), "Dark", "Light"
customtkinter.set_default_color_theme(
    "blue"
)  # Themes: "blue" (standard), "green", "dark-blue"


class App(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        # configure App main window
        self.title(APP_TITLE)
        self.geometry(f"{APP_WINDOW_WIDTH}x{APP_WINDOW_HEIGHT}")
        self.font = customtkinter.CTkFont(
            family=APP_FONT_FAMILY, size=APP_FONT_SIZE, weight=APP_FONT_WEIGHT
        )
        self.configure(fg_color=APP_BACKGROND_COLOR)

        # set Main App Fram Grid layout 2 Rows x 1 Column
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.logo_image = customtkinter.CTkImage(
            Image.open("assets/rsna_logo.png"), size=(154, 42)
        )

        # self.header_frame = customtkinter.CTkFrame(self, corner_radius=0)
        # self.header_frame.grid(row=0, column=0, padx=20, pady=20)

        self.logo = customtkinter.CTkLabel(self, image=self.logo_image, text="")
        self.logo.grid(row=0, column=0, padx=94, pady=61, sticky="nw")

        self.title_label = customtkinter.CTkLabel(
            self, text=APP_TITLE, font=self.font, text_color=APP_TITLE_COLOR
        )
        self.title_label.grid(
            row=0,
            column=1,
            pady=61,
            sticky="n",
        )


if __name__ == "__main__":
    app = App()
    app.mainloop()
