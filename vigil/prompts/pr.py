def get_pr_description_prompt(
    task: dict,
    diff: str,
    files_changed: list[str],
    benchmark_data: dict | None,
) -> str:
    bench_section = ""
    if benchmark_data:
        delta = benchmark_data.get("delta_pct", 0)
        duration = benchmark_data.get("duration", "N/A")
        bench_section = f"""
## Benchmark Results
- **Delta**: {delta:+.2f}%
- **Duration**: {duration}
- **Verdict**: {"Improvement" if delta > 0 else "No regression"}
"""

    files_list = "\n".join(f"- `{f}`" for f in files_changed)
    trimmed_diff = diff[:8000]
    if len(diff) > 8000:
        trimmed_diff += "\n... (diff truncated)"

    return f"""\
Write a professional, detailed GitHub pull request description for the following \
automated code change. This PR will be reviewed by engineers, so be specific and technical.

Requirements:
- Start with a concise **## Summary** (2-3 sentences explaining WHAT changed and WHY)
- Include a **## Motivation** section:
  - What problem or code smell was identified?
  - Why does this matter? (performance, reliability, maintainability, security, etc.)
  - Link the reasoning to concrete code issues from the diff
- Include a **## Changes** section:
  - For EACH file changed, write 1-2 sentences explaining what was modified and why
  - Use bullet points with the file path in backticks
  - Highlight any non-obvious design decisions
- If benchmark data is provided, include a **## Performance** section with a markdown table
  showing before/after metrics
- Include a **## Testing** section:
  - Note that automated tests passed
  - Suggest any additional manual testing if relevant
- Include a **## Risk Assessment** section:
  - What could this change break?
  - How is the risk mitigated?
  - Is this change easily reversible?
- Use markdown formatting throughout
- Be specific and technical, not generic
- Do NOT include the raw diff in the description
- Do NOT use phrases like "this PR" in the summary — describe the change directly

## Task Information
- **Type**: {task.get("type", "unknown")}
- **Description**: {task.get("description", "")}
- **Instructions**: {task.get("instructions", "N/A")}

## Files Changed
{files_list}

## Git Diff
```
{trimmed_diff}
```
{bench_section}
Now write the PR description:
"""


def build_static_pr_body(
    task: dict,
    files_changed: list[str],
    benchmark_data: dict | None,
) -> str:
    """Build a PR body without LLM, using structured data only."""
    files_list = "\n".join(f"- `{f}`" for f in files_changed)
    task_type = task.get("type", "unknown")
    task_desc = task.get("description", "")
    instructions = task.get("instructions", "")

    body = f"""## Summary

Automated code improvement: **{task_type}** — {task_desc}

## Motivation

This change was identified and applied by Vigil's autonomous improvement cycle. \
The task type `{task_type}` targets: {task_desc}.
"""

    if instructions:
        body += f"\n**Specific instructions**: {instructions}\n"

    body += f"""
## Changes

{files_list}
"""

    if benchmark_data:
        delta = benchmark_data.get("delta_pct", 0)
        duration = benchmark_data.get("duration", "N/A")
        verdict = "Improvement" if delta > 0 else "No regression"
        body += f"""
## Performance

| Metric | Value |
|--------|-------|
| Delta | {delta:+.2f}% |
| Duration | {duration} |
| Verdict | {verdict} |
"""

    body += """
## Testing

All configured tests passed before this PR was created.

## Risk Assessment

- Changes are scoped to the minimum necessary modification
- All existing tests pass after the change
- Change is fully reversible via git revert

---
*Automatically created by [Vigil](https://github.com/chiranjeevg/vigil) — autonomous code improvement agent.*
"""
    return body
