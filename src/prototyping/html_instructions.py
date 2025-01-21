import tkinter as tk
from tkhtmlview import RenderHTML, HTMLScrolledText

root = tk.Tk()
html_label = HTMLScrolledText(
    root, width=130, height=60, padx=10, pady=10, html=RenderHTML("assets/locales/en_US/html/images/overview.html")
)
html_label.pack(fill="both", expand=True)
root.mainloop()
