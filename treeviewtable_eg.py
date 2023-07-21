import tkinter as tk
from tkinter import ttk
import pandas as pd
import random
import string

# Generate more data for your DataFrame
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
root = tk.Tk()
root.title("DataFrame Display")

# Create a Frame to hold the Treeview and Scrollbar
frame = ttk.Frame(root)
frame.pack(fill="both", expand=True)

# Create the Treeview
tree = ttk.Treeview(frame, columns=list(df.columns), show="headings")

# Set up the column headers
for col in df.columns:
    tree.heading(col, text=col, command=lambda _col=col: sortby(tree, _col, 0))

# Load the data into the Treeview
for index, row in df.iterrows():
    tree.insert("", "end", values=list(row))

# Create a Scrollbar and associate it with the Treeview
scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
scrollbar.pack(side="right", fill="y")
tree.configure(yscrollcommand=scrollbar.set)


# Sorting function
def sortby(tree, col, descending):
    data = [(tree.set(child, col), child) for child in tree.get_children("")]
    data.sort(reverse=descending)

    for ix, item in enumerate(data):
        tree.move(item[1], "", ix)

    # switch the heading so it will sort in the opposite direction
    tree.heading(col, command=lambda _col=col: sortby(tree, _col, int(not descending)))

    global sorted_column
    sorted_column = (col, descending)

    # Update the headers to indicate the sort column and direction
    for _col in df.columns:
        if _col == col:
            direction = " \u2193" if descending else " \u2191"  # Down and up arrows
            tree.heading(_col, text=_col + direction)
        else:
            tree.heading(_col, text=_col)


# Pack the Treeview
tree.pack(fill="both", expand=True)

# Initialize the sorted_column variable
sorted_column = (df.columns[0], 0)

# Sort the Treeview on the first column
sortby(tree, df.columns[0], 0)

root.mainloop()
