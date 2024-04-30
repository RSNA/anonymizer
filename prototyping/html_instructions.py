import tkinter as tk
from tkhtmlview import RenderHTML, HTMLScrolledText

root = tk.Tk()
html_label = HTMLScrolledText(
    root, width=130, height=60, padx=10, pady=10, html=RenderHTML("assets/html/overview.html")
)
html_label.pack(fill="both", expand=True)
root.mainloop()
