import logging
import customtkinter as ctk

# TODO: investigate global, detachable log window with level and module filter


class TextBoxHandler(logging.Handler):
    def __init__(self, text):
        logging.Handler.__init__(self)
        self.text = text

    def emit(self, record):
        msg = self.format(record)
        self.text.configure(state="normal")
        self.text.insert(ctk.END, msg + "\n")
        self.text.configure(state="disabled")
        self.text.see(ctk.END)


# Install log handler for SCP Textbox:
def install_loghandler(logger, textbox: ctk.CTkTextbox) -> logging.Handler:
    handler = TextBoxHandler(textbox)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return handler
