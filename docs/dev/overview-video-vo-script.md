# Overview video — timed voiceover script

Slick ~**1:45** product overview for RSNA DICOM Anonymizer.  
**Visuals:** prefer short live screen captures; fall back to EN macOS help shots under `docs/en/**/shots/macos/`.  
**PHI:** demo fixtures only (`davidson_cxr`, `CT_Head_With_Contrast`, `us_rgb_single_frame`, `demo_report_pdf`).  
**Tone:** calm, clinician-facing; plain English; no standards codes on screen unless unavoidable.

Delivery tip: ~145–155 words/min. Total VO ≈ **250–270 words**.

---

## Shot list (timeline)

| Time | On-screen (preferred) | Fallback PNG | Lower-third |
| --- | --- | --- | --- |
| 0:00–0:08 | Title card + soft fade to Welcome | `02-install/.../Welcome.png` | RSNA DICOM Anonymizer |
| 0:08–0:18 | AI Features dialog (models ready) | `03-ai-features-setup/.../AiFeaturesSetup.png` | Optional AI models |
| 0:18–0:32 | New Project → De-identification Options (Retain) | `NewProjectSettings.png` → `DeidentificationOptions.png` | Project & options |
| 0:32–0:42 | Import finishes → Dashboard / Dataset | `ImportDavidson_Done.png` → `Dataset.png` | Import & review |
| 0:42–0:55 | Series View: Detect Text → Remove (CXR) | `Process_RemovePixel_Detect.png` → `…_Remove.png` | Burned-in text |
| 0:55–1:08 | Report Text Review (+ optional Metadata) | `ReportTextReview.png` | Reports & metadata |
| 1:08–1:22 | Harmonize results → segmented series; quick face blur | `Process_Harmonize_Description.png` → `…_SegmentedSeries.png` → `Process_FaceBlur_Gaussian.png` | Names & faces |
| 1:22–1:35 | AI Batch running → Send sent | `AiBatchRunning.png` → `SendView_Sent.png` | Batch & send |
| 1:35–1:45 | End card: manual URL / GitHub | Welcome or logo | Docs & download |

Optional B-roll inserts (if pacing allows): US blend (`Process_RemovePixel_US_Blend.png`), Description Mappings (`DescriptionMappings.png`), Analytics (`Dashboard_Analytics.png`).

---

## Voiceover (timed)

### 0:00–0:08 — Open

**VO:**  
The RSNA DICOM Anonymizer prepares medical imaging for research—on your computer, under your control.

**Visual:** Title → Welcome.  
**Caption:** Local de-identification for research imaging.

---

### 0:08–0:18 — AI Features

**VO:**  
Optional AI models download once from Welcome—so you can clean burned-in text, review leftover identifiers, harmonize names, and blur faces when you need them.

**Visual:** Ai Features setup.  
**Caption:** Install models when you need them.

---

### 0:18–0:32 — Project & options

**VO:**  
Create a project, choose how thorough de-identification should be, and keep a clear script of which labels stay, change, or go.

**Visual:** New Project Settings → De-identification Options (Retain preset visible).  
**Caption:** Your rules. Your storage.

---

### 0:32–0:42 — Import & Dataset

**VO:**  
Import from folders or a hospital archive. Identity in the file labels is cleaned at import—then review the curated Dataset.

**Visual:** Import done → Dataset tree (studies expanded).  
**Caption:** Clean at import. Review with confidence.

---

### 0:42–0:55 — Burned-in text

**VO:**  
When names or IDs are drawn on the picture itself, Detect finds them. Remove blacks them out—or blends them away on color ultrasound—while you keep orientation markers you whitelist.

**Visual:** Detect → Remove on chest X-ray; optional 1s US blend.  
**Caption:** Pixel PHI, under your whitelist.

---

### 0:55–1:08 — Reports & metadata

**VO:**  
Structured reports and PDFs open in Report Text Review. Spot leftover identifiers in tags with Metadata—Detect, remove, then Save.

**Visual:** Report Text Review; cut to Metadata Detect or Remove if time.  
**Caption:** Text in reports and tags.

---

### 1:08–1:22 — Harmonize & face blur

**VO:**  
Harmonize proposes standard series and study names—and on CT or MR, anatomy overlays you can latch. For head exams, blur recognizable faces before you share.

**Visual:** Harmonize results → segmented series → face blur preview.  
**Caption:** Consistent names. Protected faces.

---

### 1:22–1:35 — Batch & send

**VO:**  
Run the same tools across many studies overnight—or send the research-safe copy to your archive or cloud.

**Visual:** AI Batch running → Send complete.  
**Caption:** Scale up. Send out.

---

### 1:35–1:45 — Close

**VO:**  
RSNA DICOM Anonymizer—open tools for safer imaging research. Manual and downloads are linked below.

**Visual:** End card.  
**Caption:** docs · GitHub · PyPI  
*(Fill final URLs when you publish the cut.)*

---

## Full VO (paste for ElevenLabs)

Use as one take; editor splits to timeline.

> The RSNA DICOM Anonymizer prepares medical imaging for research—on your computer, under your control.  
> Optional AI models download once from Welcome—so you can clean burned-in text, review leftover identifiers, harmonize names, and blur faces when you need them.  
> Create a project, choose how thorough de-identification should be, and keep a clear script of which labels stay, change, or go.  
> Import from folders or a hospital archive. Identity in the file labels is cleaned at import—then review the curated Dataset.  
> When names or IDs are drawn on the picture itself, Detect finds them. Remove blacks them out—or blends them away on color ultrasound—while you keep orientation markers you whitelist.  
> Structured reports and PDFs open in Report Text Review. Spot leftover identifiers in tags with Metadata—Detect, remove, then Save.  
> Harmonize proposes standard series and study names—and on CT or MR, anatomy overlays you can latch. For head exams, blur recognizable faces before you share.  
> Run the same tools across many studies overnight—or send the research-safe copy to your archive or cloud.  
> RSNA DICOM Anonymizer—open tools for safer imaging research. Manual and downloads are linked below.

**Approx. word count:** 262 → ~1:45 at 150 wpm.

---

## Production checklist

- [ ] Light theme, English UI, fixture data only  
- [ ] Cursor visible on Detect / Remove / Harmonize / Batch (live clips)  
- [ ] No hospital AE titles or site names that identify a real site  
- [ ] Captions burned in (Descript/CapCut) matching lower-thirds above  
- [ ] Music bed under −18 dB relative to VO  
- [ ] Export 1080p 30 fps; 9:16 cut optional later from same VO  

## Chapter reuse

| Overview beat | Tutorial follow-up |
| --- | --- |
| Install / AI Features | `docs/en/tutorials/t1-install.md` |
| Project / import | `t2-project-import.md` |
| Burned-in text | `t3-burned-in.md` |
| Harmonize | `t4-harmonize.md` |
| Face blur | `t5-face-blur.md` |
| Batch | `t6-batch.md` |
