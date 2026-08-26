"""Serialized background delivery for structural-knowledge matching."""

from __future__ import annotations

from crystal_viewer.ui.comparison_requests import (
    ComparisonExecutor,
    ComparisonRequestManager,
    QtComparisonExecutor,
)


KnowledgeExecutor = ComparisonExecutor


class KnowledgeRequestManager(ComparisonRequestManager):
    """Publish only the latest document's knowledge proposal."""


class QtKnowledgeExecutor(QtComparisonExecutor):
    """Run knowledge matching off the GUI thread with bounded shutdown."""


__all__ = [
    "KnowledgeExecutor",
    "KnowledgeRequestManager",
    "QtKnowledgeExecutor",
]
