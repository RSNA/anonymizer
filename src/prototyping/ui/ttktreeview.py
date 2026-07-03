from tkinter import ttk
import customtkinter as ctk

# Create the main window
root = ctk.CTk()
root.title("Treeview with Scrollbars")
root.geometry("800x400")  # Set the window size

# Configure the grid to expand with the window
root.grid_rowconfigure(0, weight=1)
root.grid_columnconfigure(0, weight=1)

# Create a frame to hold the Treeview and the scrollbars
frame = ctk.CTkFrame(root)
frame.grid(row=0, column=0, sticky="nsew")
# Configure the frame to expand with the window
frame.grid_rowconfigure(0, weight=1)
frame.grid_columnconfigure(0, weight=1)


# Create the Treeview widget
columns = ("col1", "col2", "col3", "col4", "col5")
tree = ttk.Treeview(frame, columns=columns, show="headings")

# Define the column headings
for col in columns:
    tree.heading(col, text=col.capitalize())
    tree.column(col, width=100, stretch=False)

# Adjust the width of the last column
tree.column("col5", width=2000, stretch=False)

# Create the vertical scrollbar
vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
vsb.grid(row=0, column=1, sticky="ns")

# Create the horizontal scrollbar
hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
hsb.grid(row=1, column=0, sticky="ew")

# Configure the Treeview to use the scrollbars
tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

# Place the Treeview in the grid
tree.grid(row=0, column=0, sticky="nsew")

# Add some test data, including one very wide item in the last column
for i in range(100):
    if i == 50:
        # Insert a long string into the last column to ensure horizontal scrolling is required
        tree.insert(
            "",
            "end",
            values=(
                f"Item {i+1}-1",
                f"Item {i+1}-2",
                f"Item {i+1}-3",
                f"Item {i+1}-4",
                "A very long string that exceeds the column width and should require horizontal scrolling to view completely. This is to ensure that the horizontal scrollbar appears correctly.",
            ),
        )
    else:
        tree.insert(
            "", "end", values=(f"Item {i+1}-1", f"Item {i+1}-2", f"Item {i+1}-3", f"Item {i+1}-4", f"Item {i+1}-5")
        )

# Start the Tkinter main loop
root.mainloop()
