import tkinter as tk


def open_file():
    print("Open file")


def save_file():
    print("Save file")


def quit_app():
    root.quit()


root = tk.Tk()
root.geometry("500x300")

root.title("tkMenuTest")

menu_bar = tk.Menu(root)

file_menu = tk.Menu(menu_bar, tearoff=0)
file_menu.add_command(label="Open", command=open_file)
file_menu.add_command(label="Save", command=save_file)
file_menu.add_separator()
file_menu.add_command(label="Quit", command=quit_app)

menu_bar.add_cascade(label="File", menu=file_menu)

root.config(menu=menu_bar)

root.mainloop()
