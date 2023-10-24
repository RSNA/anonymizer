import tkinter as tk
from tkhtmlview import RenderHTML, HTMLScrolledText

root = tk.Tk()
html_label = HTMLScrolledText(root, html=RenderHTML("assets/html/instructions.html"))
html_label.pack(fill="both", expand=True)
root.mainloop()
