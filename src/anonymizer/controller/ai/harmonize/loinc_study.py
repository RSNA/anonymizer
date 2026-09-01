"""LOINC StudyDescription ranking from Harmonized Playbook series descriptions."""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from anonymizer.controller.ai.harmonize.playbook import (
    ANATOMIC_PLANE_PLAYBOOK_CODES,
    BODY_PART_PLAYBOOK_CODES,
    IV_CONTRAST_PLAYBOOK_CODES,
    SERIES_TYPE_PLAYBOOK_CODES,
)
from anonymizer.utils.translate import get_current_language_code

logger = logging.getLogger(__name__)

LOINC_STUDY_DESCRIPTION_FILENAME = "LOINC_StudyDescription.csv"
DEFAULT_TOP_N = 8
DOMINANT_FRACTION_THRESHOLD = 0.65
CLEAR_WINNER_SCORE_GAP = 80.0
# Drop weak / unrelated rows so top-N cannot fill with alphabetical noise.
MIN_MATCH_SCORE = 100.0

# Playbook body-part codes → LOINC LongCommonName anatomy tokens.
# LOINC StudyDescription uses "Head" (not "Brain") for brain CT exams,
# and "Cervical/Thoracic/Lumbar spine" for segmental spine exams.
_BODY_PART_TO_LOINC_ANATOMY: dict[str, tuple[str, ...]] = {
    "Brain": ("Head",),
    "Head": ("Head",),
    "Neck": ("Neck",),
    "Ch": ("Chest",),
    "Abd": ("Abdomen",),
    "Pel": ("Pelvis",),
    "AbdPel": ("Abdomen", "Pelvis"),
    "CAP": ("Chest", "Abdomen", "Pelvis"),
    "Spine": ("Spine",),
    "CSp": ("Cervical spine",),
    "TSp": ("Thoracic spine",),
    "LSp": ("Lumbar spine",),
    "Breast": ("Breast",),
}

# Substrings in a LongCommonName that satisfy a preferred LOINC anatomy part.
# Multi-word phrases are matched against the normalized name (not token equality).
_LOINC_ANATOMY_MATCH_PHRASES: dict[str, tuple[str, ...]] = {
    "Head": ("head", "brain"),
    "Brain": ("brain", "head"),
    "Neck": ("neck",),
    "Chest": ("chest",),
    "Abdomen": ("abdomen",),
    "Pelvis": ("pelvis",),
    "Spine": ("spine", "cervical spine", "thoracic spine", "lumbar spine"),
    "Cervical spine": ("cervical spine", "cervical"),
    "Thoracic spine": ("thoracic spine", "thoracic"),
    "Lumbar spine": ("lumbar spine", "lumbar"),
    "Breast": ("breast",),
}

# Legacy token synonyms used for foreign-anatomy detection among ranked regions.
_LOINC_ANATOMY_SYNONYMS: dict[str, frozenset[str]] = {
    "Head": frozenset({"Head", "Brain"}),
    "Brain": frozenset({"Brain", "Head"}),
    "Neck": frozenset({"Neck"}),
    "Chest": frozenset({"Chest"}),
    "Abdomen": frozenset({"Abdomen"}),
    "Pelvis": frozenset({"Pelvis"}),
    "Spine": frozenset({"Spine", "Cervical", "Thoracic", "Lumbar"}),
    "Cervical spine": frozenset({"Cervical", "Spine"}),
    "Thoracic spine": frozenset({"Thoracic", "Spine"}),
    "Lumbar spine": frozenset({"Lumbar", "Spine"}),
    "Breast": frozenset({"Breast"}),
}

