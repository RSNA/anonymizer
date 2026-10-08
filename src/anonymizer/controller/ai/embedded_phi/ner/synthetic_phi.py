"""Deterministic synthetic PHI factory (HMAC-seeded offline pools)."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_POOLS = Path(__file__).resolve().parent / "pools"


@lru_cache(maxsize=8)
def _load_lines(locale: str, name: str) -> tuple[str, ...]:
    path = _POOLS / locale / name
    if not path.is_file():
        path = _POOLS / "en_US" / name
    if not path.is_file():
        return ()
    return tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    )


@lru_cache(maxsize=8)
def _load_cities(locale: str) -> tuple[tuple[str, str, str], ...]:
    rows: list[tuple[str, str, str]] = []
    for line in _load_lines(locale, "cities.txt"):
        parts = line.split("|")
        if len(parts) >= 3:
            rows.append((parts[0], parts[1], parts[2]))
    return tuple(rows)


_STREET_SFX = ("Street", "Avenue", "Drive", "Road", "Lane", "Boulevard", "Court", "Way")
_EMAIL_DOMAINS = (
    "example.org",
    "example.com",
    "mail.test",
    "patients.example",
    "clinic.example",
    "health.example",
    "records.example",
    "care.example",
    "demo.example",
    "sample.org",
)
_AREA_CODES = (
    201, 202, 203, 205, 206, 207, 208, 209, 210, 212, 213, 214, 215, 216, 217, 218,
    219, 224, 225, 228, 229, 231, 234, 239, 240, 248, 251, 252, 253, 254, 256, 260,
    262, 267, 269, 270, 272, 276, 281, 301, 302, 303, 304, 305, 307, 308, 309, 310,
    312, 313, 314, 315, 316, 317, 318, 319, 320, 321, 323, 325, 330, 331, 334, 336,
    337, 339, 346, 347, 351, 352, 360, 361, 364, 380, 385, 386, 401, 402, 404, 405,
)


def _phone_shape(source: str) -> str:
    s = source.strip()
    if s.startswith("+1"):
        return "plus1"
    if re.fullmatch(r"\(\d{3}\)\s*\d{3}-\d{4}", s):
        return "paren"
    if re.fullmatch(r"\d{3}-\d{3}-\d{4}", s):
        return "dashed"
    if re.fullmatch(r"\d{10}", s):
        return "digits"
    return "paren"


def _location_shape(source: str) -> str:
    s = source.strip()
    if re.search(r"\d{5}-\d{4}\b", s):
        return "zip4"
    if re.fullmatch(r"\d{5}(-\d{4})?", s):
        return "zip_only"
    if re.search(r",\s*[A-Z]{2}\s+\d{5}", s) and not re.search(r"^\d+\s", s):
        return "city_state_zip"
    return "full"


@dataclass
class SyntheticPhiFactory:
    """
    Offline synthetic PHI keyed by project + anonymized patient id.

    Same ``anon_ptid`` + label + ordinal → same replacement across series.
    Cross-patient NAME collisions are accepted (industry-normal).
    """

    project_id: str = "default"
    anon_ptid: str = "ANON0000"
    locale: str = "en_US"
    date_offset_days: int = 0
    _secret: bytes = field(default=b"embedded_phi_synth_v1", repr=False)

    def _digest(self, *parts: str) -> bytes:
        msg = "|".join(parts).encode("utf-8")
        key = hmac.new(self._secret, self.project_id.encode("utf-8"), hashlib.sha256).digest()
        return hmac.new(key, msg, hashlib.sha256).digest()

    def _ints(self, *parts: str, n: int = 4) -> list[int]:
        d = self._digest(*parts)
        return [int.from_bytes(d[i * 4 : (i + 1) * 4], "big") for i in range(n)]

    def generate(
        self,
        label: str,
        *,
        ordinal: int = 0,
        source_fragment: str = "",
    ) -> str:
        first = _load_lines(self.locale, "first_names.txt") or ("Pat",)
        last = _load_lines(self.locale, "last_names.txt") or ("Example",)
        streets = _load_lines(self.locale, "streets.txt") or ("Main",)
        cities = _load_cities(self.locale) or (("Springfield", "IL", "62701"),)

        base = (self.anon_ptid, label, str(ordinal), source_fragment.casefold()[:32])
        a, b, c, d = self._ints(*base, n=4)
        if label == "NAME":
            f = first[a % len(first)]
            ln = last[b % len(last)]
            if "^" in source_fragment:
                return f"{ln}^{f}"
            if "," in source_fragment:
                return f"{ln}, {f}"
            return f"{f} {ln}"
        if label == "LOCATION":
            num = 100 + (a % 8900)
            street = streets[b % len(streets)]
            sfx = _STREET_SFX[c % len(_STREET_SFX)]
            city, state, z = cities[d % len(cities)]
            shape = _location_shape(source_fragment)
            if shape == "zip_only":
                return z
            if shape == "zip4":
                return f"{z}-{1000 + (a % 9000):04d}"
            if shape == "city_state_zip":
                return f"{city}, {state} {z}"
            return f"{num} {street} {sfx}, {city}, {state} {z}"
        if label == "ID":
            return f"SYN{a % 10_000_000:07d}"
        if label == "PHONE":
            area = _AREA_CODES[a % len(_AREA_CODES)]
            exch = 200 + (b % 800)
            line = c % 10000
            shape = _phone_shape(source_fragment)
            if shape == "plus1":
                return f"+1{area}{exch:03d}{line:04d}"
            if shape == "dashed":
                return f"{area}-{exch:03d}-{line:04d}"
            if shape == "digits":
                return f"{area}{exch:03d}{line:04d}"
            return f"({area}) {exch:03d}-{line:04d}"
        if label == "EMAIL":
            f = first[a % len(first)].lower()
            ln = last[b % len(last)].lower()
            dom = _EMAIL_DOMAINS[c % len(_EMAIL_DOMAINS)]
            return f"{f}.{ln}{d % 100}@{dom}"
        if label == "DATE":
            year = 1950 + (a % 60)
            month = 1 + (b % 12)
            day = 1 + (c % 28)
            if self.date_offset_days:
                # Keep hash-derived date; offset reserved for patient policy wiring.
                pass
            if re.fullmatch(r"\d{8}", source_fragment.strip()):
                return f"{year:04d}{month:02d}{day:02d}"
            return f"{month:02d}/{day:02d}/{year:04d}"
        return "REDACTED"
