"""SQLAlchemy models for Vigil."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    """A project being monitored by Vigil."""
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(50), default="unknown")

    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    total_iterations: Mapped[int] = mapped_column(Integer, default=0)
    successful_iterations: Mapped[int] = mapped_column(Integer, default=0)
    last_iteration_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    iterations: Mapped[list["Iteration"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    benchmarks: Mapped[list["Benchmark"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_projects_active_updated", "is_active", "updated_at"),
    )


class Iteration(Base):
    """A single improvement iteration."""
    __tablename__ = "iterations"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    iteration_num: Mapped[int] = mapped_column(Integer)

    task_type: Mapped[str] = mapped_column(String(100))
    task_description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")

    files_changed: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    diff: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    commit_hash: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    llm_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_prompt_system: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_prompt_user: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_duration_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    steps: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    changes_detail: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    test_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    branch_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    benchmark_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    project: Mapped["Project"] = relationship(back_populates="iterations")

    __table_args__ = (
        Index("ix_iterations_project_num", "project_id", "iteration_num", unique=True),
        Index("ix_iterations_project_created", "project_id", "created_at"),
    )


class Benchmark(Base):
    """Benchmark results over time."""
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    iteration_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("iterations.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(255))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(50), default="")

    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    delta_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    project: Mapped["Project"] = relationship(back_populates="benchmarks")

    __table_args__ = (
        Index("ix_benchmarks_project_name_created", "project_id", "name", "created_at"),
    )


class Task(Base):
    """Task queue for a project."""
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)

    task_type: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    target_files: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    priority: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    project: Mapped["Project"] = relationship(back_populates="tasks")

    __table_args__ = (
        Index("ix_tasks_project_status_priority", "project_id", "status", "priority"),
    )
