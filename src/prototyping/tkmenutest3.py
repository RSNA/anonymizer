import tkinter as tk
from tkinter import messagebox


class DynamicMenuApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dynamic Menu Example")

        # Create the main menu
        self.menu = tk.Menu(root)
        root.config(menu=self.menu)

        # Create a File menu with initial items
        self.file_menu = tk.Menu(self.menu, tearoff=0)
        self.file_menu.add_command(label="Open", command=self.open_file)
        self.file_menu.add_command(label="Save", command=self.save_file)

        # Add the File menu to the main menu
        self.menu.add_cascade(label="File", menu=self.file_menu)

        # Create a button to toggle the menu state
        self.toggle_button = tk.Button(root, text="Toggle Menu State", command=self.toggle_menu_state)
        self.toggle_button.pack(pady=20)

        # Variable to track menu state
        self.menu_state = True  # True means state with submenu

        # Create a submenu
        self.sub_menu = tk.Menu(self.file_menu, tearoff=0)
        self.sub_menu.add_command(label="Submenu Item 1", command=self.submenu_action)
        self.file_menu.add_cascade(label="Submenu", menu=self.sub_menu)

    def open_file(self):
        messagebox.showinfo("Open", "Open File clicked")

    def save_file(self):
        messagebox.showinfo("Save", "Save File clicked")

    def submenu_action(self):
        messagebox.showinfo("Submenu", "Submenu Item clicked")

    def toggle_menu_state(self):
        if self.menu_state:
            # Remove the submenu
            self.file_menu.delete("Submenu")
            self.menu_state = False
        else:
            # Re-add the submenu
            self.file_menu.add_cascade(label="Submenu", menu=self.sub_menu)
            self.menu_state = True


if __name__ == "__main__":
    root = tk.Tk()
    app = DynamicMenuApp(root)
    root.mainloop()
