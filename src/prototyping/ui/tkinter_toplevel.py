import tkinter as tk

def open_toplevel():
    toplevel = tk.Toplevel(root)  # Set the 'top' attribute to the parent window 'root'
    toplevel.title("Toplevel Window")
    toplevel.geometry("300x200")

root = tk.Tk()
root.title("Main Window")

button = tk.Button(root, text="Open Toplevel", command=open_toplevel)
button.pack()

root.mainloop()
