"""Localized display names for Embedded PHI entity labels.

Public API
----------
entity_label_display(label) -> str
    Localized short display name for an entity label.
"""

from anonymizer.utils.translate import _


def entity_label_display(label: str) -> str:
    """
    Localized short display name for an entity label.

    Args:
        label: PHI / NER class code (e.g. NAME, DATE).

    Returns:
        Translated short name, or the original label when unknown.
    """
    names = {
        "NAME": _("Name"),
        "FIRST_NAME": _("First name"),
        "LAST_NAME": _("Last name"),
        "LOCATION": _("Location"),
        "ID": _("ID"),
        "PHONE": _("Phone"),
        "DATE": _("Date"),
        "EMAIL": _("Email"),
    }
    return names.get(str(label).upper(), str(label))
