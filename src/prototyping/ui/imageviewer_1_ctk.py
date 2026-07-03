import customtkinter as ctk


def key_pressed(event):
    print(f"Key pressed: {event.keysym}")
    print(f"Widget with focus: {root.focus_get()}")  # Add this line


root = ctk.CTk()
root.geometry("200x100")

frame = ctk.CTkFrame(root, width=100, height=50)
frame.pack(expand=True, fill="both")

# Set focus to the frame *after* packing it
frame.focus_set()

# Bind the <Key> event to the frame.  "<Key>" is a catch-all for key presses.
frame.bind("<Key>", key_pressed)

# Add a label to the frame (to make sure it's not completely empty)
label = ctk.CTkLabel(frame, text="Click here, then press keys")
label.pack(pady=20)


# Add a click handler to ensure focus is set:
def frame_clicked(event):
    # see here: https://stackoverflow.com/questions/77676235/tkinter-focus-set-on-frame
    # The reason why the customtkinter code doesn't work is that customtkinter has some peculiarities in how it handles bindings. '
    # 'It unfortunately overrides bind to apply any bindings to a canvas widget embedded in the frame rather than the frame itself. '
    # 'So, the bindings get added to a canvas, but you set focus to the frame.
    frame._canvas.focus_set()
    print("Frame clicked, focus set.")


frame.bind("<Button-1>", frame_clicked)

root.mainloop()
