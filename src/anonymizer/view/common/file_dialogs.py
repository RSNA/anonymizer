"""File open dialog helpers shared by settings dialogs."""

import sys

from anonymizer.utils.translate import _


def open_filetypes(*typed: tuple[str, str]) -> list[tuple[str, str]]:
    """
    Build askopenfilename filetypes lists.

    On macOS, Tk's native panel often greys out matching files when a custom
    extension filter is selected first. Put All Files first on darwin so the
    dialog opens usable; keep typed filters available in the menu.

    Args:
        typed: (label, pattern) pairs such as ("Script Files", "*.script").

    Returns:
        filetypes list for filedialog.askopenfilename.
    """
    all_files = (_("All Files"), "*.*")
    typed_list = list(typed)
    if sys.platform == "darwin":
        return [all_files, *typed_list]
    return [*typed_list, all_files]
