import customtkinter as ctk
from PIL import Image

ABOUT_WELCOME = "RSNA is assembling a repository of de-identified COVID-19-related imaging data for research and education. Medical institutions interested in joining this international collaboration are invited to submit de-identified imaging data for inclusion in this repository. The RSNA Anonymizer program is a free open-source tool for collecting and de-identifying DICOM studies to prepare them for submission. It may be used to ensure privacy by removing protected health information from your DICOM imaging studies.\n\nYou can learn more about the RSNA COVID-19 Imaging Data Repository initiative here."


class TabViewNested(ctk.CTkTabview):
    def __init__(self, master, tabs, **kwargs):
        super().__init__(master, **kwargs)
        for tab in tabs:
            tabview = self.add(tab)
            tabview.rowconfigure(1, weight=1)
            tabview.columnconfigure(0, weight=1)

            if tab == "Welcome":
                label_welcome = ctk.CTkLabel(
                    master=tabview, text=tab, font=("Domine", 20)
                )
                label_welcome.grid(row=0, column=0, sticky="n")
                text_box_welcome = ctk.CTkTextbox(tabview, wrap="word")
                text_box_welcome.insert("0.0", text=ABOUT_WELCOME)
                text_box_welcome.grid(row=1, column=0, sticky="nwe")


class TabViewMain(ctk.CTkTabview):
    def __init__(self, master, tabs, border_width, **kwargs):
        super().__init__(master, border_width=border_width, **kwargs)

        for main_tab, embedded_tabs in tabs.items():
            self.add(main_tab)

            # Get the parent widget for the nested TabView
            parent = self.tab(main_tab)

            # Configure the parent widget to distribute extra space to the nested TabView
            parent.rowconfigure(0, weight=1)
            parent.columnconfigure(0, weight=1)

            # Create and grid the nested TabView
            tabview_nested = TabViewNested(master=parent, tabs=embedded_tabs)
            tabview_nested.grid(row=0, column=0, sticky="nswe")


class App(ctk.CTk):
    def __init__(
        self,
        color_theme,
        title,
        logo_files,
        logo_width,
        logo_height,
        tabs,
        pad,
    ):
        super().__init__()

        ctk.set_appearance_mode("Light")  # Modes: "System" (standard), "Dark", "Light"
        # sets all colors and default font:
        ctk.set_default_color_theme(color_theme)

        self.geometry("800x600")
        self.font = ctk.CTkFont()  # get default font as defined in json file
        self.title(title)
        self.title_height = self.font.metrics("linespace")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Logo:
        self.logo = ctk.CTkImage(
            light_image=Image.open(logo_files[0]),
            dark_image=Image.open(logo_files[1]),
            size=(logo_width, logo_height),
        )
        self.logo = ctk.CTkLabel(self, image=self.logo, text="")
        self.logo.grid(
            row=0,
            column=0,
            padx=pad,
            pady=(pad, 0),
            sticky="nw",
        )

        # Title:
        self.title_label = ctk.CTkLabel(
            self,
            text=title,
            # font=self.font,
        )
        self.title_label.grid(
            row=0,
            column=0,
            pady=(logo_height + pad - self.title_height, 0),
            sticky="n",
        )

        # Content (TabView):
        self.tab_view = TabViewMain(master=self, tabs=tabs, border_width=pad)
        self.tab_view.grid(row=1, column=0, padx=pad, pady=(0, pad), sticky="nswe")


tabs = {
    "About": ["Welcome", "Help"],
    "Storage": ["Set Storage Directory", "Configure Storage SCP"],
    "Settings": ["Anonymizer Script", "Filter Settings"],
    "Import": ["Select Local Files", "Query SCP Storage"],
    "Verify": ["Patient Index List"],
    "Export": ["Export to HTTPS", "Export to SCP Storage"],
    "Admin": ["Import Log", "Export Log"],
}


app = App(
    color_theme="assets/rsna_color_scheme_font.json",
    title="DICOM Anonymizer Version 17",
    logo_files=("assets/rsna_logo_light.png", "assets/rsna_logo_dark.png"),
    logo_width=75,
    logo_height=20,
    tabs=tabs,
    pad=10,
)
app.mainloop()
