# 8.1 Remove Pixel PHI

Some images have **patient names or labels drawn onto the pixels**. Cleaning DICOM tags alone does not remove them.

## Demo series

| Series | Path | Used for |
| --- | --- | --- |
| **`davidson_cxr`** | `tests/controller/assets/test_dcm_files/davidson_cxr` | Whitelist → Detect → **Black out** |
| **`us_rgb_single_frame`** | `tests/controller/assets/test_dcm_files/us_rgb_single_frame` (`US_RGB_SingleFrame.dcm`) | Detect → **Blend into background** |

Import each folder into your project, then open the series in **Series View**.

## Goal

1. On `davidson_cxr`, detect burned-in text and **black out** PHI while keeping useful markers via the default whitelist.
2. On `us_rgb_single_frame`, detect burned-in text and remove it by **blending into the background** (inpaint).

## Before you start

1. Complete [AI Features setup](../../03-ai-features-setup/) so OCR models are ready.
2. Import the demo series and open them in Series View from [Dataset](../../07-view/).

## Workflow on `davidson_cxr` (black out)

Follow these steps in order. Screenshots match this fixture.

### 1. Default whitelist and Frame context

1. Keep the **default whitelist** (do not clear it).
2. Set edit context to **Frame** (not whole series yet).

![Default whitelist + Frame](shots/macos/Process_RemovePixel_Whitelist.png)

### 2. Detect Text

1. Click **Detect Text**.
2. Wait until detection finishes. **Green rectangles** mark text that would be removed.

![Detect Text on davidson_cxr](shots/macos/Process_RemovePixel_Detect.png)

On this chest X-ray you should see green boxes around the patient name, date, DOB, and similar PHI — but **not** around **Portable** or **L**. Those words are already on the default whitelist, so Detect Text leaves them alone.

**Whitelist match dropdown** (next to Defaults / Clear — here set to **Standard**):

Controls how closely OCR text must match a whitelist entry to be treated as a keeper:

| Setting | Effect |
| --- | --- |
| **Exact** | Only hide text that matches a whitelist entry letter-for-letter |
| **Strict** | Almost exact — tiny OCR mistakes only |
| **Standard** (default) | Allows small OCR errors (for example `AXIL` still matches `AXIAL`) |
| **Lenient** | Most forgiving — better for noisy text and short markers |

Use a stricter setting if too much text is skipped; use a looser one if useful markers keep getting boxed.

### 3. Review and whitelist keepers

1. If a green rectangle covers text you want to **keep**, click that rectangle.
2. The text is added to the whitelist on the left and will not be removed.

On `davidson_cxr`, **Portable** and **L** are already covered by the default whitelist — you usually do not need to add them again.

### 4. Remove Text using black out

1. Set the removal mode dropdown to **Black out text**.
2. Click **Remove Text**.
3. PHI regions become solid black; whitelisted keepers stay.
4. Click **Save Pixel Changes** when you are satisfied.

![Remove Text black out on davidson_cxr](shots/macos/Process_RemovePixel_Remove.png)

Black out is the usual choice for de-identification: removed text is clearly gone and cannot be recovered from the pixels.

## Workflow on `us_rgb_single_frame` (blend into background)

Use this color ultrasound frame when you want removed text to look like nearby tissue instead of black bars.

### 5. Remove Text using blend with background

1. Import and open **`us_rgb_single_frame`** (`US_RGB_SingleFrame.dcm`) in Series View.
2. Keep edit context on **Frame**.
3. Set the removal mode dropdown to **Blend into background**.
4. Click **Detect Text** and wait for the green rectangles.

![Detect Text on us_rgb_single_frame](shots/macos/Process_RemovePixel_US_Detect.png)

5. Click **Remove Text**.
6. Detected text is painted out by blending with surrounding pixels (inpaint), then **Save Pixel Changes**.

![Remove Text blend on us_rgb_single_frame](shots/macos/Process_RemovePixel_US_Blend.png)

**Black out** vs **Blend into background**: black out replaces text with black; blend fills the area so it matches the image around it. Prefer black out when you need an obvious, irreversible redaction; prefer blend when a less conspicuous result is acceptable (for example some ultrasound overlays).

## After the demo

- Dataset **Pixel PHI** status should update for each series you saved.
- Modality whitelists and the match dropdown (Exact → Lenient) live in Series View; stricter matching means fewer OCR hits are treated as whitelist keepers.
- To run the same tool on many studies, see [8.4 Run on many studies](../05-run-on-many-studies/).

## What good looks like

- On `davidson_cxr`: PHI blacked out; orientation markers kept if whitelisted.
- On `us_rgb_single_frame`: burned-in labels blended away without solid black bars.
- **Pixel PHI** column updates in Dataset.

## If it fails

- Many false boxes → tighten match strictness; whitelist keepers.
- Missed text → manual blackout.
- Tools greyed out → finish [AI Features](../../03-ai-features-setup/).

## Next steps

Continue with [8.2 Harmonize names](../03-harmonize-names/) using **`Brain_Ax_EarlyArt`**.
