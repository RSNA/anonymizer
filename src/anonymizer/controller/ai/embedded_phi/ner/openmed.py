"""OpenMed ClinicalE5-Small token classifier (product NER head)."""

from __future__ import annotations

from anonymizer.controller.ai.embedded_phi.ner.cache import (
    load_token_classification_pipeline,
    resolve_model_id,
)
from anonymizer.controller.ai.embedded_phi.ner.phi_entity import Span

_TO_SCORED: dict[str, str] = {
    "PERSON": "NAME",
    "PER": "NAME",
    "PATIENT": "NAME",
    "DOCTOR": "NAME",
    "NAME": "NAME",
    "PATIENTNAME": "NAME",
    "FIRSTNAME": "NAME",
    "FIRST_NAME": "NAME",
    "LASTNAME": "NAME",
    "LAST_NAME": "NAME",
    "MIDDLENAME": "NAME",
    "MIDDLE_NAME": "NAME",
    "USERNAME": "NAME",
    "USER_NAME": "NAME",
    "COMPANY_NAME": "NAME",
    "DATE": "DATE",
    "DATE_TIME": "DATE",
    # Bare TIME is left unlabeled (not required for Safe Harbor anonymization).
    "AGE": "DATE",
    "DATE_OF_BIRTH": "DATE",
    "DATEOFBIRTH": "DATE",
    "DOB": "DATE",
    "LOCATION": "LOCATION",
    "LOC": "LOCATION",
    "GPE": "LOCATION",
    "FAC": "LOCATION",
    "ADDRESS": "LOCATION",
    "HOSPITAL": "LOCATION",
    "CITY": "LOCATION",
    "STATE": "LOCATION",
    "COUNTRY": "LOCATION",
    "COUNTY": "LOCATION",
    "ZIP": "LOCATION",
    "ZIPCODE": "LOCATION",
    "STREET": "LOCATION",
    "STREET_ADDRESS": "LOCATION",
    "CITY_STATE": "LOCATION",
    "POSTCODE": "LOCATION",
    "ID": "ID",
    "IDNUM": "ID",
    "MEDICALRECORD": "ID",
    "MEDICAL_RECORD": "ID",
    "MEDICAL_RECORD_NUMBER": "ID",
    "MRN": "ID",
    "SSN": "ID",
    "US_SSN": "ID",
    "SOCIAL_SECURITY_NUMBER": "ID",
    "SOCIALSECURITYNUMBER": "ID",
    "NATIONAL_ID": "ID",
    "PATIENT_ID": "ID",
    "PATIENT_IDENTIFIER": "ID",
    "ACCOUNT": "ID",
    "ACCOUNT_NUMBER": "ID",
    "UNIQUE_ID": "ID",
    "CUSTOMER_ID": "ID",
    "EMPLOYEE_ID": "ID",
    "TAX_ID": "ID",
    "BIOID": "ID",
    "BIOMETRIC_IDENTIFIER": "ID",
    "HEALTHPLAN": "ID",
    "HEALTH_PLAN_BENEFICIARY_NUMBER": "ID",
    "DEVICE": "ID",
    "DEVICE_IDENTIFIER": "ID",
    "CREDIT_CARD": "ID",
    "CREDITCARDNUMBER": "ID",
    "CREDIT_DEBIT_CARD": "ID",
    "CERTIFICATE_LICENSE_NUMBER": "ID",
    # PHONE is owned by PatternsEngine (ClinicalE5 phone recall is weak).
    "EMAIL": "EMAIL",
    "EMAIL_ADDRESS": "EMAIL",
    "EMAILADDRESS": "EMAIL",
}


def to_scored_label(raw: str) -> str | None:
    key = raw.strip().upper().replace(" ", "_").replace("-", "_")
    if len(key) > 2 and key[1] in {"_", "-"} and key[0] in {"B", "I", "E", "S"}:
        key = key[2:]
    if key in {"TIME", "PHONE", "PHONE_NUMBER", "TELEPHONENUMBER", "FAX", "FAX_NUMBER"}:
        return None
    return _TO_SCORED.get(key)


class OpenMedEngine:
    name = "openmed_pii"

    def __init__(self) -> None:
        self._pipe = None
        self._error: str | None = None
        self._model_id: str | None = None

    def is_available(self) -> bool:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            self._error = "transformers/torch not installed"
            return False
        return True

    def _ensure(self, locale: str) -> None:
        if self._pipe is not None:
            return
        self._model_id = resolve_model_id(locale)
        try:
            self._pipe = load_token_classification_pipeline(self._model_id)
        except Exception as exc:  # noqa: BLE001
            self._error = f"Failed to load {self._model_id}: {exc}"
            self._pipe = None

    def analyze(self, text: str, *, locale: str = "en_US") -> list[Span]:
        if not self.is_available():
            return []
        self._ensure(locale)
        if self._pipe is None:
            return []
        spans: list[Span] = []
        for ent in self._pipe(text):
            raw = ent.get("entity_group") or ent.get("entity") or ""
            scored = to_scored_label(str(raw))
            if scored is None:
                continue
            spans.append(
                Span(
                    label=scored,
                    start=int(ent["start"]),
                    end=int(ent["end"]),
                    score=float(ent.get("score", 0.5)),
                    raw_label=str(raw),
                )
            )
        return spans
