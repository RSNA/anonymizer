import tkinter as tk
from tkinter import ttk


# Function to toggle child visibility
def toggle_children(item_id):
    # If children are already present, remove them
    children = tree.get_children(item_id)
    if children:
        tree.delete(children)
    else:
        # Add child item with embedded string
        tree.insert(item_id, "end", text="Embedded String: This is additional information")


# Create the main window
root = tk.Tk()
root.title("Treeview with Expandable Rows")

# Create a Treeview widget
tree = ttk.Treeview(root)
tree.pack(fill="both", expand=True)

# Define columns and headings
tree["columns"] = "details"
tree.column("#0", width=150)
tree.heading("#0", text="Item")
tree.column("details", width=200)
tree.heading("details", text="Details")

# Insert root level items
item1 = tree.insert("", "end", text="Item 1", values=("Details for Item 1"))
item2 = tree.insert("", "end", text="Item 2", values=("Details for Item 2"))
item3 = tree.insert("", "end", text="Item 3", values=("Details for Item 3"))

# Insert a child item under "Item 3"
child_item3 = tree.insert(item3, "end", text="Embedded String: This is additional information")
tree.item(child_item3, open=True)  # Open the child item initially

# Bind double-click to toggle child visibility
tree.bind("<Double-1>", lambda event: toggle_children(tree.selection()[0]))

# Start the Tkinter main loop
root.mainloop()
