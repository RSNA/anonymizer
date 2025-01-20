import tkinter as tk
from tkinter import ttk


def show_popup(message):
    """Create and display a pop-up window with the given message"""
    popup = tk.Toplevel()
    popup.wm_title("Error Message")
    label = tk.Label(popup, text=message, wraplength=300, justify="left")
    label.pack(side="top", fill="x", pady=10, padx=10)
    button = tk.Button(popup, text="Close", command=popup.destroy)
    button.pack(pady=5)
    popup.geometry("400x200")


def on_item_double_click(event):
    """Display the error message in a pop-up window on double-click"""
    item = tree.identify_row(event.y)
    if item:
        message = tree.item(item, "values")[0]
        show_popup(message)


# Create the main window
root = tk.Tk()
root.title("Treeview with Error Messages")

# Create a Treeview widget
tree = ttk.Treeview(root)
tree.pack(fill="both", expand=True)

# Define columns and headings
tree["columns"] = ("details",)
tree.column("#0", width=150)
tree.heading("#0", text="Item")
tree.column("details", width=200)
tree.heading("details", text="Details")

# Example data with error messages
data = [
    ("Item 1", "Short error message."),
    (
        "Item 2",
        "This is a much longer error message that might not fit in the column and should be visible in the popup.",
    ),
    ("Item 3", "Another example of an error message that is quite lengthy and requires a popup to be fully visible."),
]

# Insert data into the Treeview
for item in data:
    tree.insert("", "end", text=item[0], values=(item[1],))

# Bind double-click event to the Treeview
tree.bind("<Double-1>", on_item_double_click)

# Start the Tkinter main loop
root.mainloop()
