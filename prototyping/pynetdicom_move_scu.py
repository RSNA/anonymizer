import threading
from pydicom.dataset import Dataset
from pydicom.filewriter import write_file_meta_info
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.events import Event, EVT_C_STORE, EVT_C_ECHO
from pynetdicom.sop_class import _QR_CLASSES as QR_CLASSES
from pynetdicom import debug_logger
from pynetdicom.presentation import (
    build_context,
    StoragePresentationContexts,
    VerificationPresentationContexts,
)
from pynetdicom._globals import ALL_TRANSFER_SYNTAXES

# debug_logger()


def handle_store(event: Event) -> int:
    """Handle a C-STORE service request"""
    # Ignore the request and return Success
    print("handle_store")
    return 0x0000


handlers = [(EVT_C_STORE, handle_store)]

# Initialise the Application Entity
ae = AE("PYANON")
ds = Dataset()
ds.QueryRetrieveLevel = "STUDY"
ds.StudyInstanceUID = "1.3.51.0.7.2580558702.65205.27203.38597.5639.39660.54942"

storage_sop_classes = [
    cx.abstract_syntax
    for cx in StoragePresentationContexts + VerificationPresentationContexts
]
for uid in storage_sop_classes:
    ae.add_supported_context(uid, ALL_TRANSFER_SYNTAXES)  # type: ignore


# Start our Storage SCP in non-blocking mode, listening on port 1045
# scp = ae.start_server(("127.0.0.1", 1045), block=False, evt_handlers=handlers)  # type: ignore
def run_scp():
    # Start our Storage SCP in non-blocking mode, listening on port 1045
    global scp
    scp = ae.start_server(("127.0.0.1", 1045), block=True, evt_handlers=handlers)  # type: ignore
    print("end run_scp")


# Start SCP server in a new thread
scp_thread = threading.Thread(target=run_scp, args=())
scp_thread.start()

# Associate with peer AE at IP 127.0.0.1 and port 11112
assoc = ae.associate(
    "127.0.0.1",
    11112,
    contexts=[build_context(QR_CLASSES["StudyRootQueryRetrieveInformationModelMove"])],
    ae_title="MDEDEV",
)

if assoc.is_established:
    # Use the C-MOVE service to send the identifier
    responses = assoc.send_c_move(
        ds, "PYANON", QR_CLASSES["StudyRootQueryRetrieveInformationModelMove"]
    )

    for status, identifier in responses:
        if status:
            print("C-MOVE query status: 0x{0:04x}".format(status.Status))
        else:
            print("Connection timed out, was aborted or received invalid response")

    # Release the association
    assoc.release()
else:
    print("Association rejected, aborted or never connected")

# Stop our Storage SCP
print("shutdown")
ae.shutdown()