# Specialty / extremity phrases that must never pad top-N when not evidenced.
_UNRELATED_ANATOMY_PHRASES: frozenset[str] = frozenset(
    {
        "ankle",
        "adrenal",
        "appendix",
        "elbow",
        "knee",
        "wrist",
        "hand",
        "finger",
        "foot",
        "clavicle",
        "shoulder",
        "hip",
        "femur",
        "airway",
        "abdominal aorta",
        "brachial plexus",
        "extremity",
        "facial bones",
        "mandible",
        "maxillofacial",
        "orbit",
        "sinuses",
        "temporal bone",
        "pituitary",
        "sella",
        "thyroid",
        "heart",
        "coronary",
        "kidney",
        "liver",
        "pancreas",
        "prostate",
        "uterus",
        "rectum",
        "unspecified body",
    }
)

# TS BODY_PARTS region names → LOINC anatomy tokens.
_TS_REGION_TO_LOINC: dict[str, str] = {
    "Head": "Head",
    "Chest": "Chest",
    "Abdomen": "Abdomen",
}

_ANATOMY_RANK: dict[str, int] = {
    "Brain": 0,
    "Head": 1,
    "Neck": 2,
    "Chest": 3,
    "Abdomen": 4,
    "Pelvis": 5,
    "Cervical spine": 6,
    "Thoracic spine": 7,
    "Lumbar spine": 8,
    "Spine": 9,
    "Breast": 10,
}

_ANATOMY_TOKEN_NAMES: frozenset[str] = frozenset(
    {
        "Brain",
        "Head",
        "Neck",
        "Chest",
        "Abdomen",
        "Pelvis",
        "Spine",
        "Cervical",
        "Thoracic",
        "Lumbar",
        "Breast",
    }
)

_EXTRA_PENALTY_TOKENS: frozenset[str] = frozenset(
    {
        "angiogram",
        "limited",
        "3d",
        "post",
        "processing",
        "guidance",
        "perfusion",
        "coronary",
        "pulmonary",
        "lower",
        "extremity",
        "upper",
        "bilateral",
    }
)


@dataclass(frozen=True)
class LoincStudyMatch:
    loinc_number: str
    long_common_name: str
    score: float


@dataclass(frozen=True)
class StudyDescriptionAggregate:
    """Aggregated study-level signals from Playbook series strings (+ optional TS fractions)."""

    anatomy_parts: tuple[str, ...]  # full evidenced union, e.g. ("Chest", "Abdomen")
    preferred_anatomy_parts: tuple[str, ...]  # dominant-focused primary ranking set
    anatomy_fractions: tuple[tuple[str, float], ...]  # sorted LOINC anatomy → fraction
    contrast_family: str  # "WO" | "W" | "WO_AND_W"
    diagnostic_series_count: int
    series_descriptions: tuple[str, ...]


@dataclass(frozen=True)
class StudyDescriptionOffer:
    """Payload for Study Description auto-apply or dialog after Harmonize completes."""

    anon_study_uid: str
    fingerprint: tuple[str, ...]
    matches: tuple[LoincStudyMatch, ...]
    peer_study_uids: tuple[str, ...]  # other studies with same fingerprint (excludes self)
    ambiguous: bool = False


def loinc_study_description_csv_path(*, language_code: str | None = None) -> Path:
    lang = language_code or get_current_language_code() or "en_US"
    package_locales = Path(__file__).resolve().parents[3] / "assets" / "locales"
    for root in (Path("assets") / "locales", package_locales):
        candidate = root / lang / LOINC_STUDY_DESCRIPTION_FILENAME
        if candidate.is_file():
            return candidate
        fallback = root / "en_US" / LOINC_STUDY_DESCRIPTION_FILENAME
        if fallback.is_file():
            return fallback
    return package_locales / "en_US" / LOINC_STUDY_DESCRIPTION_FILENAME


