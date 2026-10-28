"""Deterministic synthetic PHI from offline locale pools (HMAC-seeded).

Pools live under ner/pools/<locale>/ (first_names_male.txt,
first_names_female.txt, last_names.txt, streets.txt, cities.txt with
city|state|zip rows). FIRST_NAME replacements keep the source sex when
the original given name is in a gendered pool. Unknown labels yield
"REDACTED". Same project_id / anon_ptid / label / ordinal / source →
same value.

Public API
----------
generate_synthetic_phi(label: str, *, project_id: str='default', anon_ptid: str='ANON0000', locale: str='en_US', ordinal: int=0, source_fragment: str='') -> str
    Return a synthetic replacement string for a PHI label.
"""
import hashlib
import hmac
import re
from functools import lru_cache
from pathlib import Path

_POOLS = Path(__file__).resolve().parent / "pools"
_SECRET = b"embedded_phi_synth_v1"

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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_synthetic_phi(
    label: str,
    *,
    project_id: str = "default",
    anon_ptid: str = "ANON0000",
    locale: str = "en_US",
    ordinal: int = 0,
    source_fragment: str = "",
) -> str:
    """
    Return a synthetic replacement string for a PHI label.

    Values are deterministic for the same project_id, anon_ptid,
    label, ordinal, and source_fragment (shape hint). FIRST_NAME picks
    from the male or female pool when the source given name is known.

    Args:
        label: Product PHI label (FIRST_NAME, LAST_NAME, LOCATION,
            ID, PHONE, EMAIL, DATE, …).
        project_id: Project / site seed namespace.
        anon_ptid: Anonymized patient id seed.
        locale: Pool locale directory name (falls back to en_US).
        ordinal: Occurrence index among same-label entities in one text.
        source_fragment: Original span text used as a formatting shape hint
            and, for FIRST_NAME, sex inference.

    Returns:
        Synthetic replacement string.
    """
    male, female, first = _first_name_pools(locale)
    last = _load_lines(locale, "last_names.txt") or ("Example",)
    streets = _load_lines(locale, "streets.txt") or ("Main",)
    cities = _load_cities(locale) or (("Springfield", "IL", "62701"),)

    a, b, c, d = _seed_ints(
        project_id,
        anon_ptid,
        label,
        str(ordinal),
        source_fragment.casefold()[:32],
    )
    if label == "FIRST_NAME":
        pool = _first_name_pool_for_source(source_fragment, male=male, female=female, all_names=first)
        return pool[a % len(pool)]
    if label == "LAST_NAME":
        return last[b % len(last)]
    if label == "LOCATION":
        return _synth_location(streets, cities, a, b, c, d, source_fragment)
    if label == "ID":
        return f"SYN{a % 10_000_000:07d}"
    if label == "PHONE":
        return _synth_phone(a, b, c, source_fragment)
    if label == "EMAIL":
        return _synth_email(first, last, a, b, c, d)
    if label == "DATE":
        return _synth_date(a, b, c, source_fragment)
    return "REDACTED"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _load_lines(locale: str, name: str) -> tuple[str, ...]:
    """
    Load non-comment lines from a pool file (falls back to en_US).

    Args:
        locale: Pool locale directory name.
        name: File name under pools/<locale>/.

    Returns:
        Tuple of stripped non-comment lines (may be empty).
    """
    return _cached_load_lines(locale, name)


