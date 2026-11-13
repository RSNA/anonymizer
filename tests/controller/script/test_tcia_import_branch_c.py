"""Branch C NormalizedDate: dateinterval→rebasedate, @if(isblank), LTET stamp."""

from datetime import datetime, timedelta
from pathlib import Path

from pydicom.dataset import Dataset

from anonymizer.controller.dates import rebase_days, stamp_rebase_registration
from anonymizer.controller.script.ctp_normalize import normalize_ctp_document
from anonymizer.controller.script.document import load_script_rules, validate_document
from anonymizer.controller.script.operands import (
    parse_if_isblank_operation,
    validate_operation,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tcia"
_NORMALIZED_MINI = _FIXTURES / "normalized_date_mini.script"


def test_normalize_dateinterval_normdate_to_rebasedate() -> None:
    """@dateinterval(…,@NORMDATE) becomes @rebasedate(this,NORMDATE)."""
    document = load_script_rules(_NORMALIZED_MINI)
    warnings = normalize_ctp_document(document)
    assert document.get_rule("00080020").operation == "@rebasedate(this,19750101)"
    assert any("rebasedate" in w for w in warnings)
    assert document.get_rule("00181002").operation == "@uid"
    assert validate_document(document) == []


def test_normalize_if_isblank_with_rebasedate_arm() -> None:
    """@if arms rewrite nested dateinterval to rebasedate and validate."""
    document = load_script_rules(_NORMALIZED_MINI)
    normalize_ctp_document(document)
    series = document.get_rule("00080021").operation
    arms = parse_if_isblank_operation(series)
    assert arms is not None
    assert arms[0] == "@remove()"
    assert arms[1] == "@rebasedate(this,19750101)"
    assert validate_operation(series) is None


def test_rebase_math_and_ltet_stamp() -> None:
    """Rebase day math and Event Type from LTET."""
    # origin 19750101, basedate 20150115 → negative days
    days = rebase_days("20150115", "19750101")
    assert days == (datetime(1975, 1, 1) - datetime(2015, 1, 15)).days
    study = (datetime(2015, 1, 15) + timedelta(days=30)).strftime("%Y%m%d")
    ds = Dataset()
    stamp_rebase_registration(ds, study, "20150115", event_type="DIAGNOSIS")
    assert ds.LongitudinalTemporalEventType == "DIAGNOSIS"
    assert float(ds.LongitudinalTemporalOffsetFromEvent) == 30.0


def test_normalized_date_mini_validates() -> None:
    """Merge gate: NormalizedDate excerpt validates after normalize."""
    document = load_script_rules(_NORMALIZED_MINI)
    normalize_ctp_document(document)
    assert document.get_rule("00120053").operation == "@always()DIAGNOSIS"
    assert validate_document(document) == []
