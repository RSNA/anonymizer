# How to talk to the Anonymizer MCP (for clinicians)

Use this when chatting with an LLM client connected to the RSNA Anonymizer MCP server.

You do **not** need to know every setting before creating a project. Give the assistant a project name and only the settings that matter to you. The MCP server combines those choices with the Anonymizer defaults, shows you the complete configuration, and creates nothing until you confirm it.

The same plain-language guidance is what the assistant should return when you ask how to use the Anonymizer (via the `anonymizer_usage` tool).

## Quick start: just ask for help

In the chat, you can ask:

```text
How do I create a new project and change its settings later?
Explain the steps; do not create anything yet.
```

The assistant should explain the create → review → confirm flow without creating a project. You can also ask:

```text
Show me the project defaults and ranges.
```

or, when a project is already open:

```text
Show my current project settings.
```

## Create a project

Start with a name and any important choices:

```text
Create a new project named DemoCXR. Use defaults for everything else.
```

Retain-options example (plain language; the assistant maps this to the project’s de-identification options):

```text
Create a Retain-options project named RetainDemo using CT and MR.
```

The assistant will prepare the configuration and reply with a review summary. It should identify:

- values you supplied;
- values taken from defaults;
- any warnings, such as an existing project at the destination.

**Nothing has been created at that point.** While you are still reviewing, any creation choice — including the language — can be revised; once you confirm, those creation choices are fixed.

You can then either change something:

```text
Add US and show me the revised configuration.
```

or confirm the exact revision shown:

```text
Yes, create it exactly as shown.
```

Only then is the project created and opened. Do not ask to open the same project again after creation.

### Settings you may supply when creating

You only need to mention the ones you care about:

- project name — required;
- de-identification options — **Basic** (default) or **Retain** (keeps more clinical context; same idea as the desktop New Project options);
- modalities — for example CT, MR, and US;
- language — chosen once at creation, like the desktop welcome-screen language selector; it cannot be changed afterwards;
- site ID and UID root — normally generated or defaulted;
- storage folder — normally the default project store;
- local receive address (IP, port, AE title) for this workstation;
- network timeouts.

The review summary shows the effective value of every create setting, including defaults.

## List or open an existing project

```text
What projects do I already have?
```

```text
Open the project named DemoCXR.
```

Opening a project does **not** import DICOM. Import is a separate step after a project is open.

## Configure a project later

After a project is created or opened, you can change mutable settings at any time:

```text
Change the modalities to CT, MR and US.
```

Mutable settings are:

- modalities
- transfer syntaxes (encodings accepted on receive/import)
- local receive address (IP, port, AE title)
- network timeouts
- de-identification options (changing them rebuilds the project’s anonymizer script from the defaults plus those options — custom script edits are lost; confirm first)

Project name, storage folder, site ID, UID root, and language are fixed after creation.

Ask for the current configuration whenever you are unsure:

```text
Show my current project settings.
```

## Configure a PACS QUERY remote

A project must be open. Say **DIMSE or DICOMweb** and give the exact fields. Use these names only: `ip`, `port`, `aet`, `role`, `dicomweb`, `http_port`, `http_path` — not `host`, `hostname`, `protocol`, `path`, or `aetitle`.

**DIMSE:**

```text
Configure QUERY remote as DIMSE: ip 10.0.0.5, port 104, aet ORTHANC,
dicomweb false.
```

**DICOMweb:**

```text
Configure QUERY remote as DICOMweb: ip 10.0.0.5, port 104, aet ORTHANC,
dicomweb true, http_port 8042, http_path /dicom-web.
```

If you do not specify DIMSE versus DICOMweb, the assistant should ask before configuring the remote.

After the QUERY remote is configured you can ask to **find** studies and **import** selected studies from PACS. Give study identifiers from the find results — do not invent UIDs.

## Import DICOM from this computer

Once a project is open, give a **real absolute path**:

```text
Import the DICOM file at this absolute path: /Users/me/studies/chest.dcm
```

```text
Import the DICOM directory at this absolute path: /Users/me/studies/batch_folder
```

Folder import can take a while. The assistant should say the work has started and wait until it finishes before reporting counts. Do not use “open project” to import a file.

## List what is in the project

```text
List what studies and series are in the project.
```

Use inventory for “what series/patients are in the project?” For settings, ask to show the current project settings instead.

## Preview and process

With inventory available (or indices you already know):

```text
Show me a preview of patient 1, series 1.
```

```text
Remove burnt-in text from all series.
```

```text
Harmonize study and series descriptions for everything in the project.
```

Burnt-in text removal and Harmonize can run for minutes. The assistant should report that work has started and only summarize results when the job completes. Face blur is available in the desktop app and headless AI batch JSON — it is **not** an MCP chat tool.

## Good prompts

| Goal | Say |
|---|---|
| Learn the workflow | “How do I create a new project and change its settings later? Do not create anything yet.” |
| Create with defaults | “Create a new project named DemoCXR. Use defaults for everything else.” |
| Create with Retain options | “Create a Retain-options project named RetainDemo using CT and MR.” |
| Revise before creation | “Add US and show me the revised configuration.” |
| Confirm creation | “Yes, create it exactly as shown.” |
| See defaults | “Show me the project defaults and ranges.” |
| List projects | “What projects do I already have?” |
| Open a project | “Open the project named DemoCXR.” |
| See current settings | “Show my current project settings.” |
| Change settings | “Change the modalities to CT, MR and US.” |
| Import a file | “Import the DICOM file at this absolute path: /Users/me/studies/chest.dcm” |
| Import a folder | “Import the DICOM directory at this absolute path: /Users/me/studies/batch_folder” |
| Inventory | “List what studies and series are in the project.” |
| Preview | “Show me a preview of patient 1, series 1.” |
| Remove burnt-in text | “Remove burnt-in text from all series.” |
| Harmonize names | “Harmonize study and series descriptions for everything in the project.” |

## Related

- Server tool how-to (for the model): package asset `anonymizer/mcp/assets/instructions.md`
- Clinician wording source used by `anonymizer_usage`: package asset `anonymizer/mcp/assets/setup_help.json`
- Connect client / start server: [Run headless](index.md)