@lru_cache(maxsize=8)
def _cached_load_lines(locale: str, name: str) -> tuple[str, ...]:
    """
    Cached pool file read for locale / name.

    Args:
        locale: Pool locale directory name.
        name: File name under pools/<locale>/.

    Returns:
        Tuple of stripped non-comment lines (may be empty).
    """
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
def _first_name_pools(locale: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """
    Male, female, and combined first-name pools for locale.

    Args:
        locale: Pool locale directory name.

    Returns:
        (male, female, all) tuples; each falls back to ("Pat",) when empty.
    """
    male = _cached_load_lines(locale, "first_names_male.txt")
    female = _cached_load_lines(locale, "first_names_female.txt")
    if not male and not female:
        # Legacy single-file locales: treat as unsexed combined pool.
        combined = _cached_load_lines(locale, "first_names.txt") or ("Pat",)
        return (), (), combined
    male = male or ("Pat",)
    female = female or ("Pat",)
    return male, female, tuple(dict.fromkeys((*male, *female)))


def _first_name_pool_for_source(
    source_fragment: str,
    *,
    male: tuple[str, ...],
    female: tuple[str, ...],
    all_names: tuple[str, ...],
) -> tuple[str, ...]:
    """
    Choose the first-name pool matching the source given name's sex.

    Args:
        source_fragment: Original FIRST_NAME span.
        male: Male given-name pool.
        female: Female given-name pool.
        all_names: Combined pool when sex is unknown.

    Returns:
        Pool to sample from (never empty).
    """
    sex = _infer_first_name_sex(source_fragment, male=male, female=female)
    if sex == "male" and male:
        return male
    if sex == "female" and female:
        return female
    return all_names or ("Pat",)


def _infer_first_name_sex(
    source_fragment: str,
    *,
    male: tuple[str, ...],
    female: tuple[str, ...],
) -> str | None:
    """
    Infer male/female from membership in gendered pools (case-insensitive).

    Args:
        source_fragment: Original given-name span.
        male: Male given-name pool.
        female: Female given-name pool.

    Returns:
        "male", "female", or None when unknown or listed in both pools.
    """
    needle = str(source_fragment or "").strip().casefold()
    if not needle:
        return None
    male_keys = frozenset(name.casefold() for name in male)
    female_keys = frozenset(name.casefold() for name in female)
    in_male = needle in male_keys
    in_female = needle in female_keys
    if in_male and not in_female:
        return "male"
    if in_female and not in_male:
        return "female"
    return None


def _load_cities(locale: str) -> tuple[tuple[str, str, str], ...]:
    """
    Load city|state|zip rows for locale.

    Args:
        locale: Pool locale directory name.

    Returns:
        Tuple of (city, state, zip) triples.
    """
    return _cached_load_cities(locale)


@lru_cache(maxsize=8)
def _cached_load_cities(locale: str) -> tuple[tuple[str, str, str], ...]:
    """
    Cached city/state/zip triples for locale.

    Args:
        locale: Pool locale directory name.

    Returns:
        Tuple of (city, state, zip) triples.
    """
    rows: list[tuple[str, str, str]] = []
    for line in _cached_load_lines(locale, "cities.txt"):
        parts = line.split("|")
        if len(parts) >= 3:
            rows.append((parts[0], parts[1], parts[2]))
    return tuple(rows)


def _seed_ints(project_id: str, *parts: str, n: int = 4) -> list[int]:
    """
    HMAC-derive n unsigned 32-bit ints from project id and seed parts.

    Args:
        project_id: Outer HMAC key material.
        *parts: Additional message fragments joined with |.
        n: Number of 32-bit integers to return (default 4).

    Returns:
        List of n integers in [0, 2**32).
    """
    msg = "|".join(parts).encode("utf-8")
    key = hmac.new(_SECRET, project_id.encode("utf-8"), hashlib.sha256).digest()
    digest = hmac.new(key, msg, hashlib.sha256).digest()
    return [int.from_bytes(digest[i * 4 : (i + 1) * 4], "big") for i in range(n)]


def _phone_shape(source: str) -> str:
    """
    Classify phone formatting of source for shape-preserving synth.

    Args:
        source: Original phone span text.

    Returns:
        One of plus1, paren, dashed, digits.
    """
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
    """
    Classify address/zip formatting of source for shape-preserving synth.

    Args:
        source: Original location span text.

    Returns:
        One of zip4, zip_only, city_state_zip, full.
    """
    s = source.strip()
    if re.search(r"\d{5}-\d{4}\b", s):
        return "zip4"
    if re.fullmatch(r"\d{5}(-\d{4})?", s):
        return "zip_only"
    if re.search(r",\s*[A-Z]{2}\s+\d{5}", s) and not re.search(r"^\d+\s", s):
        return "city_state_zip"
    return "full"


def _synth_location(
    streets: tuple[str, ...],
    cities: tuple[tuple[str, str, str], ...],
    a: int,
    b: int,
    c: int,
    d: int,
    source_fragment: str,
) -> str:
    """
    Build a synthetic LOCATION matching zip / city-state / full address shape.

    Args:
        streets: Street-name pool.
        cities: (city, state, zip) pool.
        a: Seed for house number / zip+4.
        b: Seed index into streets.
        c: Seed index into street suffixes.
        d: Seed index into cities.
        source_fragment: Original location span (shape hint).

    Returns:
        Synthetic location string.
    """
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


def _synth_phone(a: int, b: int, c: int, source_fragment: str) -> str:
    """
    Build a synthetic PHONE matching the punctuation style of source_fragment.

    Args:
        a: Seed index into area-code pool.
        b: Seed for exchange.
        c: Seed for line number.
        source_fragment: Original phone span (shape hint).

    Returns:
        Synthetic phone string.
    """
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


def _synth_email(
    first: tuple[str, ...],
    last: tuple[str, ...],
    a: int,
    b: int,
    c: int,
    d: int,
) -> str:
    """
    Build a synthetic EMAIL from name pools and a fixed example domain.

    Args:
        first: Given-name pool.
        last: Family-name pool.
        a: Seed index into first.
        b: Seed index into last.
        c: Seed index into email domains.
        d: Numeric suffix seed.

    Returns:
        Synthetic email address.
    """
    given = first[a % len(first)].lower()
    family = last[b % len(last)].lower()
    dom = _EMAIL_DOMAINS[c % len(_EMAIL_DOMAINS)]
    return f"{given}.{family}{d % 100}@{dom}"


def _synth_date(a: int, b: int, c: int, source_fragment: str) -> str:
    """
    Build a synthetic DATE as YYYYMMDD or MM/DD/YYYY to match source shape.

    Args:
        a: Seed for year.
        b: Seed for month.
        c: Seed for day.
        source_fragment: Original date span (shape hint).

    Returns:
        Synthetic date string.
    """
    year = 1950 + (a % 60)
    month = 1 + (b % 12)
    day = 1 + (c % 28)
    if re.fullmatch(r"\d{8}", source_fragment.strip()):
        return f"{year:04d}{month:02d}{day:02d}"
    return f"{month:02d}/{day:02d}/{year:04d}"
