# Search

## Goal

Bring DICOM studies into your project so they are de-identified and listed in the Dataset. You can import from a **folder or files** on this computer, or **search a remote imaging system** (PACS / VNA) from the Dashboard.

Configure the [Query Server, modalities, storage classes, and network timeouts](../04-create-project/) before you rely on remote Search.

## From a folder or files

Use **File → Import Files** (pick one or more files) or **File → Import Directory** (every file under a folder and its subfolders is attempted, not only `.dcm`).

Already-imported instances (same SOP Instance UID already in this project) are **skipped**, not quarantined.

### What must be true for a file to import

A file is accepted only if all of these hold:

1. Valid DICOM Part 10 file with file meta information (including the DICOM preamble).
2. Contains **SOP Class UID**, **Study Instance UID**, **Series Instance UID**, and **SOP Instance UID**.
3. Its storage class is allowed by this project’s [storage classes](../04-create-project/#storage-classes).
4. Protected identity (PHI) can be captured successfully.
5. It has not already been imported into this project.

If a [patient lookup table](../04-create-project/#patient-lookup-table) is required, the PHI Patient ID must also match an entry—or the file is quarantined as **Lookup_Miss**.

### Import `davidson_cxr`

Demo chest X-ray used later in [View](../06-view/) and [Remove burned-in text](../07-process/02-remove-burned-in-text/). Path: `tests/controller/assets/test_dcm_files/davidson_cxr`.

**File → Import Directory**, choose that folder, then watch the Import Files dialog. Success shows **PHI Patient ID → anonymized Patient ID**.

![Import in progress](shots/ImportDavidson_Progress.png)

![Import finished](shots/ImportDavidson_Done.png)

### Quarantine

Failed files land under the project’s private quarantine folders (names may appear with spaces or underscores in the UI):


| Folder                             | Typical cause                             |
| ---------------------------------- | ----------------------------------------- |
| `Invalid_DICOM` / DICOM read error | Not valid DICOM, or unreadable            |
| `Missing_Attributes`               | Required UIDs / SOP Class missing         |
| `Invalid_Storage_Class`            | Storage class not enabled for the project |
| `Capture_PHI_Error`                | Could not capture PHI                     |
| `Lookup_Miss`                      | Patient ID not in the lookup table        |


Review quarantine counts on the Dashboard. Fix settings or source files, then import again.

## From a remote imaging system (Dashboard **Search**)

On the Dashboard, click **Search**. The app first **C-ECHO**s the configured Query Server. If the echo succeeds, the **Query, Retrieve & Import** window opens.

!!! tip "Ask IT for help"
    The Query Server must allow this computer to C-ECHO, C-FIND, and C-MOVE, and must know your **Local Server** (address, port, AE Title) as the C-MOVE destination. See [Create a project → When you talk to IT](../04-create-project/#when-you-talk-to-it).

### Search for studies

Enter one or more fields, then click **Query** (or press Return). At least one criterion is required—an empty query is rejected.


| Field                | Notes                                                                                          |
| -------------------- | ---------------------------------------------------------------------------------------------- |
| **Patient Name**     | Letters (including accents), digits, `^` name separator; `?` = one character, `*` = any string |
| **Patient ID**       | ASCII letters/digits; `?` and `*` wildcards                                                    |
| **Modality**         | Dropdown from modalities configured in Project Settings                                        |
| **Study Date**       | One day or a range: `YYYYMMDD` or `YYYYMMDD-YYYYMMDD`                                          |
| **Accession No.(s)** | ASCII, digits, and `/ - _ , .`; `?` and `*` wildcards                                          |


Extra accession options:

- Type a **comma-separated list** in Accession No.(s) to run several searches in one go.
- Use **Load Accession Numbers** to load a `.txt` or `.csv` file (comma- or line-delimited). You will be asked to confirm before the bulk query runs. Accession numbers that are not found can be written to a text file for follow-up.

Other controls:

- **Show Imported Studies** — when off, studies already in this project are hidden from the results list.
- Only studies whose modalities are allowed for the project appear and can be selected.
- **Cancel** stops an in-progress query.

### Example: CT query and import (`Doe^Archibald`)

Set **Modality** to **CT**, click **Query**, select the **Doe^Archibald** head CT, then **Import & Anonymize**. When the import dialog finishes, click **Close** — the study turns green in the results list.

![CT query results — Doe^Archibald selected](shots/OrthancCT_Query.png)

![Import Studies dialog](shots/OrthancCT_Importing.png)

![Imported study highlighted green](shots/OrthancCT_Imported.png)

### Select studies and import

1. Select studies: single click, multi-select (**⌘** / **Ctrl**+click), **Select All**, or **Clear Selection**.
2. Choose **Move Level**: **STUDY**, **SERIES**, or **INSTANCE** (DICOM C-MOVE level). Prefer STUDY when the archive supports it; try SERIES or INSTANCE if transfers stall.
3. Click **Import and Anonymize**. The app builds a study hierarchy for the selected move level, then opens the **Import Studies** progress dialog.
4. Progress tracks images received versus the hierarchy. A study finishes when all expected files arrive **or** a [Network Timeout](../04-create-project/#network-timeouts) expires for that transfer.
5. Close the dialog when done. Successfully imported studies are **highlighted green** in the Query results list.

You can select the same studies again after adjusting timeout or move level—already-imported instances are skipped.

### Handling slow or non-ideal archives

Many VNAs move images asynchronously and do not behave like a textbook PACS. If imports are incomplete:

- Lengthen **Network Timeout** in Project Settings.
- Change **Move Level** (Study → Series → Instance) and retry **Import and Anonymize**.
- Confirm with IT that C-MOVE destination matches your Local Server AE Title and that modalities / storage classes allow the studies you expect.

## What good looks like

- Studies appear under [View → Dataset](../06-view/).
- Dashboard patient / study / image counts increase; quarantine stays empty or only holds expected rejects.
- Remote imports show green highlighting in Query results after a successful run.
- Status text at the bottom of the Dashboard reflects the last Search or import action.

## If it fails


| Symptom                                   | What to try                                                                         |
| ----------------------------------------- | ----------------------------------------------------------------------------------- |
| Search button stays disabled / echo fails | Query Server offline or blocked; verify address, port, AE Title with IT             |
| Connection error on Query                 | C-ECHO failed—fix Query Server settings or network                                  |
| Empty results                             | Broaden wildcards/date; turn on **Show Imported Studies**; check project modalities |
| Nothing imports from folder               | Storage classes / modalities; valid Part 10 DICOM; Lookup table if required         |
| Lookup_Miss                               | Add the Patient ID to the lookup table or relax lookup requirements                 |
| Partial PACS import                       | Longer Network Timeout; different Move Level; retry selection                       |
| Files ignored with no quarantine          | Already imported (same SOP Instance UID)                                            |


## Next steps

Continue with [View](../06-view/) to browse what you imported.
