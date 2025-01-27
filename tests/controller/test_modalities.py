from src.anonymizer.utils.modalities import (
get_modalities
)

def test_get_modalities():
    """
    Tests if the get_modalities function returns the expected dictionary 
    structure and contains the expected keys.
    """
    data = get_modalities()

    # Assert the data is a dictionary
    assert isinstance(data, dict)

    # Assert the dictionary contains the expected keys
    expected_keys = [
        "CR", "DX", "IO", "MG", "CT", "MR", "US", "PT", "NM", "SC", "SR", "PR", "PDF", "OT", "DOC"
    ]
    assert set(data.keys()) == set(expected_keys)