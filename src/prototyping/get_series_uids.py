from pynetdicom import AE
from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelFind



# Create an Application Entity
ae = AE("ANONYMIZER")

# Create a C-FIND request for Series with the Study Instance UID
request = (
    (0x0008, 0x0052), 'SERIES',
    (0x0020, 0x000D), 'Your Study Instance UID'  # Replace with the actual Study Instance UID
)

study_root_sop_class = StudyRootQueryRetrieveInformationModelFind
transfer_syntaxes = [
    '1.2.840.10008.1.2',  # Implicit VR Little Endian
    '1.2.840.10008.1.2.1',  # Explicit VR Little Endian
    '1.2.840.10008.1.2.2'  # Explicit VR Big Endian
]

# Add the Presentation Context
for ts in transfer_syntaxes:
    ae.add_supported_context(study_root_sop_class, ts)

# Establish a connection to the PACS
assoc = ae.associate('pacs_host', 11112)  # Replace with your PACS host and port

if assoc.is_established:
    # Send the C-FIND request
    responses = assoc.send_c_find(request)

    # Process the responses and collect the Series Instance UIDs
    series_uids = [response.SeriesInstanceUID for response in responses]

    # Close the association
    assoc.release()

    # Print the list of Series Instance UIDs
    for uid in series_uids:
        print(uid)
else:
    print("Association failed")

