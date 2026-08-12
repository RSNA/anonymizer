"""Shared Nobulela RGB US fixture paths and OCR expectations for Series View vs batch."""

from __future__ import annotations

from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

NOBULELA_US_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "nobulela_us_rgb"
NOBULELA_US_DCM = NOBULELA_US_DIR / "nobulela_US_RGB_SingleFrame_uncompressed.dcm"
NOBULELA_PROJECT_T2_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "nobulela_us_rgb_project_t2"
NOBULELA_PROJECT_T2_DCM = NOBULELA_PROJECT_T2_DIR / "nobulela_US_RGB_project_t2_damaged.dcm"

# Series View detect-only: no noise filter (V18-like); includes EasyOCR speckle hits.
NOBULELA_SERIES_VIEW_OCR_TEXTS = [
    "mindray",
    "KMR",
    "X-RAYS",
    "26,05/2018",
    "13.09:16",
    "1009",
    "MI 0.9",
    "TIS 0.3",
    "AP",
    "DIKO",
    "NOBULELA",
    "8211080464089",
    "3CSs",
    "A-Abdomen",
    "G57",
    "4",
    "B1 FHS.0 /",
    "D17.2 /",
    "4",
    "FRIO /",
    "IPS /",
    "DR7O",
    "B2 FHS.0 ",
    "D17.2 /",
    "G63",
    "FRIO /",
    "IPS /",
    "DR7O",
    "LLLOBEI",
    "10",
    "Dist",
    "15.23",
    "cm",
    "LIVER",
    "15",
    "99,/99",
    "8/8",
]

# Batch detect (noise filter, no whitelist): differs from batch removal (adds default whitelist).
NOBULELA_BATCH_OCR_TEXTS = [
    "mindray",
    "KMR",
    "X-RAYS",
    "26,05/2018",
    "13.09:16",
    "MI 0.9",
    "TIS 0.3",
    "AP",
    "DIKO",
    "NOBULELA",
    "8211080464089",
    "3CSs",
    "A-Abdomen",
    "G57",
    "B1 FHS.0 /",
    "D17.2 /",
    "FRIO /",
    "IPS /",
    "DR7O",
    "B2 FHS.0 ",
    "D17.2 /",
    "G63",
    "FRIO /",
    "IPS /",
    "DR7O",
    "LLLOBEI",
    "Dist",
    "15.23",
    "cm",
    "LIVER",
    "99,/99",
    "8/8",
]

# AI batch removal (UX log): default US whitelist + noise filter. 24 strings, 21,054 px.
# Log shows first 8 then "(+16 more)"; NOBULELA is string 10 (hidden in truncation).
NOBULELA_BATCH_REMOVED_TEXTS = [
    "mindray",
    "KMR",
    "X-RAYS",
    "26,05/2018",
    "13.09:16",
    "MI 0.9",
    "TIS 0.3",
    "AP",
    "DIKO",
    "NOBULELA",
    "8211080464089",
    "3CSs",
    "G57",
    "B1 FHS.0 /",
    "D17.2 /",
    "FRIO /",
    "IPS /",
    "DR7O",
    "B2 FHS.0",
    "G63",
    "LLLOBEI",
    "15.23",
    "99,/99",
    "8/8",
]

NOBULELA_BATCH_PIXELS_CHANGED = 21_054

# Visible in UX instance log before "(+14 more)".
NOBULELA_BATCH_UX_LOG_VISIBLE_TEXTS = NOBULELA_BATCH_REMOVED_TEXTS[:8]

# Hidden in UX log under "(+14 more)" — includes patient name/ID PHI.
NOBULELA_BATCH_UX_LOG_HIDDEN_TEXTS = NOBULELA_BATCH_REMOVED_TEXTS[8:]

# Detected in Series View (whitelist display) after batch blackout — aligned OCR path removes all.
NOBULELA_SERIES_VIEW_SURVIVORS_AFTER_BATCH: list[str] = []

# Detected in Series View but not removed by batch (whitelist anatomy/noise, or OCR variant).
NOBULELA_SERIES_VIEW_NOT_REMOVED_BY_BATCH = [
    "1009",
    "4",
    "A-Abdomen",
    "B2 FHS.0 ",
    "10",
    "Dist",
    "cm",
    "LIVER",
    "15",
]

# Tokens that appear in batch workflow log lines (summary truncates after 6–8 strings).
NOBULELA_BATCH_PHI_LOG_TOKENS = (
    "mindray",
    "KMR",
    "26,05/2018",
    "TIS 0.3",
    "pixels blacked out",
)
