"""PT default whitelist shares the CT list."""

from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import load_default_whitelist


def test_pt_default_whitelist_aliases_ct() -> None:
    ct = load_default_whitelist("CT")
    pt = load_default_whitelist("PT")
    assert pt == ct
    assert len(pt) > 0
