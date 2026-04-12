"""Work sources — external feeds that generate actionable tasks for Vigil.

Each source implements the ``WorkSource`` interface and returns a list of
``WorkItem`` dicts.  The ``TaskPlanner`` aggregates results from all enabled
sources and hands them to the ``Prioritizer`` before selecting the next task.
"""

from vigil.core.work_sources.base import WorkItem, WorkSource
from vigil.core.work_sources.github_issues import GitHubIssueSource
from vigil.core.work_sources.goal_source import GoalSource
from vigil.core.work_sources.prd_scanner import PRDScanner

__all__ = ["WorkItem", "WorkSource", "GoalSource", "GitHubIssueSource", "PRDScanner"]