@lru_cache(maxsize=4)
def load_loinc_study_descriptions(csv_path: str | None = None) -> tuple[tuple[str, str], ...]:
    """Return ``(LoincNumber, LongCommonName)`` rows (CT and all modalities)."""
    path = Path(csv_path) if csv_path else loinc_study_description_csv_path()
    if not path.is_file():
        logger.warning("LOINC StudyDescription CSV not found: %s", path)
        return ()
    rows: list[tuple[str, str]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            code = (row.get("LoincNumber") or "").strip()
            name = (row.get("LongCommonName") or "").strip()
            if code and name:
                rows.append((code, name))
    return tuple(rows)


def load_ct_loinc_study_descriptions(csv_path: str | None = None) -> tuple[tuple[str, str], ...]:
    return load_loinc_study_descriptions_for_prefix("CT ", csv_path=csv_path)


def load_loinc_study_descriptions_for_prefix(
    loinc_prefix: str,
    csv_path: str | None = None,
) -> tuple[tuple[str, str], ...]:
    """Return LOINC rows whose LongCommonName starts with ``loinc_prefix`` (e.g. ``CT `` / ``MR ``)."""
    return tuple(
        (code, name)
        for code, name in load_loinc_study_descriptions(csv_path)
        if name.startswith(loinc_prefix)
    )


def study_series_description_fingerprint(descriptions: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Sorted multiset of non-empty series Playbook descriptions."""
    cleaned = [str(d).strip() for d in descriptions if str(d).strip()]
    return tuple(sorted(cleaned))


def fingerprint_for_harmonized_study(anon_model, anon_study_uid: str) -> tuple[str, ...]:
    """Fingerprint of harmonized CT|MR series descriptions stored for a study."""
    return study_series_description_fingerprint(anon_model.get_ct_series_harmonized_descriptions(anon_study_uid))


def _split_playbook_tokens(description: str) -> list[str]:
    return [tok for tok in description.strip().split() if tok]


def parse_playbook_series_description(description: str) -> dict[str, object]:
    """Parse a Playbook series string into body parts, contrast, and series type."""
    tokens = _split_playbook_tokens(description)
    body_parts: list[str] = []
    contrast = ""
    series_type = ""
    plane = ""

    if not tokens:
        return {
            "body_parts": body_parts,
            "contrast": contrast,
            "series_type": series_type,
            "plane": plane,
            "is_localizer": False,
        }

    first = tokens[0]
    for part in first.split("+"):
        part = part.strip()
        if part in BODY_PART_PLAYBOOK_CODES or part in _BODY_PART_TO_LOINC_ANATOMY:
            body_parts.append(part)

    for tok in tokens[1:]:
        if tok in SERIES_TYPE_PLAYBOOK_CODES:
            series_type = tok
        elif tok in IV_CONTRAST_PLAYBOOK_CODES:
            contrast = tok
        elif tok in ANATOMIC_PLANE_PLAYBOOK_CODES:
            plane = tok

    return {
        "body_parts": body_parts,
        "contrast": contrast,
        "series_type": series_type,
        "plane": plane,
        "is_localizer": series_type == "Localizer",
    }


def _expand_anatomy(body_part_codes: list[str]) -> list[str]:
    parts: list[str] = []
    seen: set[str] = set()
    for code in body_part_codes:
        for anatomy in _BODY_PART_TO_LOINC_ANATOMY.get(code, ()):
            if anatomy not in seen:
                seen.add(anatomy)
                parts.append(anatomy)
    parts.sort(key=lambda name: (_ANATOMY_RANK.get(name, 99), name))
    return parts


def _contrast_is_wo(code: str) -> bool:
    return code == "WO" or code == ""


def _sort_anatomy(parts: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(parts, key=lambda name: (_ANATOMY_RANK.get(name, 99), name)))


def series_region_voxel_counts(series_path: Path) -> dict[str, int]:
    """Return TS region voxel counts from the series seg cache, or empty if unavailable."""
    from anonymizer.controller.ai.tseg.modality_profile import (
        default_ct_profile,
        resolve_profile_for_series,
    )
    from anonymizer.controller.ai.tseg.segment import (
        _segmentation_cache_valid,
        collect_structure_voxels,
        dominant_region_from_voxels,
        series_cache_dir,
    )

    series_path = Path(series_path)
    profile = resolve_profile_for_series(series_path) or default_ct_profile()
    seg_dir = series_cache_dir(series_path) / "seg"
    structures = list(profile.roi_subset)
    if not _segmentation_cache_valid(
        seg_dir,
        structures,
        anatomy_task=profile.anatomy_task,
        modality=profile.modality,
    ):
        return {}
    structure_voxels = collect_structure_voxels(seg_dir, structures)
    region = dominant_region_from_voxels(
        structure_voxels,
        structure_to_region=profile.structure_to_region,
    )
    return {name: count for name, count in region.region_voxels.items() if count > 0}


def aggregate_region_fractions(series_paths: Sequence[Path]) -> dict[str, float]:
    """Sum TS region voxels across series and return LOINC anatomy fractions."""
    totals: dict[str, int] = {}
    for series_path in series_paths:
        for region, count in series_region_voxel_counts(series_path).items():
            loinc = _TS_REGION_TO_LOINC.get(region)
            if loinc is None or count <= 0:
                continue
            totals[loinc] = totals.get(loinc, 0) + count
    total = sum(totals.values())
    if total <= 0:
        return {}
    return {name: count / total for name, count in totals.items()}


def preferred_anatomy_from_fractions(
    anatomy_parts: Sequence[str],
    fractions: Mapping[str, float],
    *,
    dominant_threshold: float = DOMINANT_FRACTION_THRESHOLD,
) -> tuple[str, ...]:
    """
    Prefer dominant-only anatomy when one region clearly dominates.

    Otherwise keep the full evidenced union from Playbook series descriptions.
    """
    union = _sort_anatomy(anatomy_parts)
    if not fractions or not union:
        return union

    ranked = sorted(
        ((name, fractions.get(name, 0.0)) for name in union),
        key=lambda item: (-item[1], _ANATOMY_RANK.get(item[0], 99), item[0]),
    )
    top_name, top_frac = ranked[0]
    if top_frac >= dominant_threshold:
        preferred = [top_name]
        for name, frac in ranked[1:]:
            # Keep a secondary region only when it is also substantial and close to the top.
            if frac >= 0.25 and (top_frac - frac) < 0.20:
                preferred.append(name)
        return _sort_anatomy(preferred)
    return union


def aggregate_study_from_series_descriptions(
    series_descriptions: list[str] | tuple[str, ...],
    *,
    region_fractions: Mapping[str, float] | None = None,
) -> StudyDescriptionAggregate:
    """Aggregate Playbook series descriptions into study-level anatomy + contrast."""
    fingerprint = study_series_description_fingerprint(series_descriptions)
    anatomy: list[str] = []
    seen_anatomy: set[str] = set()
    has_wo = False
    has_w = False
    diagnostic = 0

    for description in fingerprint:
        parsed = parse_playbook_series_description(description)
        if parsed["is_localizer"]:
            continue
        series_type = str(parsed["series_type"] or "")
        if series_type in {"Radiation_Dose", "Contrast_Dose", "Screenshot", "Monitoring"}:
            continue
        diagnostic += 1
        for part in _expand_anatomy(list(parsed["body_parts"])):  # type: ignore[arg-type]
            if part not in seen_anatomy:
                seen_anatomy.add(part)
                anatomy.append(part)
        contrast = str(parsed["contrast"] or "")
        if _contrast_is_wo(contrast):
            has_wo = True
        else:
            has_w = True

    anatomy_parts = _sort_anatomy(anatomy)
    fractions = dict(region_fractions or {})
    preferred = preferred_anatomy_from_fractions(anatomy_parts, fractions)

    if has_wo and has_w:
        contrast_family = "WO_AND_W"
    elif has_w:
        contrast_family = "W"
    else:
        contrast_family = "WO"

    fraction_items = tuple(
        sorted(
            ((name, float(frac)) for name, frac in fractions.items() if frac > 0),
            key=lambda item: (-item[1], _ANATOMY_RANK.get(item[0], 99), item[0]),
        )
    )

    return StudyDescriptionAggregate(
        anatomy_parts=anatomy_parts,
        preferred_anatomy_parts=preferred,
        anatomy_fractions=fraction_items,
        contrast_family=contrast_family,
        diagnostic_series_count=diagnostic,
        series_descriptions=fingerprint,
    )


def _anatomy_phrase(parts: tuple[str, ...]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return " and ".join(parts)


def _contrast_suffixes(contrast_family: str) -> list[str]:
    if contrast_family == "WO_AND_W":
        return ["WO and W contrast IV", "W contrast IV", "WO contrast"]
    if contrast_family == "W":
        return ["W contrast IV", "WO and W contrast IV"]
    return ["WO contrast", "W contrast IV"]


def build_canonical_loinc_phrases(
    aggregate: StudyDescriptionAggregate,
    *,
    loinc_prefix: str = "CT ",
) -> list[str]:
    """Build preferred then full-union LongCommonName candidates for ``loinc_prefix``."""
    suffixes = _contrast_suffixes(aggregate.contrast_family)
    phrases: list[str] = []
    seen: set[str] = set()
    modality_label = loinc_prefix.strip() or "CT"

    def _map_part(part: str) -> str:
        # LOINC StudyDescription uses Brain (not Head) for MR neuro exams.
        if modality_label.upper() == "MR" and part == "Head":
            return "Brain"
        return part

    def _add(parts: tuple[str, ...]) -> None:
        mapped = tuple(_map_part(p) for p in parts)
        anatomy = _anatomy_phrase(mapped)
        if not anatomy:
            return
        for suffix in suffixes:
            phrase = f"{modality_label} {anatomy} {suffix}"
            key = _normalize_name(phrase)
            if key not in seen:
                seen.add(key)
                phrases.append(phrase)

    _add(aggregate.preferred_anatomy_parts)
    if aggregate.anatomy_parts != aggregate.preferred_anatomy_parts:
        _add(aggregate.anatomy_parts)
    return phrases


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _tokenize_loinc_name(name: str) -> set[str]:
    lowered = _normalize_name(name)
    return set(re.findall(r"[a-z0-9]+", lowered))


def anatomy_tokens_in_loinc_name(name: str) -> frozenset[str]:
    tokens = _tokenize_loinc_name(name)
    found: set[str] = set()
    for part in _ANATOMY_TOKEN_NAMES:
        if part.lower() in tokens:
            found.add(part)
    # Normalize Brain ↔ Head for comparisons against preferred LOINC anatomy.
    if "Brain" in found:
        found.add("Head")
    return frozenset(found)


def _synonyms_for_anatomy(part: str) -> frozenset[str]:
    return _LOINC_ANATOMY_SYNONYMS.get(part, frozenset({part}))


def _match_phrases_for_anatomy(part: str) -> tuple[str, ...]:
    return _LOINC_ANATOMY_MATCH_PHRASES.get(part, (part.lower(),))


def _name_matches_anatomy_part(name: str, part: str) -> bool:
    lowered = _normalize_name(name)
    return any(phrase in lowered for phrase in _match_phrases_for_anatomy(part))


def _primary_loinc_anatomy_phrase(name: str) -> str:
    """Return the leading anatomy phrase of a LOINC LongCommonName (before contrast / and CT|MR)."""
    normalized = _normalize_name(name)
    for prefix in ("ct ", "mr "):
        if normalized.startswith(prefix):
            rest = normalized[len(prefix) :]
            break
    else:
        return ""
    cut_points = [
        rest.find(" wo contrast"),
        rest.find(" w contrast"),
        rest.find(" wo and w"),
        rest.find(" and ct "),
        rest.find(" and mr "),
        rest.find(" for "),
    ]
    cut = min((p for p in cut_points if p >= 0), default=-1)
    primary = rest[:cut].strip() if cut >= 0 else rest.strip()
    return primary


def _allowed_anatomy_parts(aggregate: StudyDescriptionAggregate) -> frozenset[str]:
    allowed: set[str] = set()
    for part in aggregate.anatomy_parts or aggregate.preferred_anatomy_parts:
        allowed.add(part)
        allowed.update(_synonyms_for_anatomy(part))
    for part in aggregate.preferred_anatomy_parts:
        allowed.add(part)
        allowed.update(_synonyms_for_anatomy(part))
    return frozenset(allowed)


def _name_covers_required_anatomy(name: str, required_parts: Sequence[str]) -> bool:
    """True when every required anatomy part (or a synonym phrase) appears in the LOINC name."""
    if not required_parts:
        return True
    return all(_name_matches_anatomy_part(name, part) for part in required_parts)


def _name_has_foreign_anatomy(name: str, allowed: frozenset[str]) -> bool:
    """True when the name cites a ranked anatomy region outside the study evidence."""
    if not allowed:
        return False
    for part in anatomy_tokens_in_loinc_name(name):
        synonyms = _synonyms_for_anatomy(part)
        if part in allowed or not synonyms.isdisjoint(allowed):
            continue
        # Spine token is OK when a segmental spine part is allowed.
        if part == "Spine" and any("spine" in a.lower() for a in allowed):
            continue
        if part in {"Cervical", "Thoracic", "Lumbar"} and (
            "Spine" in allowed or any(part.lower() in a.lower() for a in allowed)
        ):
            continue
        return True
    return False


def _name_has_unrelated_specialty_anatomy(
    name: str,
    required_parts: Sequence[str],
) -> bool:
    """
    Reject specialty/extremity LOINC rows that are not part of the required anatomy.

    Prevents alphabetical top-N padding (ankle, adrenal, …) when required coverage fails
    only weakly or when the primary phrase is unrelated.
    """
    primary = _primary_loinc_anatomy_phrase(name)
    if not primary:
        return True
    # Primary must match at least one required anatomy phrase.
    if required_parts and not any(
        any(phrase in primary for phrase in _match_phrases_for_anatomy(part)) for part in required_parts
    ):
        return True
    # Deny known specialty phrases unless they are explicitly required.
    required_lower = " ".join(required_parts).lower()
    for phrase in _UNRELATED_ANATOMY_PHRASES:
        if phrase in primary and phrase not in required_lower:
            # Allow "orbit"/sinus only when Head is required? Still specialty — keep denied
            # unless the required phrase itself contains it.
            if not any(phrase in part.lower() for part in required_parts):
                return True
    return False


def _name_contrast_family(name: str) -> str | None:
    name_l = _normalize_name(name)
    if "wo and w" in name_l:
        return "WO_AND_W"
    if "wo contrast" in name_l:
        return "WO"
    if "w contrast" in name_l:
        return "W"
    return None


def _score_loinc_name(name: str, aggregate: StudyDescriptionAggregate, canonicals: list[str]) -> float:
    normalized = _normalize_name(name)
    for index, canonical in enumerate(canonicals):
        canon = _normalize_name(canonical)
        if normalized == canon:
            return 1000.0 - index * 10.0
        # Prefix only on a word boundary so "CT Head WO contrast and …" matches
        # "CT Head WO contrast", but not accidental substring collisions.
        if normalized.startswith(canon + " ") or normalized.startswith(canon + " and"):
            return 900.0 - index * 10.0

    tokens = _tokenize_loinc_name(name)
    if "ct" not in tokens and "mr" not in tokens:
        return -1e9

    target_parts = aggregate.preferred_anatomy_parts or aggregate.anatomy_parts
    if not _name_covers_required_anatomy(name, target_parts):
        return -1e9
    if _name_has_unrelated_specialty_anatomy(name, target_parts):
        return -1e9
    allowed = _allowed_anatomy_parts(aggregate)
    if _name_has_foreign_anatomy(name, allowed):
        return -1e9

    score = 0.0
    for part in target_parts:
        if _name_matches_anatomy_part(name, part):
            score += 40.0
        else:
            score -= 80.0

    for anatomy in _ANATOMY_RANK:
        if not _name_matches_anatomy_part(name, anatomy):
            continue
        if anatomy in target_parts:
            continue
        # Synonym overlap with preferred (e.g. Brain name when Head preferred).
        if any(_name_matches_anatomy_part(name, pref) for pref in target_parts) and anatomy in {
            "Head",
            "Brain",
            "Spine",
            "Cervical spine",
            "Thoracic spine",
            "Lumbar spine",
        }:
            # Do not penalize Head↔Brain or Spine↔segmental aliases already covered.
            if anatomy in {"Head", "Brain"} and any(p in {"Head", "Brain"} for p in target_parts):
                continue
            if "spine" in anatomy.lower() and any("spine" in p.lower() for p in target_parts):
                continue
        if anatomy in aggregate.anatomy_parts:
            score -= 15.0
        else:
            score -= 35.0

    name_l = normalized
    is_wo_only = "wo contrast" in name_l and "wo and w" not in name_l
    is_w_only = ("w contrast" in name_l or "w contrast iv" in name_l) and "wo" not in name_l
    is_wo_and_w = "wo and w" in name_l

    if aggregate.contrast_family == "WO":
        if is_wo_only:
            score += 50.0
        elif is_wo_and_w:
            score += 10.0
        elif is_w_only:
            score -= 40.0
    elif aggregate.contrast_family == "W":
        if is_w_only:
            score += 50.0
        elif is_wo_and_w:
            score += 15.0
        elif is_wo_only:
            score -= 40.0
    else:
        if is_wo_and_w:
            score += 55.0
        elif is_w_only:
            score += 25.0
        elif is_wo_only:
            score -= 20.0

    for penalty in _EXTRA_PENALTY_TOKENS:
        if penalty in tokens:
            score -= 25.0

    word_count = len(name.split())
    score -= max(0, word_count - 6) * 2.0
    return score


def ranking_is_ambiguous(
    matches: Sequence[LoincStudyMatch],
    aggregate: StudyDescriptionAggregate,
    *,
    score_gap: float = CLEAR_WINNER_SCORE_GAP,
) -> bool:
    """
    Return True when the user should choose among competing LOINC names.

    Clear (False) when the top score leads by ``score_gap``, or preferred single-region
    anatomy matches the top name (and contrast family).
    """
    if len(matches) < 2:
        return False

    top, second = matches[0], matches[1]
    if top.score - second.score >= score_gap:
        return False

    preferred = frozenset(aggregate.preferred_anatomy_parts)
    top_anatomy = anatomy_tokens_in_loinc_name(top.long_common_name)
    second_anatomy = anatomy_tokens_in_loinc_name(second.long_common_name)

    # Clear: single preferred region (or synonym) matches top name + contrast.
    if len(preferred) == 1:
        part = next(iter(preferred))
        if not _synonyms_for_anatomy(part).isdisjoint(top_anatomy):
            # Prefer simple single-region names without compound "and CT …" extras.
            if " and ct " not in _normalize_name(top.long_common_name) and " and mr " not in _normalize_name(
                top.long_common_name
            ):
                top_contrast = _name_contrast_family(top.long_common_name)
                if top_contrast is None or top_contrast == aggregate.contrast_family or (
                    aggregate.contrast_family == "W" and top_contrast == "W"
                ):
                    return False

    if top_anatomy != second_anatomy and (top.score - second.score) < score_gap:
        return True

    fractions = dict(aggregate.anatomy_fractions)
    dominant_frac = max(fractions.values()) if fractions else 0.0
    return dominant_frac < DOMINANT_FRACTION_THRESHOLD and top_anatomy != second_anatomy


def rank_loinc_study_descriptions(
    series_descriptions: list[str] | tuple[str, ...],
    *,
    top_n: int = DEFAULT_TOP_N,
    csv_path: str | None = None,
    region_fractions: Mapping[str, float] | None = None,
    series_paths: Sequence[Path] | None = None,
    loinc_prefix: str = "CT ",
) -> list[LoincStudyMatch]:
    """Rank LOINC StudyDescription rows for the given Playbook series descriptions."""
    fractions = dict(region_fractions) if region_fractions is not None else None
    if fractions is None and series_paths:
        fractions = aggregate_region_fractions(series_paths)

    aggregate = aggregate_study_from_series_descriptions(
        series_descriptions,
        region_fractions=fractions,
    )
    if not aggregate.anatomy_parts and aggregate.diagnostic_series_count == 0:
        for description in study_series_description_fingerprint(series_descriptions):
            parsed = parse_playbook_series_description(description)
            for part in _expand_anatomy(list(parsed["body_parts"])):  # type: ignore[arg-type]
                if part not in aggregate.anatomy_parts:
                    new_parts = _sort_anatomy(set(aggregate.anatomy_parts) | {part})
                    preferred = preferred_anatomy_from_fractions(new_parts, dict(aggregate.anatomy_fractions))
                    aggregate = StudyDescriptionAggregate(
                        anatomy_parts=new_parts,
                        preferred_anatomy_parts=preferred,
                        anatomy_fractions=aggregate.anatomy_fractions,
                        contrast_family=aggregate.contrast_family,
                        diagnostic_series_count=aggregate.diagnostic_series_count,
                        series_descriptions=aggregate.series_descriptions,
                    )

    canonicals = build_canonical_loinc_phrases(aggregate, loinc_prefix=loinc_prefix)
    scored: list[LoincStudyMatch] = []
    for code, name in load_loinc_study_descriptions_for_prefix(loinc_prefix, csv_path=csv_path):
        score = _score_loinc_name(name, aggregate, canonicals)
        if score < MIN_MATCH_SCORE:
            continue
        required = aggregate.preferred_anatomy_parts or aggregate.anatomy_parts
        if not _name_covers_required_anatomy(name, required):
            continue
        if _name_has_unrelated_specialty_anatomy(name, required):
            continue
        if _name_has_foreign_anatomy(name, _allowed_anatomy_parts(aggregate)):
            continue
        scored.append(LoincStudyMatch(loinc_number=code, long_common_name=name, score=score))

    scored.sort(key=lambda item: (-item.score, item.long_common_name, item.loinc_number))
    return scored[: max(1, top_n)] if scored else []


def build_study_description_ranking(
    series_descriptions: list[str] | tuple[str, ...],
    *,
    top_n: int = DEFAULT_TOP_N,
    csv_path: str | None = None,
    region_fractions: Mapping[str, float] | None = None,
    series_paths: Sequence[Path] | None = None,
    loinc_prefix: str = "CT ",
) -> tuple[StudyDescriptionAggregate, list[LoincStudyMatch], bool]:
    """Return aggregate, ranked matches, and whether ranking is ambiguous."""
    fractions = dict(region_fractions) if region_fractions is not None else None
    if fractions is None and series_paths:
        fractions = aggregate_region_fractions(series_paths)

    aggregate = aggregate_study_from_series_descriptions(
        series_descriptions,
        region_fractions=fractions,
    )
    matches = rank_loinc_study_descriptions(
        series_descriptions,
        top_n=top_n,
        csv_path=csv_path,
        region_fractions=fractions,
        loinc_prefix=loinc_prefix,
    )
    ambiguous = ranking_is_ambiguous(matches, aggregate)
    return aggregate, matches, ambiguous
