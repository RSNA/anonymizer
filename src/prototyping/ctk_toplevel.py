import customtkinter as ctk

def open_toplevel():
    toplevel = ctk.CTkToplevel(root)  # Set the 'top' attribute to the parent window 'root'
    toplevel.title("Toplevel Window")
    toplevel.geometry("300x200")
    toplevel.lift()

root = ctk.CTk()
root.title("Main Window")

button = ctk.CTkButton(root, text="Open Toplevel", command=open_toplevel)
button.pack()

root.mainloop()
