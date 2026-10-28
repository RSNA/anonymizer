# Start here

## What this program does

The RSNA DICOM Anonymizer is a stand-alone application that **removes protected identity information** from medical imaging studies and stores a research-safe copy on your computer.

You can bring images in from a folder or from a hospital imaging system, review them, optionally apply AI tools (burned-in text on pixels, named-entity scrubbing of report text, standard study & series naming, face blur), then send the de-identified studies to another system or cloud archive.

## Privacy goal

Patient names, IDs, and other identifiers in the file “labels” (DICOM tags) are replaced or removed at **import** by the project’s de-identification script. Dates are shifted so timing within one patient stays consistent but is not the calendar date.

That tag walk does **not** scrub free text inside Structured Reports or Encapsulated PDFs, and it does not erase names drawn onto pixels. When you keep report objects (Clean Structured Content), you must run **Report Text Review** after import: English named-entity recognition (NER) finds names, dates, IDs, phones, and similar spans in the report body so you can blank them or replace them with synthetic values. Separately, optional AI tools can hide burned-in pixel text and blur faces on head exams—because those can still identify someone after the labels are cleaned.

## Standards and testing

The default script follows the DICOM **Basic Application Confidentiality Profile** ([PS 3.15 Appendix E](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html)) and related retain options you choose for the project. That profile and the public TCIA / NCI **Medical Image De-Identification Benchmark (MIDI-B)** are aligned with **HIPAA Safe Harbor–style** identifier removal for imaging headers (not a claim that the product is “HIPAA certified”). Header de-identification is checked with the official MIDI-B scorer (see [De-identification protocol](../deidentification-protocol.md)). For the formal PS 3.15 § E.1.3 checklist (what is removed, replaced, inserted; options; no Encrypted Attributes path), see the [DICOM Conformance Statement](../dicom-conformance-statement.md). Your privacy officer should still review options and any custom script for your site—this manual is operational guidance, not a compliance certificate.

## Who it is for

- Radiologists and imaging researchers curating datasets
- Sites submitting studies to research archives

## Two ways to work


| Mode                     | Best for                                                                                                     |
| ------------------------ | ------------------------------------------------------------------------------------------------------------ |
| **Desktop window (GUI)** | Creating projects, reviewing images, AI tools, organ-volume Analytics on the Dashboard, export |
| **No window (headless)** | Lab/server: keep receiving images, or run AI batch overnight — see [Run headless](../10-headless/index.md) |


!!! important "Create the project in the window first"
    Headless mode uses a project you already created and configured. Start with [Create a project](../05-create-project/index.md), then ask IT to run headless if needed.

## Next steps

1. [Install and first launch](../02-install/index.md)
2. [AI Features setup](../03-ai-features-setup/index.md) (from Welcome)
3. [Words we use](../04-words-we-use/index.md)
4. [Create a project](../05-create-project/index.md)

