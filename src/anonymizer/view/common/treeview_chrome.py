"""Shared Treeview zebra chrome (Metadata tree, Anonymizer Script editor).

Even/odd row backgrounds use the theme Treeview base plus CTkFrame top_fg
(same tones as Dataset / Metadata). Call configure_zebra_row_tags once,
then apply_zebra_tags after each list rebuild.

Never constructs a CTk root — walk masters for _apply_appearance_mode
(AppToplevel dialogs sit under the Dashboard CTk host).
"""

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk

from customtkinter import ThemeManager


def find_appearance_host(widget: tk.Misc) -> tk.Misc | None:
    """
    Walk masters to the CTk widget that applies appearance-mode theme colors.

    Args:
        widget: Starting widget (dialog, frame, or tree).

    Returns:
        Host with _apply_appearance_mode, or None.
    """
    current: tk.Misc | None = widget
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if callable(getattr(current, "_apply_appearance_mode", None)):
            return current
        nxt = getattr(current, "master", None)
        if nxt is None or nxt is current:
            break
        current = nxt
    return None


def _appearance_apply(host: tk.Misc | None) -> Callable[[object], object]:
    """Resolve appearance-mode apply, or pick the light tuple entry."""
    if host is not None:
        apply = getattr(host, "_apply_appearance_mode", None)
        if callable(apply):
            return apply

    def _pick(pair: object) -> object:
        return pair[0] if isinstance(pair, (list, tuple)) else pair

    return _pick


def treeview_theme_colors(host: tk.Misc) -> tuple[str, str, str, str]:
    """
    Resolve Treeview bg / fg / selected colors (Dataset / app startup path).

    Args:
        host: Widget near the dialog; appearance host is found via masters.

    Returns:
        (bg, fg, select_bg, select_fg) color strings.
    """
    apply = _appearance_apply(find_appearance_host(host))
    theme = ThemeManager.theme
    bg = apply(theme["CTkFrame"]["fg_color"])
    fg = apply(theme["CTkLabel"]["text_color"])
    select_bg = apply(theme["CTkButton"]["fg_color"])
    select_fg = apply(theme["CTkButton"]["text_color"])
    tv = theme.get("Treeview") or {}
    if "bg_color" in tv:
        bg = apply(tv["bg_color"])
    if "text_color" in tv:
        fg = apply(tv["text_color"])
    if "selected_bg_color" in tv:
        select_bg = apply(tv["selected_bg_color"])
    if "selected_color" in tv:
        select_fg = apply(tv["selected_color"])
    return str(bg), str(fg), str(select_bg), str(select_fg)


def stripe_pair(host: tk.Misc, base_bg: str) -> tuple[str, str]:
    """
    Even/odd row backgrounds from theme grays (never pure white).

    Args:
        host: Widget near the dialog; appearance host is found via masters.
        base_bg: Even-row background (usually Treeview bg).

    Returns:
        (even_bg, odd_bg).
    """
    apply = _appearance_apply(find_appearance_host(host))
    # Treeview bg (gray90 / gray13) + CTkFrame top_fg (gray85 / gray16).
    frame = ThemeManager.theme.get("CTkFrame") or {}
    alt = frame.get("top_fg_color", ["gray85", "gray16"])
    odd = str(apply(alt))
    even = base_bg
    if odd.casefold() == even.casefold():
        odd = str(apply(["gray86", "gray16"]))
    return even, odd


def configure_zebra_row_tags(tree: ttk.Treeview, host: tk.Misc) -> None:
    """
    Register row_even / row_odd tags on tree (Metadata chrome).

    Args:
        tree: Target Treeview.
        host: Widget near the dialog (AppToplevel or CTkToplevel).
    """
    bg, fg, _sel_bg, _sel_fg = treeview_theme_colors(host)
    even, odd = stripe_pair(host, bg)
    tree.tag_configure("row_even", background=even, foreground=fg)
    tree.tag_configure("row_odd", background=odd, foreground=fg)


def apply_zebra_tags(tree: ttk.Treeview, iids: Sequence[str]) -> None:
    """
    Apply alternating row_even / row_odd tags in display order.

    Args:
        tree: Target Treeview.
        iids: Row ids in visible order (flat lists: get_children()).
    """
    for i, iid in enumerate(iids):
        tree.item(iid, tags=("row_odd" if i % 2 else "row_even",))
