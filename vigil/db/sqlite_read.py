"""Sync SQLite reads for iteration listings when filesystem state is empty or path mismatches."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


def _db_file() -> Path:
    return Path.home() / ".vigil" / "vigil.db"


def find_project_id(conn: sqlite3.Connection, project_path: str) -> int | None:
    """Match projects.path with normalization variants (symlinks, ~)."""
    norm = os.path.normpath(os.path.expanduser(project_path))
    candidates: list[str] = [norm]
    if os.path.isdir(norm):
        try:
            candidates.append(os.path.realpath(norm))
        except OSError:
            pass
    seen: set[str] = set()
    cur = conn.cursor()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        cur.execute("SELECT id FROM projects WHERE path = ?", (p,))
        row = cur.fetchone()
        if row:
            return int(row[0])
    return None


def _row_to_summary(row: sqlite3.Row) -> dict:
    files_changed = row["files_changed"]
    if isinstance(files_changed, str):
        try:
            files_changed = json.loads(files_changed) if files_changed else []
        except json.JSONDecodeError:
            files_changed = []
    steps = row["steps"]
    if isinstance(steps, str):
        try:
            steps = json.loads(steps) if steps else []
        except json.JSONDecodeError:
            steps = []
    return {
        "iteration": row["iteration_num"],
        "task_type": row["task_type"] or "",
        "task_description": row["task_description"] or "",
        "status": row["status"] or "",
        "summary": row["summary"] or "",
        "benchmark_data": {},
        "timestamp": str(row["created_at"]) if row["created_at"] is not None else "",
        "files_changed": files_changed or [],
        "commit_hash": row["commit_hash"] or "",
        "duration_ms": int(row["duration_ms"] or 0),
        "llm_tokens": int(row["llm_tokens"] or 0),
        "llm_duration_s": float(row["llm_duration_s"] or 0),
        "step_count": len(steps) if isinstance(steps, list) else 0,
    }


def iteration_summaries_page(
    project_path: str,
    offset: int,
    limit: int,
    status_filter: str | None,
    sort_order: str = "desc",
) -> tuple[list[dict], int] | None:
    """Return (summaries, total) from SQLite, or None if DB missing / project not found."""
    dbp = _db_file()
    if not dbp.exists():
        return None

    conn = sqlite3.connect(str(dbp), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        pid = find_project_id(conn, project_path)
        if pid is None:
            return None

        cur = conn.cursor()
        where = "WHERE project_id = ?"
        params: list = [pid]
        if status_filter == "success":
            where += " AND status = 'success'"
        elif status_filter == "failed":
            where += " AND status != 'success'"

        cur.execute(f"SELECT COUNT(*) FROM iterations {where}", params)
        total = int(cur.fetchone()[0])

        order_sql = "ORDER BY created_at DESC, iteration_num DESC"
        if sort_order == "asc":
            order_sql = "ORDER BY created_at ASC, iteration_num ASC"

        cur.execute(
            f"SELECT * FROM iterations {where} {order_sql} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        rows = cur.fetchall()
        summaries = [_row_to_summary(r) for r in rows]
        return summaries, total
    finally:
        conn.close()


def stats_for_project(project_path: str) -> dict | None:
    dbp = _db_file()
    if not dbp.exists():
        return None

    conn = sqlite3.connect(str(dbp), timeout=5)
    try:
        pid = find_project_id(conn, project_path)
        if pid is None:
            return None

        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM iterations WHERE project_id = ?",
            (pid,),
        )
        total = int(cur.fetchone()[0])
        cur.execute(
            "SELECT COUNT(*) FROM iterations WHERE project_id = ? AND status = 'success'",
            (pid,),
        )
        successes = int(cur.fetchone()[0])
        failures = total - successes

        cur.execute(
            "SELECT COALESCE(SUM(llm_tokens), 0), COALESCE(SUM(duration_ms), 0) "
            "FROM iterations WHERE project_id = ?",
            (pid,),
        )
        row = cur.fetchone()
        llm_tokens_total = int(row[0] or 0)
        duration_ms_total = int(row[1] or 0)

        return {
            "total_iterations": total,
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / total * 100, 1) if total else 0.0,
            "coverage_trend": [],
            "llm_tokens_total": llm_tokens_total,
            "duration_ms_total": duration_ms_total,
        }
    finally:
        conn.close()


def iteration_detail(project_path: str, iteration_num: int) -> dict | None:
    dbp = _db_file()
    if not dbp.exists():
        return None

    conn = sqlite3.connect(str(dbp), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        pid = find_project_id(conn, project_path)
        if pid is None:
            return None

        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM iterations WHERE project_id = ? AND iteration_num = ?",
            (pid, iteration_num),
        )
        row = cur.fetchone()
        if not row:
            return None

        def jcol(name: str) -> list | dict | None:
            raw = row[name]
            if raw is None:
                return None
            if isinstance(raw, (list, dict)):
                return raw
            try:
                return json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return None

        return {
            "iteration": row["iteration_num"],
            "task_type": row["task_type"] or "",
            "task_description": row["task_description"] or "",
            "status": row["status"] or "",
            "summary": row["summary"] or "",
            "benchmark_data": jcol("benchmark_data") or {},
            "timestamp": str(row["created_at"]) if row["created_at"] is not None else "",
            "duration_ms": int(row["duration_ms"] or 0),
            "steps": jcol("steps") or [],
            "files_changed": jcol("files_changed") or [],
            "diff": row["diff"] or "",
            "commit_hash": row["commit_hash"] or "",
            "llm_response": row["llm_response"] or "",
            "llm_prompt_system": row["llm_prompt_system"] or "",
            "llm_prompt_user": row["llm_prompt_user"] or "",
            "llm_tokens": int(row["llm_tokens"] or 0),
            "llm_duration_s": float(row["llm_duration_s"] or 0),
            "changes_detail": jcol("changes_detail") or [],
            "test_output": row["test_output"] or "",
            "branch_name": row["branch_name"] or "",
            "provider_name": row["provider_name"] or "",
        }
    finally:
        conn.close()
