"""Shared RGB US single-frame fixture paths and OCR expectations for Series View vs batch."""

from __future__ import annotations

from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

US_RGB_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "us_rgb_single_frame"
US_RGB_DCM = US_RGB_DIR / "US_RGB_SingleFrame.dcm"
US_RGB_PROJECT_T2_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "us_rgb_single_frame_project_t2"
US_RGB_PROJECT_T2_DCM = US_RGB_PROJECT_T2_DIR / "US_RGB_SingleFrame_project_t2_damaged.dcm"

# Series View detect-only: no noise filter; includes EasyOCR speckle hits.
US_RGB_SERIES_VIEW_OCR_TEXTS = [
    "mindray",
    "KMR",
    "X-RAYS",
    "26,05/2018",
    "13.09:16",
    "1009",
    "MI 0.9",
    "TIS 0.3",
    "AP",
    "3CSs",
    "A-Abdomen",
    "4",
    "B1 FHS.0 /",
    "D17.2 /",
    "G57",
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
US_RGB_BATCH_OCR_TEXTS = [
    "mindray",
    "KMR",
    "X-RAYS",
    "26,05/2018",
    "13.09:16",
    "MI 0.9",
    "TIS 0.3",
    "AP",
    "3CSs",
    "A-Abdomen",
    "B1 FHS.0 /",
    "D17.2 /",
    "G57",
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

# AI batch removal (UX log): default US whitelist + noise filter.
US_RGB_BATCH_REMOVED_TEXTS = [
    "mindray",
    "KMR",
    "X-RAYS",
    "26,05/2018",
    "13.09:16",
    "MI 0.9",
    "TIS 0.3",
    "AP",
    "3CSs",
    "B1 FHS.0 /",
    "D17.2 /",
    "G57",
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

US_RGB_BATCH_PIXELS_CHANGED = 18_316

US_RGB_BATCH_UX_LOG_VISIBLE_TEXTS = US_RGB_BATCH_REMOVED_TEXTS[:8]
US_RGB_BATCH_UX_LOG_HIDDEN_TEXTS = US_RGB_BATCH_REMOVED_TEXTS[8:]

US_RGB_SERIES_VIEW_SURVIVORS_AFTER_BATCH: list[str] = []

US_RGB_SERIES_VIEW_NOT_REMOVED_BY_BATCH = [
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

US_RGB_BATCH_LOG_TOKENS = (
    "mindray",
    "KMR",
    "26,05/2018",
    "TIS 0.3",
    "pixels blacked out",
)

US_RGB_PROJECT_T2_SERIES_VIEW_OCR_TEXTS = [
    "1009",
    "4-Abdomen",
    "4",
    "M",
    "Dist",
    "cm",
    "LIVER",
]
