import tkinter as tk


def key_pressed(event):
    print(f"Key pressed: {event.keysym}")


root = tk.Tk()
root.geometry("200x100")

frame = tk.Frame(root, width=100, height=50, bg="red")
frame.pack(expand=True, fill="both")
frame.focus_set()  # Give the frame focus

frame.bind("<Key>", key_pressed)  # Bind to the frame

root.mainloop()
