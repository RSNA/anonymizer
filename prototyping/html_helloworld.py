import tkinter as tk
from tkhtmlview import HTMLLabel, HTMLScrolledText

root = tk.Tk()
html_label = HTMLScrolledText(root, html='<h1 style="color: red; text-align: center"> Hello World </H1>')
html_label.pack(fill="both", expand=True)
html_label.fit_height()
root.mainloop()
