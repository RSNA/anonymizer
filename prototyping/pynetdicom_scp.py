import os
from pydicom.filewriter import write_file_meta_info
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.events import Event, EVT_C_STORE, EVT_C_ECHO
from pynetdicom import debug_logger
from pynetdicom.presentation import (
    build_context,
    AllStoragePresentationContexts,
    VerificationPresentationContexts,
)
from pynetdicom._globals import ALL_TRANSFER_SYNTAXES

debug_logger()


def handle_store(event, storage_dir):
    try:
        os.makedirs(storage_dir, exist_ok=True)
    except:
        return 0xC001

    # We rely on the UID from the C-STORE request instead of decoding
    fname = os.path.join(storage_dir, event.request.AffectedSOPInstanceUID)

    remote = event.assoc.remote
    ds = event.dataset
    ds.file_meta = event.file_meta
    ds.save_as(fname, write_like_original=False)

    # with open(fname, "wb") as f:
    #     # Write the preamble, prefix and file meta information elements
    #     f.write(b"\x00" * 128)
    #     f.write(b"DICM")
    #     write_file_meta_info(f, event.file_meta)
    #     # Write the raw encoded dataset
    #     f.write(event.request.DataSet.getvalue())

    return 0x0000


handlers = [(EVT_C_STORE, handle_store, ["out"])]

ae = AE("ANONSTORE")
storage_sop_classes = [
    cx.abstract_syntax
    for cx in AllStoragePresentationContexts + VerificationPresentationContexts
]
for uid in storage_sop_classes:
    ae.add_supported_context(uid, ALL_TRANSFER_SYNTAXES)  # type: ignore

ae.start_server(("127.0.0.1", 1045), block=True, evt_handlers=handlers)  # type: ignore
