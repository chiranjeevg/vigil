"""Repository pattern for database operations."""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.db.models import Benchmark, Iteration, Project, Task

log = logging.getLogger(__name__)


class ProjectRepository:
    """Repository for Project operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, project_id: int) -> Optional[Project]:
        result = await self.session.execute(
            select(Project).where(Project.id == project_id)
        )
        return result.scalar_one_or_none()

    async def get_by_path(self, path: str) -> Optional[Project]:
        result = await self.session.execute(
            select(Project).where(Project.path == path)
        )
        return result.scalar_one_or_none()

    async def get_all_active(self) -> list[Project]:
        result = await self.session.execute(
            select(Project)
            .where(Project.is_active.is_(True))
            .order_by(desc(Project.updated_at))
        )
        return list(result.scalars().all())

    async def create(
        self,
        path: str,
        name: str,
        language: str = "unknown",
        config_json: Optional[str] = None,
    ) -> Project:
        project = Project(
            path=path,
            name=name,
            language=language,
            config_json=config_json,
        )
        self.session.add(project)
        await self.session.flush()
        return project

    async def upsert(
        self,
        path: str,
        name: str,
        language: str = "unknown",
        config_json: Optional[str] = None,
    ) -> Project:
        existing = await self.get_by_path(path)
        if existing:
            existing.name = name
            existing.language = language
            if config_json:
                existing.config_json = config_json
            existing.is_active = True
            await self.session.flush()
            return existing
        return await self.create(path, name, language, config_json)

    async def update_stats(
        self,
        project_id: int,
        total_iterations: Optional[int] = None,
        successful_iterations: Optional[int] = None,
    ) -> None:
        project = await self.get_by_id(project_id)
        if project:
            if total_iterations is not None:
                project.total_iterations = total_iterations
            if successful_iterations is not None:
                project.successful_iterations = successful_iterations
            project.last_iteration_at = datetime.now(timezone.utc)

    async def deactivate_by_path(self, path: str) -> bool:
        """Hide project from Vigil UI (soft delete). Does not delete files on disk."""
        project = await self.get_by_path(path)
        if not project:
            return False
        project.is_active = False
        await self.session.flush()
        return True


class IterationRepository:
    """Repository for Iteration operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, iteration_id: int) -> Optional[Iteration]:
        result = await self.session.execute(
            select(Iteration).where(Iteration.id == iteration_id)
        )
        return result.scalar_one_or_none()

    async def get_by_project_and_num(
        self, project_id: int, iteration_num: int
    ) -> Optional[Iteration]:
        result = await self.session.execute(
            select(Iteration).where(
                Iteration.project_id == project_id,
                Iteration.iteration_num == iteration_num,
            )
        )
        return result.scalar_one_or_none()

    async def get_recent(
        self, project_id: int, limit: int = 20
    ) -> list[Iteration]:
        result = await self.session.execute(
            select(Iteration)
            .where(Iteration.project_id == project_id)
            .order_by(desc(Iteration.iteration_num))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_all(self, project_id: int) -> list[Iteration]:
        result = await self.session.execute(
            select(Iteration)
            .where(Iteration.project_id == project_id)
            .order_by(Iteration.iteration_num)
        )
        return list(result.scalars().all())

    async def create(
        self,
        project_id: int,
        iteration_num: int,
        task_type: str,
        task_description: str,
        status: str,
        summary: str = "",
        files_changed: Optional[list] = None,
        diff: Optional[str] = None,
        commit_hash: Optional[str] = None,
        llm_response: Optional[str] = None,
        benchmark_data: Optional[dict] = None,
        duration_seconds: Optional[float] = None,
    ) -> Iteration:
        iteration = Iteration(
            project_id=project_id,
            iteration_num=iteration_num,
            task_type=task_type,
            task_description=task_description,
            status=status,
            summary=summary,
            files_changed=files_changed,
            diff=diff,
            commit_hash=commit_hash,
            llm_response=llm_response,
            benchmark_data=benchmark_data,
            duration_seconds=duration_seconds,
        )
        self.session.add(iteration)
        await self.session.flush()
        return iteration

    async def get_stats(self, project_id: int) -> dict:
        total = await self.session.execute(
            select(func.count(Iteration.id)).where(
                Iteration.project_id == project_id
            )
        )
        successes = await self.session.execute(
            select(func.count(Iteration.id)).where(
                Iteration.project_id == project_id,
                Iteration.status == "success",
            )
        )

        total_count = total.scalar() or 0
        success_count = successes.scalar() or 0

        return {
            "total_iterations": total_count,
            "successes": success_count,
            "failures": total_count - success_count,
            "success_rate": (success_count / total_count * 100) if total_count > 0 else 0,
        }


class BenchmarkRepository:
    """Repository for Benchmark operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_recent(
        self, project_id: int, name: Optional[str] = None, limit: int = 50
    ) -> list[Benchmark]:
        query = select(Benchmark).where(Benchmark.project_id == project_id)
        if name:
            query = query.where(Benchmark.name == name)
        query = query.order_by(desc(Benchmark.created_at)).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        project_id: int,
        name: str,
        value: float,
        unit: str = "",
        iteration_id: Optional[int] = None,
        is_baseline: bool = False,
        delta_pct: Optional[float] = None,
    ) -> Benchmark:
        benchmark = Benchmark(
            project_id=project_id,
            name=name,
            value=value,
            unit=unit,
            iteration_id=iteration_id,
            is_baseline=is_baseline,
            delta_pct=delta_pct,
        )
        self.session.add(benchmark)
        await self.session.flush()
        return benchmark

    async def get_baseline(self, project_id: int, name: str) -> Optional[Benchmark]:
        result = await self.session.execute(
            select(Benchmark).where(
                Benchmark.project_id == project_id,
                Benchmark.name == name,
                Benchmark.is_baseline.is_(True),
            )
        )
        return result.scalar_one_or_none()


class TaskRepository:
    """Repository for Task operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_pending(self, project_id: int) -> list[Task]:
        result = await self.session.execute(
            select(Task)
            .where(Task.project_id == project_id, Task.status == "pending")
            .order_by(desc(Task.priority), Task.created_at)
        )
        return list(result.scalars().all())

    async def create(
        self,
        project_id: int,
        task_type: str,
        description: str,
        target_files: Optional[list] = None,
        instructions: Optional[str] = None,
        priority: int = 0,
    ) -> Task:
        task = Task(
            project_id=project_id,
            task_type=task_type,
            description=description,
            target_files=target_files,
            instructions=instructions,
            priority=priority,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def update_status(
        self, task_id: int, status: str, increment_attempts: bool = False
    ) -> None:
        result = await self.session.execute(
            select(Task).where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()
        if task:
            task.status = status
            if increment_attempts:
                task.attempts += 1
                task.last_attempt_at = datetime.now(timezone.utc)
