import customtkinter

app = customtkinter.CTk()
app.geometry("400x300")


def button_click_event():
    dialog = customtkinter.CTkInputDialog(text="Type in a number:", title="Test")
    print("Number:", dialog.get_input())


button = customtkinter.CTkButton(app, text="Open Dialog", command=button_click_event)
button.pack(padx=20, pady=20)

app.mainloop()
