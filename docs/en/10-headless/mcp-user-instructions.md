# How to talk to the Anonymizer MCP (for clinicians)

Use this when chatting with an LLM client connected to the RSNA Anonymizer MCP server.

You do **not** need to know every setting before creating a project. Give the assistant a project name and only the settings that matter to you. The MCP server combines those choices with the Anonymizer defaults, shows you the complete configuration, and creates nothing until you confirm it.

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

Clinical example:

```text
Create a project named ClinicalDemo with anonymization_policy clinical
and modalities CT and MR.
```

The assistant will prepare the configuration and reply with a review summary. It should identify:

- values you supplied;
- values taken from defaults;
- any warnings, such as an existing project at the destination.

**Nothing has been created at that point.** While you are still reviewing, any creation choice — including the language — can be revised; once you confirm, those creation choices are fixed.

You can then either change something:

```text
Add US and change the language to fr. Show me the revised configuration.
```

or confirm the exact revision shown:

```text
Yes, create it exactly as shown.
```

Only then is the project created and opened. Do not ask to open the same project again after creation.

### Settings you may supply when creating

You only need to mention the ones you care about:

- `project_name` — required;
- `anonymization_policy` — `strict` or `clinical`;
- `modalities` — for example `["CT", "MR", "US"]`;
- `language_code` — chosen once at creation, like the desktop welcome-screen language selector; it cannot be changed afterwards;
- `site_id` and `uid_root` — normally generated/defaulted;
- `storage_dir` — normally the default project store;
- local `scp` (`ip`, `port`, `aet`);
- `network_timeouts`.

The review summary shows the effective value of every create setting, including defaults.

## Configure a project later

After a project is created or opened, you can change mutable settings at any time:

```text
Change the open project settings: modalities ["CT", "MR", "US"].
```

Mutable settings are:

- `modalities`
- `transfer_syntaxes`
- local `scp`
- `network_timeouts`
- `anonymization_policy`

`project_name`, `storage_dir`, `site_id`, `uid_root`, and `language_code` are fixed after creation. The language is chosen once when the project is created (like the desktop welcome screen) and is not part of the project settings that can be edited later.

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

## Import a DICOM file

Once a project is open, give a **real absolute file path**:

```text
Import the DICOM file at this absolute path: /Users/me/studies/chest.dcm
```

There is no local-versus-PACS plan to choose before importing. Do not use `project_open` to import a file; that only opens/switches projects.

## List what is in the project

```text
List the series inventory for the open project (list_inventory).
```

Use inventory for “what series/patients are in the project?” For settings, ask to show the current project settings instead.

## Good prompts

| Goal | Say |
|---|---|
| Learn the workflow | “How do I create a new project and change its settings later? Do not create anything yet.” |
| Create with defaults | “Create a new project named DemoCXR. Use defaults for everything else.” |
| Create with choices | “Create a clinical project named ClinicalDemo with CT and MR.” |
| Revise before creation | “Add US and change the language to fr. Show me the revised configuration.” |
| Confirm creation | “Yes, create it exactly as shown.” |
| See defaults | “Show me the project defaults and ranges.” |
| See current settings | “Show my current project settings.” |
| Change settings | “Change the modalities to CT, MR and US.” |

## Related

- Server tool how-to (for the model): package asset `anonymizer/mcp/assets/instructions.md`
- Connect client / start server: [Run headless](index.md)
