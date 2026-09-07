# Send

## Goal

Send anonymized patients to a remote DICOM system or AWS S3, and optionally save a PHI lookup CSV.

## Send view

![Export](shots/macos/SendView.png)

1. From the Dashboard, click **Send** (echo first when using DICOM export).
2. Select patients (a patient may include several studies).
3. Send to the configured export server or AWS (if enabled in settings).
4. Watch status and timestamps; already-sent objects are not re-sent.

![Send status](shots/macos/SendView.png)

## Patient lookup CSV

![Save PHI CSV](shots/macos/SendView.png)

Use **Create Patient Lookup** to write a CSV under `/private/phi_export/`.

- **One row per series** (study fields repeated).
- Includes series AI fields (harmonized, face blurred, pixel PHI).
- Filename pattern includes site, project, and counts.

## What good looks like

- Send status completes; destination confirms objects.
- CSV opens in a spreadsheet with expected columns.

## If it fails

- Echo / auth failure → check export server or AWS Cognito credentials with IT.
- Nothing selected → select patients first.

## Next steps

Optional: [Run without the window](../10-headless/) for lab/server receive or overnight batch.
