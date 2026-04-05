from vigil.config import VigilConfig


def get_task_prompt(task: dict, context: dict, config: VigilConfig) -> str:
    sections: list[str] = []

    sections.append(
        f"## Task: {task['type']}\n"
        f"**Description**: {task['description']}\n\n"
        f"Analyze the codebase below, identify concrete improvements for this task, "
        f"and produce well-documented changes with clear reasoning."
    )

    if task.get("instructions"):
        sections.append(f"## Task-Specific Instructions\n{task['instructions']}")

    task_instructions = config.tasks.instructions.get(task["type"])
    if task_instructions and task_instructions != task.get("instructions"):
        sections.append(f"## Additional Instructions\n{task_instructions}")

    file_tree = context.get("file_tree", "")
    if file_tree:
        sections.append(f"## Project File Tree\n```\n{file_tree}\n```")

    file_contents = context.get("file_contents", {})
    if file_contents:
        parts = ["## Source Files"]
        for fpath, content in file_contents.items():
            parts.append(f"### {fpath}\n```\n{content}\n```")
        sections.append("\n".join(parts))

    progress = context.get("progress_summary", "")
    if progress:
        sections.append(f"## Recent Progress\n{progress}")

    completed = context.get("completed_tasks", [])
    if completed:
        lines = ["## Recently Completed Tasks"]
        for c in completed[-5:]:
            lines.append(
                f"- Iteration {c.get('iteration')}: {c.get('task_type')} — "
                f"{c.get('summary', '')}"
            )
        sections.append("\n".join(lines))

    benchmarks = context.get("recent_benchmarks", [])
    if benchmarks:
        lines = ["## Recent Benchmarks"]
        for b in benchmarks:
            delta = b.get("delta_pct", "N/A")
            dur = b.get("duration", "N/A")
            lines.append(f"- Duration: {dur}, Delta: {delta}%")
        sections.append("\n".join(lines))

    sections.append(
        "## Output Requirements\n\n"
        "1. Start with a `<vigil-analysis>` block explaining your reasoning "
        "(problem, root cause, approach, impact, risk, files affected).\n"
        "2. Then produce your code changes using the SEARCH/REPLACE format.\n"
        "3. Add inline comments to explain WHY you made each change — "
        "especially for non-obvious logic, bug fixes, and optimizations.\n"
        "4. If you update a function's behavior, update its docstring too.\n"
        "5. Do NOT add trivial comments that just restate the code."
    )

    return "\n\n".join(sections)
