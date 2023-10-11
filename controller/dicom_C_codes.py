# C-ECHO, C-STORE, C-FIND, C-MOVE return status values used by Anonmyzier
# from DICOM Standard, Part 7:
# https://dicom.nema.org/medical/dicom/current/output/chtml/part07/chapter_9.html#sect_9.1.1
# Non-Service Class specific statuses - PS3.7 Annex C

C_SUCCESS = 0x0000
C_STORE_PROCESSING_FAILURE = 0x0110
C_STORE_OUT_OF_RESOURCES = 0xA700
C_MOVE_UNKNOWN_AE = 0xA801
C_CANCEL = 0xFE00
C_PENDING_A = 0xFF00
C_PENDING_B = 0xFF01
C_SOP_CLASS_INVALID = 0xC313
C_FAILURE = 0xC000
C_DATA_ELEMENT_DOES_NOT_EXIST = 0x0107
C_STORE_UNRECOGNIZED_OPERATION = 0xC211