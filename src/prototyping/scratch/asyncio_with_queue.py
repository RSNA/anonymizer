import asyncio
import concurrent.futures
from queue import Queue
from pynetdicom import AE, evt
from pydicom import Dataset

# Initialize a thread-safe queue for inter-task communication
dicom_queue = Queue()


# Define an asynchronous callback function to handle incoming DICOM files
async def on_c_store(event):
    # Get the received DICOM dataset
    ds = event.dataset

    # Initial async processing of DICOM dataset (e.g., header extraction)
    await asyncio.to_thread(process_dicom, ds)

    # Enqueue the DICOM dataset for further processing
    dicom_queue.put(ds)


# Perform CPU-bound processing on DICOM dataset
def process_dicom(ds):
    # Perform CPU-bound processing here (e.g., image analysis)
    pass


# Consume DICOM datasets from the queue and save them
async def save_dicom_files():
    while True:
        ds = dicom_queue.get()
        if ds:
            # Perform additional processing if needed
            # Save the DICOM dataset to a file
            ds.save_as("path_to_save_directory/filename.dcm")


# Create an Application Entity (AE) and add the callback
ae = AE()
ae.add_requested_context("1.2.840.10008.5.1.4.1.1.2")  # C-STORE SOP Class
ae.on_c_store += on_c_store


# Start the asyncio event loop
async def main():
    server = ae.start_server(("localhost", 11112))
    await asyncio.gather(
        server.serve_forever(),
        save_dicom_files(),  # Start the DICOM file saving coroutine
    )


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
