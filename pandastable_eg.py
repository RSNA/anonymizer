import tkinter as tk
from pandastable import Table
import pandas as pd
import numpy as np
import customtkinter as ctk
import random
import string

# Generate random string data for your DataFrame
data = {
    "Name": [
        "".join(random.choices(string.ascii_uppercase + string.ascii_lowercase, k=5))
        for _ in range(20)
    ],
    "City": [
        "".join(random.choices(string.ascii_uppercase + string.ascii_lowercase, k=7))
        for _ in range(20)
    ],
}
df = pd.DataFrame(data)

# Create the root window
root = ctk.CTk()
root.title("DataFrame Display")

# Create a Frame to hold the Table
frame = ctk.CTkFrame(root)
frame.pack(fill="both", expand=True)

# Create and display the Table
table = Table(
    frame,
    dataframe=df,
    showtoolbar=True,
    showstatusbar=True,
    editable=False,
    enable_menus=True,
)
table.show()

root.mainloop()
