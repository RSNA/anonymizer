"""Date-option mutual exclusivity for de-identification options."""

from anonymizer.controller.script.option_explanations import apply_date_option_exclusivity
from anonymizer.utils.dicom import DeidMethodCode


def test_enabling_full_dates_clears_modified() -> None:
    selected = frozenset(
        {
            DeidMethodCode.BASIC,
            DeidMethodCode.MODIFIED_DATES,
            DeidMethodCode.SAFE_PRIVATE,
        }
    )
    result = apply_date_option_exclusivity(selected, enabled=DeidMethodCode.FULL_DATES)
    assert DeidMethodCode.FULL_DATES in result
    assert DeidMethodCode.MODIFIED_DATES not in result
    assert DeidMethodCode.SAFE_PRIVATE in result


def test_enabling_modified_dates_clears_full() -> None:
    selected = frozenset({DeidMethodCode.BASIC, DeidMethodCode.FULL_DATES})
    result = apply_date_option_exclusivity(selected, enabled=DeidMethodCode.MODIFIED_DATES)
    assert DeidMethodCode.MODIFIED_DATES in result
    assert DeidMethodCode.FULL_DATES not in result
