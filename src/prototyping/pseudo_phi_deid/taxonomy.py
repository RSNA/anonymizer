"""OpenMed raw-label → action (blank / ignore / defer-to-script).

Unknown labels default to **ignore**. Keep this map in sync with observed
histograms (`phase_0_characterize`, PseudoPHI-eval SCORECARD).
"""

from typing import Literal

Action = Literal["blank", "synth", "ignore", "defer-to-script"]

# Runtime overrides (optional); scrub uses DEFAULT_ACTIONS when empty.
ACTIONS: dict[str, Action] = {}

# Gold blanks free-text PHI on NER spans (step 6).
# Step 4 caret→space is prepare (not taxonomy); USER_NAME still blanks if seen.
DEFAULT_ACTIONS: dict[str, Action] = {
    # Person / name

    "FIRST_NAME": "blank",
    "LAST_NAME": "blank",
    "MIDDLE_NAME": "blank",
    "NAME": "blank",
    "PERSON": "blank",
    "PATIENT": "blank",
    "DOCTOR": "blank",
    "USER_NAME": "blank",
    "USERNAME": "blank",
    # Address / geo
    "STREET_ADDRESS": "blank",
    "STREET": "blank",
    "ADDRESS": "blank",
    "CITY": "blank",
    "STATE": "blank",
    "ZIP": "blank",
    "ZIPCODE": "blank",
    "POSTCODE": "blank",
    "COUNTRY": "blank",
    # Contact
    "PHONE": "blank",
    "PHONE_NUMBER": "blank",
    "FAX_NUMBER": "blank",
    "EMAIL": "blank",
    "EMAIL_ADDRESS": "blank",
    # Identifiers (patient / coverage / biometric)
    "CUSTOMER_ID": "blank",
    "CREDIT_DEBIT_CARD": "blank",
    "ACCOUNT_NUMBER": "blank",
    "EMPLOYEE_ID": "blank",
    "CERTIFICATE_LICENSE_NUMBER": "blank",
    "HEALTH_PLAN_BENEFICIARY_NUMBER": "blank",
    "BIOMETRIC_IDENTIFIER": "blank",
    "UNIQUE_ID": "blank",
    "ID": "blank",
    "MRN": "blank",
    "PATIENT_ID": "blank",
    "SSN": "blank",
    # Facility in free text
    "HOSPITAL": "blank",
    "FAC": "blank",
    # Whole DA/DT → script DATEINC. Free-text DATE spans: defer for now; long-tail
    # cases (e.g. glued Sep1999) collected before adding NER-prep exceptions.
    "DATE": "defer-to-script",
    "DOB": "defer-to-script",
    "DATE_OF_BIRTH": "defer-to-script",
    # Org / manufacturer noise in free text (script owns Institution* tags)
    "COMPANY_NAME": "ignore",
}


def normalize_raw(raw: str) -> str:
    key = str(raw or "").strip().upper()
    if key.startswith("B-") or key.startswith("I-"):
        key = key[2:]
    return key.replace("-", "_")


def resolve_action(raw_label: str, *, use_defaults: bool = True) -> Action:
    key = normalize_raw(raw_label)
    if key in ACTIONS:
        return ACTIONS[key]
    if use_defaults and key in DEFAULT_ACTIONS:
        return DEFAULT_ACTIONS[key]
    return "ignore"


def lock_taxonomy_from_histogram(
    histogram: dict[str, int],
    *,
    min_count: int = 1,
) -> dict[str, Action]:
    """Lock ACTIONS from observed raw labels (prefer DEFAULT_ACTIONS)."""
    locked: dict[str, Action] = {}
    for raw, count in histogram.items():
        key = normalize_raw(raw)
        if count < min_count:
            continue
        locked[key] = resolve_action(key)
    ACTIONS.clear()
    ACTIONS.update(locked)
    return dict(ACTIONS)


def taxonomy_table_md() -> str:
    rows = sorted(ACTIONS.items()) if ACTIONS else sorted(DEFAULT_ACTIONS.items())
    lines = [
        "| raw_label | action |",
        "| --- | --- |",
    ]
    for k, v in rows:
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def audit_actions_md(observed: dict[str, int] | None = None) -> str:
    """Markdown audit: blank vs not-removed for defaults (+ optional histogram counts)."""
    obs = {normalize_raw(k): int(v) for k, v in (observed or {}).items()}
    blank = [(k, v) for k, v in DEFAULT_ACTIONS.items() if v == "blank"]
    defer = [(k, v) for k, v in DEFAULT_ACTIONS.items() if v == "defer-to-script"]
    ignore_mapped = [(k, v) for k, v in DEFAULT_ACTIONS.items() if v == "ignore"]
    lines = [
        "## Blank (removed)",
        "",
        "| raw_label | count (if known) |",
        "| --- | ---: |",
    ]
    for k, _ in sorted(blank):
        c = obs.get(k)
        lines.append(f"| {k} | {c if c is not None else '—'} |")
    lines += [
        "",
        "## Not removed",
        "",
        "### defer-to-script",
        "",
        "| raw_label | count |",
        "| --- | ---: |",
    ]
    for k, _ in sorted(defer):
        c = obs.get(k)
        lines.append(f"| {k} | {c if c is not None else '—'} |")
    lines += [
        "",
        "### ignore (mapped)",
        "",
        "| raw_label | count | why |",
        "| --- | ---: | --- |",
        "| COMPANY_NAME | "
        f"{obs.get('COMPANY_NAME', '—')} | org/manufacturer in free text |",
        "",
        "### ignore (unmapped default)",
        "",
        "Any OpenMed label **not** listed in `DEFAULT_ACTIONS` → **ignore**.",
        "",
    ]
    if obs:
        unmapped = sorted(k for k in obs if k not in DEFAULT_ACTIONS)
        if unmapped:
            lines += ["| raw_label | count |", "| --- | ---: |"]
            for k in unmapped:
                lines.append(f"| {k} | {obs[k]} |")
        else:
            lines.append("_None in current histogram._")
    return "\n".join(lines)
