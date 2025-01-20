import asyncio
import tkinter as tk
from tkinter import messagebox
from pydicom.uid import ExplicitVRLittleEndian
from pynetdicom import AE, evt, debug_logger

# Enable logging
debug_logger()


class DICOMEchoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("DICOM Echo")

        self.label = tk.Label(root, text="Enter SCP details:")
        self.label.pack()

        self.ae_title_label = tk.Label(root, text="AE Title:")
        self.ae_title_label.pack()
        self.ae_title_entry = tk.Entry(root)
        self.ae_title_entry.pack()

        self.ip_label = tk.Label(root, text="IP Address:")
        self.ip_label.pack()
        self.ip_entry = tk.Entry(root)
        self.ip_entry.pack()

        self.port_label = tk.Label(root, text="Port:")
        self.port_label.pack()
        self.port_entry = tk.Entry(root)
        self.port_entry.pack()

        self.echo_button = tk.Button(root, text="Send Echo", command=self.send_echo)
        self.echo_button.pack()

        self.loop = asyncio.get_event_loop()

    async def perform_echo(self, ae_title, ip, port):
        ae = AE()
        ae.add_requested_context(ExplicitVRLittleEndian)

        try:
            assoc = await ae.associate(ip, int(port), ae_title=ae_title)
            if assoc.is_established:
                status = await assoc.send_c_echo()
                assoc.release()

                if status:
                    messagebox.showinfo("Success", f"Echo succeeded: {status.Status}")
                else:
                    messagebox.showwarning("Failure", "Echo failed")
            else:
                messagebox.showwarning("Failure", "Association rejected or aborted")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def send_echo(self):
        ae_title = self.ae_title_entry.get()
        ip = self.ip_entry.get()
        port = self.port_entry.get()

        # Run the perform_echo coroutine
        asyncio.run_coroutine_threadsafe(self.perform_echo(ae_title, ip, port), self.loop)


if __name__ == "__main__":
    root = tk.Tk()
    app = DICOMEchoApp(root)

    # Start the Tkinter event loop in the main thread
    root.mainloop()
