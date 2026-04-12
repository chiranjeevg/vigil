"""Shared types and abstract base for all Vigil work sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal, TypedDict

# The set of work categories Vigil understands.  The Prioritizer uses this to
# assign a baseline score: bug_fix and security are highest, improvement lowest.
WorkType = Literal[
    "bug_fix",
    "feature",
    "security",
    "test",
    "improvement",
    "custom",
]


class WorkItem(TypedDict):
    """Canonical representation of a unit of work, regardless of source.

    All fields are plain scalars or lists of strings so the dict is trivially
    serialisable to JSON for caching and API responses.
    """

    # Stable identifier; format: "<source>:<external-id>", e.g. "goal:auth-service"
    id: str
    # Which source produced this item
    source: str
    work_type: WorkType
    # Short human-readable title shown in logs and the UI
    title: str
    # Full description forwarded to the LLM as task context
    description: str
    # 1 = most urgent, 5 = lowest (mirrors GitHub P1–P5 label convention)
    priority: int
    # Paths relative to the project root that are likely to need editing
    context_files: list[str]
    # Read-only reference documents (PRDs, specs) for the LLM to use as requirements
    context_docs: list[str]
    # Extra instructions injected verbatim into the task prompt
    instructions: str
    # Source-specific extras (issue URL, PR link, label list, etc.)
    metadata: dict


class WorkSource(ABC):
    """Abstract base for anything that can produce ``WorkItem`` dicts."""

    @abstractmethod
    def poll(self) -> list[WorkItem]:
        """Return the current list of actionable work items.

        Implementations must be safe to call frequently (every iteration) and
        should use caching where external I/O is involved.
        """

    @abstractmethod
    def name(self) -> str:
        """Human-readable source name for logging and status endpoints."""

    @property
    def is_enabled(self) -> bool:
        """False disables the source entirely without removing its configuration."""
        return True
