# Start here

## What this program does

The RSNA DICOM Anonymizer is a stand-alone application that **removes protected identity information** from medical imaging studies and stores a research-safe copy on your computer.

You can bring images in from a folder or from a hospital imaging system, review them, optionally apply AI tools (burned-in text removal, standard study & series naming, face blur), then send the de-identified studies to another system or cloud archive.

## Privacy goal

Patient names, IDs, and other identifiers in the file “labels” (DICOM tags) are replaced or removed. Dates are shifted so timing within one patient stays consistent but is not the calendar date. Optional AI tools can also hide text drawn onto the picture itself and blur facial features on head exams—because those can still identify someone after the labels are cleaned.

## Who it is for

- Radiologists and imaging researchers curating datasets
- Sites submitting studies to research archives

## Two ways to work


| Mode                     | Best for                                                                                                     |
| ------------------------ | ------------------------------------------------------------------------------------------------------------ |
| **Desktop window (GUI)** | Creating projects, reviewing images, AI tools, export                                                        |
| **No window (headless)** | Lab/server: keep receiving images, or run AI batch overnight — see [Run without the window](../09-headless/) |


!!! important "Create the project in the window first"
    Headless mode uses a project you already created and configured. Start with [Create a project](../04-create-project/), then ask IT to run headless if needed.

## Next steps

1. [Install and first launch](../02-install/)
2. [Words we use](../03-words-we-use/)
3. [Create a project](../04-create-project/)

