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
    prepared = create_project(**kwargs)
    if prepared.get("ok") is False:
        return prepared
    assert prepared.get("status") == "confirmation_required", prepared
    assert prepared.get("created") is False, prepared
    return create_project(
        project_name=kwargs["project_name"],
        confirm=True,
        revision=prepared["revision"],
    )
