import customtkinter as ctk
import tkinter as tk


class Application(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Initialize the segmented button for main tabs
        self.main_view = tk.Frame(self)
        self.main_view.pack(fill="both", expand=True)

        self.main_button_callback = self.update_main_view
        self.main_segmented_button = ctk.CTkSegmentedButton(
            self, values=["Tab 1", "Tab 2"], command=self.main_button_callback
        )
        self.main_segmented_button.pack(padx=20, pady=10)

        # Initialize the segmented button for embedded tabs
        self.embedded_view = tk.Frame(self.main_view)
        self.embedded_view.pack(fill="both", expand=True)

        self.embedded_button_callback = self.update_embedded_view
        self.embedded_segmented_button = ctk.CTkSegmentedButton(
            self.main_view,
            values=["Tab A", "Tab B"],
            command=self.embedded_button_callback,
        )
        self.embedded_segmented_button.pack(padx=20, pady=10)

        # Initially, only display main segmented button and set default tab
        self.main_segmented_button.set("Tab 1")
        self.embedded_segmented_button.pack_forget()

    def update_main_view(self, value):
        if value == "Tab 1":
            self.embedded_segmented_button.pack(padx=20, pady=10)
        else:
            self.embedded_segmented_button.pack_forget()

    def update_embedded_view(self, value):
        # Code for updating the view when Tab A or Tab B is selected
        pass


app = Application()
app.mainloop()
