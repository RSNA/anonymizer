"""Shared two-phase ``create_project`` helper for MCP tests."""

from collections.abc import Callable
from typing import Any


def confirm_create(create_project: Callable[..., dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """
    Prepare then confirm one MCP project creation.

    Args:
        create_project: Handler or ops ``create_project`` callable.
        **kwargs: Create-project arguments; ``project_name`` is required.

    Returns:
        The confirmation-call result/payload.
    """
    prepare_kwargs = dict(kwargs)
    if prepare_kwargs.get("confidentiality_options") is None and not prepare_kwargs.get("accept_basic_profile"):
        prepare_kwargs["accept_basic_profile"] = True
    prepared = create_project(**prepare_kwargs)
    if prepared.get("ok") is False:
        return prepared
    assert prepared.get("status") == "confirmation_required", prepared
    assert prepared.get("created") is False, prepared
    return create_project(
        project_name=kwargs["project_name"],
        confirm=True,
        revision=prepared["revision"],
    )
