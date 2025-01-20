import tkinter as tk
from tkinter import filedialog


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Tkinter Cascaded Menu Example")

        # Create a menu bar
        menubar = tk.Menu(root)
        root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)

        # Open Recent menu (cascaded)
        open_recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Open Recent", menu=open_recent_menu)

        # Add sample directories to the Open Recent menu
        recent_directories = ["/path/to/dir1", "/path/to/dir2", "/path/to/dir3"]
        for directory in recent_directories:
            open_recent_menu.add_command(
                label=directory, command=lambda dir=directory: self.open_directory(dir)
            )

        # Add a separator and "Exit" option to the File menu
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=root.destroy)

    def open_directory(self, directory):
        # Replace this function with the desired action for opening a directory
        print(f"Opening directory: {directory}")


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
