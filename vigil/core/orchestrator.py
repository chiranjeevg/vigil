"""Core orchestration loop — drives the continuous improvement cycle."""

import logging
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from vigil.config import VigilConfig
from vigil.core.benchmark import BenchmarkRunner
from vigil.core.code_applier import CodeApplier
from vigil.core.git_ops import GitManager
from vigil.core.pr_manager import PRManager
from vigil.core.state import StateManager
from vigil.core.task_planner import TaskPlanner
from vigil.providers.base import BaseProvider

log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, config: VigilConfig, provider: BaseProvider):
        self.config = config
        self.provider = provider
        self.state = StateManager(config.project.path)
        self.git = GitManager(config.project.path)
        self.bench = BenchmarkRunner(config.benchmarks, config.project.path)
        self.planner = TaskPlanner(self.state, config)
        self.applier = CodeApplier(config.project.path, config.project.read_only_paths)
        self.pr_manager: PRManager | None = None
        self._pr_enabled = False
        # True when gh + remote + auth succeed; gates push and gh pr create only.
        self._pr_push_enabled = False
        self._running = False
        self._paused = False
        self._current_task: dict | None = None
        self._current_iteration = 0
        self._current_ilog = None
        self._daily_count = 0
        self._no_improve_streak = 0
        self._start_time: datetime | None = None

    def start(self) -> None:
        self._running = True
        self._start_time = datetime.now(timezone.utc)
        log.info("Vigil starting — provider: %s", self.provider.name())

        if self.config.pr.enabled:
            self.pr_manager = PRManager(self.config.project.path, self.config.pr)
            push_ok, push_msg = self.pr_manager.preflight_check()
            # Local vigil/* branches do not require gh or a remote; only push/PR does.
            self._pr_enabled = True
            self._pr_push_enabled = push_ok
            if push_ok:
                log.info(
                    "PR section enabled — iteration branches from %s; push/PR enabled",
                    self.config.pr.base_branch,
                )
            else:
                log.warning(
                    "PR push disabled (%s). Local vigil/* iteration branches are still created.",
                    push_msg,
                )

            restored = self.state.get_last_successful_branch()
            if restored and self.pr_manager.local_branch_exists(restored):
                self.pr_manager.set_last_successful_branch(restored)
                log.info(
                    "Restored iterative branch chain — next iteration forks from %s",
                    restored,
                )
            elif restored:
                log.warning(
                    "Stored iterative branch %s not found locally — resetting chain to %s",
                    restored,
                    self.config.pr.base_branch,
                )
                self.state.set_last_successful_branch(None)

            self._broadcast(
                "pr_status",
                {
                    "enabled": True,
                    "push_enabled": push_ok,
                    "preflight_message": push_msg,
                },
            )

        if not self._pr_enabled:
            self.git.ensure_branch(self.config.controls.work_branch)

        self._run_loop()

    def stop(self) -> None:
        log.info("Vigil stopping...")
        self._running = False

    def pause(self) -> None:
        self._paused = True
        log.info("Vigil paused")

    def resume(self) -> None:
        self._paused = False
        log.info("Vigil resumed")

    def get_live_iteration(self) -> dict | None:
        """Return the in-progress iteration log, or None if idle."""
        ilog = self._current_ilog
        if ilog is None:
            return None
        return {
            "iteration": ilog.iteration,
            "task_type": ilog.task.get("type", ""),
            "task_description": ilog.task.get("description", ""),
            "started_at": ilog.started_at.isoformat(),
            "elapsed_ms": ilog.total_duration_ms(),
            "steps": ilog.steps,
            "provider": self.provider.name(),
            "branch": self._current_branch_label(),
        }

    def _current_branch_label(self) -> str:
        """Actual git HEAD branch (PR iteration branch or work_branch)."""
        b = self.git.get_current_branch()
        return b if b else self.config.controls.work_branch

    def get_status(self) -> dict:
        uptime = 0.0
        if self._start_time:
            uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds()
        return {
            "running": self._running,
            "paused": self._paused,
            "iteration": self._current_iteration,
            "current_task": self._current_task,
            "daily_count": self._daily_count,
            "no_improve_streak": self._no_improve_streak,
            "uptime_seconds": uptime,
            "provider": self.provider.name(),
            "branch": self._current_branch_label(),
            "project_name": self.config.project.name,
            "project_path": self.config.project.path,
        }

    def _run_loop(self) -> None:
        while self._running:
            if self._paused:
                time.sleep(5)
                continue

            if self._check_battery_pause():
                log.info("On battery power — pausing")
                time.sleep(60)
                continue

            if self._daily_count >= self.config.controls.max_iterations_per_day:
                log.info("Daily iteration limit reached. Sleeping 1 hour.")
                time.sleep(3600)
                self._daily_count = 0
                continue

            total_limit = self.config.controls.max_iterations_total
            if total_limit and self._current_iteration >= total_limit:
                log.info("Total iteration limit reached. Stopping.")
                self._running = False
                break

            try:
                self._run_iteration()
            except Exception as e:
                log.error("Iteration failed with unexpected error: %s", e, exc_info=True)
                time.sleep(self.config.controls.sleep_after_failure)

            time.sleep(self.config.controls.sleep_between_iterations)

    def _run_iteration(self) -> None:
        iteration = self.state.next_iteration()
        self._current_iteration = iteration
        log.info("=== Iteration %d ===", iteration)

        task = self.planner.next_task(self._no_improve_streak)
        self._current_task = task
        log.info("Task: %s — %s", task["type"], task["description"])

        ilog = self.state.new_iteration_log(iteration, task, broadcast_fn=self._broadcast)
        self._current_ilog = ilog
        self._broadcast("iteration_start", {
            "iteration": iteration,
            "task_type": task["type"],
            "task_description": task["description"],
            "provider": self.provider.name(),
        })
        ilog.add_step("Task selected", {
            "type": task["type"],
            "description": task["description"],
            "no_improve_streak": self._no_improve_streak,
        })

        pr_branch: str | None = None
        if self._pr_enabled and self.pr_manager:
            ilog.begin_step("Creating iteration branch")
            try:
                pr_branch = self.pr_manager.create_iteration_branch(
                    iteration, task["type"], task.get("description", ""),
                )
                parent = self.pr_manager.parent_branch
                ilog.end_step(f"Branch: {pr_branch} (from {parent})")
            except Exception as e:
                log.error("Failed to create PR branch: %s — falling back to work branch", e)
                self.git.ensure_branch(self.config.controls.work_branch)
                ilog.end_step(f"Failed: {e} — using work branch")

        ilog.begin_step("Building context")
        context = self._build_context(task)
        file_count = len(context.get("file_contents", {}))
        ilog.end_step({
            "files_scanned": file_count,
            "file_tree_lines": len(context.get("file_tree", "").splitlines()),
            "files_included": list(context.get("file_contents", {}).keys()),
        })

        from vigil.prompts.system import get_system_prompt
        from vigil.prompts.tasks import get_task_prompt

        system_prompt = get_system_prompt(self.config)
        user_prompt = get_task_prompt(task, context, self.config)
        ilog.add_step("Prompts prepared", {
            "system_prompt_len": len(system_prompt),
            "user_prompt_len": len(user_prompt),
        })

        _provider_name = self.provider.name()
        _work_branch = pr_branch or self.config.controls.work_branch

        def _finalize_failure(status: str, summary: str, bench: dict | None = None, **kw):
            """Save a failed iteration and clean up the branch."""
            entry = ilog.to_dict(
                status, summary, bench or {},
                branch_name=_work_branch,
                provider_name=_provider_name,
                **kw,
            )
            self.state.save_iteration(entry)
            self._current_ilog = None
            if pr_branch and self.pr_manager:
                self.pr_manager.cleanup_branch(pr_branch)
            self._no_improve_streak += 1
            self._broadcast("iteration_complete", {
                "iteration": iteration, "status": status, "summary": summary,
                "duration_ms": entry.get("duration_ms", 0),
            })

        ilog.begin_step("LLM inference")
        try:
            response = self.provider.complete(system_prompt, user_prompt)
            ilog.end_step({
                "tokens": response.tokens_used,
                "duration_s": round(response.duration_seconds, 2),
                "response_len": len(response.text),
            })
            log.info(
                "LLM responded in %.1fs (%d tokens)",
                response.duration_seconds,
                response.tokens_used,
            )
        except Exception as e:
            log.error("LLM call failed: %s", e)
            ilog.end_step(f"Error: {e}")
            _finalize_failure(
                "llm_error", str(e),
                llm_prompt_system=system_prompt,
                llm_prompt_user=user_prompt,
            )
            return

        analysis_text = ""
        analysis_match = re.search(
            r"<vigil-analysis>(.*?)</vigil-analysis>",
            response.text,
            re.DOTALL,
        )
        if analysis_match:
            analysis_text = analysis_match.group(1).strip()
            ilog.add_step("LLM analysis & reasoning", analysis_text)
            log.info("LLM analysis: %s", analysis_text[:200])

        if self.config.controls.dry_run:
            log.info("Dry run — skipping apply")
            ilog.add_step("Dry run — skipped apply")
            _finalize_failure(
                "dry_run", response.text[:500],
                llm_response=response.text,
                llm_prompt_system=system_prompt,
                llm_prompt_user=user_prompt,
                llm_tokens=response.tokens_used,
                llm_duration_s=response.duration_seconds,
            )
            return

        ilog.begin_step("Parsing & applying changes")
        changes, blocked_readonly = self.applier.parse_and_apply(response.text)
        end_apply: dict = {
            "changes_applied": len(changes),
            "changes": changes,
        }
        if blocked_readonly:
            end_apply["blocked_readonly_paths"] = blocked_readonly
        ilog.end_step(end_apply)
        if blocked_readonly:
            ilog.add_step(
                "Skipped read-only targets (vigil.yaml read_only_paths)",
                "\n".join(blocked_readonly),
            )

        if not changes:
            log.warning("No applicable changes produced")
            ilog.add_step("No changes extracted from LLM output")
            _finalize_failure(
                "no_changes", "LLM produced no applicable changes",
                llm_response=response.text,
                llm_prompt_system=system_prompt,
                llm_prompt_user=user_prompt,
                llm_tokens=response.tokens_used,
                llm_duration_s=response.duration_seconds,
            )
            return

        ilog.begin_step("Validating change size")
        if not self.applier.validate_changes(
            changes,
            self.config.controls.max_files_per_iteration,
            self.config.controls.max_lines_changed,
        ):
            ilog.end_step("FAILED — too many changes, reverting")
            self.git.revert_all()
            _finalize_failure(
                "safety_revert", "Too many changes",
                llm_response=response.text,
                llm_prompt_system=system_prompt,
                llm_prompt_user=user_prompt,
                llm_tokens=response.tokens_used,
                llm_duration_s=response.duration_seconds,
                changes_detail=changes,
                files_changed=[c["file"] for c in changes],
            )
            return
        ilog.end_step("OK")

        test_output = ""
        if self.config.controls.require_test_pass and self.config.tests.command:
            ilog.begin_step(f"Running tests: {self.config.tests.command}")
            test_ok, test_output = self._run_tests_capture()
            ilog.end_step({
                "passed": test_ok,
                "output_lines": len(test_output.splitlines()),
                "output_preview": test_output[:2000],
            })
            if not test_ok:
                self.git.revert_all()
                ilog.add_step("Tests failed — changes reverted")
                _finalize_failure(
                    "tests_failed", "Tests failed after changes",
                    llm_response=response.text,
                    llm_prompt_system=system_prompt,
                    llm_prompt_user=user_prompt,
                    llm_tokens=response.tokens_used,
                    llm_duration_s=response.duration_seconds,
                    changes_detail=changes,
                    files_changed=[c["file"] for c in changes],
                    test_output=test_output,
                )
                return

        bench_result = None
        if self.config.benchmarks.enabled and iteration % self.config.benchmarks.run_every == 0:
            ilog.begin_step(f"Running benchmarks: {self.config.benchmarks.command}")
            bench_result = self.bench.run_and_compare()
            ilog.end_step(bench_result or "No result")
            if bench_result and bench_result.get("delta_pct", 0) < self.config.benchmarks.regression_threshold:
                self.git.revert_all()
                ilog.add_step(f"Benchmark regression ({bench_result['delta_pct']:.2f}%) — changes reverted")
                _finalize_failure(
                    "benchmark_regression",
                    f"Regression: {bench_result['delta_pct']:.2f}%",
                    bench_result,
                    llm_response=response.text,
                    llm_prompt_system=system_prompt,
                    llm_prompt_user=user_prompt,
                    llm_tokens=response.tokens_used,
                    llm_duration_s=response.duration_seconds,
                    changes_detail=changes,
                    files_changed=[c["file"] for c in changes],
                    test_output=test_output,
                )
                return

        files_changed = [c["file"] for c in changes]
        diff_before_commit = self.git.get_diff()

        ilog.begin_step("Committing changes")
        commit_msg = f"{self.config.controls.commit_prefix}: {task['type']} — {task['description']}"
        if analysis_text:
            first_line = analysis_text.split("\n")[0].strip().lstrip("*").strip()
            if first_line and len(first_line) < 200:
                commit_msg += f"\n\n{analysis_text[:500]}"
        commit_hash = ""
        if self.git.has_changes():
            self.git.commit(commit_msg)
            commit_hash = self.git.get_last_commit_hash()
        ilog.end_step({"commit_hash": commit_hash, "message": commit_msg})

        summary = f"Applied {len(changes)} change(s)"
        if analysis_text:
            reason = analysis_text.split("\n")[0].strip().lstrip("*").strip()
            if reason:
                summary += f" — {reason[:120]}"
        if bench_result:
            summary += f", benchmark delta: {bench_result.get('delta_pct', 0):.2f}%"
            self.state.save_benchmark(bench_result)

        pr_url = None
        if pr_branch and self.pr_manager:
            self.pr_manager.mark_success(pr_branch)
            self.state.set_last_successful_branch(pr_branch)

            if self._pr_push_enabled:
                ilog.begin_step("Creating pull request")
                pr_url = self._create_pr(pr_branch, task, bench_result)
                if pr_url:
                    summary += f" — PR: {pr_url}"
                ilog.end_step(pr_url or "PR creation failed")
            else:
                ilog.add_step(
                    "PR push skipped",
                    "Add a git remote and run `gh auth login` to push branches and open PRs.",
                )

            self.pr_manager.stay_on_branch(pr_branch)
            log.info("Staying on branch %s for next iteration to build upon", pr_branch)

        final_diff = ""
        if commit_hash:
            final_diff = self.git.get_commit_diff(commit_hash)
        if not final_diff:
            final_diff = diff_before_commit

        ilog.add_step("Iteration complete", summary)

        entry = ilog.to_dict(
            "success", summary, bench_result or {},
            files_changed=files_changed,
            diff=final_diff,
            commit_hash=commit_hash,
            llm_response=response.text,
            llm_prompt_system=system_prompt,
            llm_prompt_user=user_prompt,
            llm_tokens=response.tokens_used,
            llm_duration_s=response.duration_seconds,
            changes_detail=changes,
            test_output=test_output,
            branch_name=pr_branch or self.config.controls.work_branch,
            provider_name=self.provider.name(),
        )
        self.state.save_iteration(entry)
        self._current_ilog = None

        self._no_improve_streak = 0
        self._daily_count += 1
        log.info("Iteration %d succeeded: %s", iteration, summary)
        self._broadcast("iteration_complete", {
            "iteration": iteration,
            "status": "success",
            "summary": summary,
            "pr_url": pr_url,
            "duration_ms": entry.get("duration_ms", 0),
        })

    def _run_tests(self) -> bool:
        ok, _ = self._run_tests_capture()
        return ok

    def _run_tests_capture(self) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                self.config.tests.command,
                shell=True,
                cwd=self.config.project.path,
                capture_output=True,
                text=True,
                timeout=self.config.tests.timeout,
            )
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            return result.returncode == 0, output.strip()
        except subprocess.TimeoutExpired:
            log.warning("Tests timed out")
            return False, "Tests timed out"

    def _create_pr(self, branch: str, task: dict, bench_result: dict | None) -> str | None:
        """Generate PR description and create the pull request."""
        commit_hash = self.git.get_last_commit_hash()
        diff = self.git.get_commit_diff(commit_hash)
        files = self.git.get_commit_files(commit_hash)

        if self.config.pr.use_llm_description:
            try:
                from vigil.prompts.pr import get_pr_description_prompt
                prompt = get_pr_description_prompt(task, diff, files, bench_result)
                resp = self.provider.complete(
                    "You are a technical writer. Write only the PR description in markdown. No preamble.",
                    prompt,
                )
                pr_body = resp.text
                log.info("LLM generated PR description (%d chars)", len(pr_body))
            except Exception as e:
                log.warning("LLM PR description failed, using static: %s", e)
                from vigil.prompts.pr import build_static_pr_body
                pr_body = build_static_pr_body(task, files, bench_result)
        else:
            from vigil.prompts.pr import build_static_pr_body
            pr_body = build_static_pr_body(task, files, bench_result)

        task_type = task.get("type", "improvement")
        desc = task.get("description", task_type)
        prefix_map = {
            "optimize_performance": "perf",
            "fix_tests": "fix",
            "test_coverage": "test",
            "modernize_code": "refactor",
            "reduce_complexity": "refactor",
            "refactor": "refactor",
        }
        prefix = prefix_map.get(task_type, "improve")
        title = f"{prefix}({self.config.project.name}): {desc}"
        if len(files) == 1:
            title += f" in {files[0]}"
        elif len(files) <= 3:
            title += f" [{', '.join(files)}]"

        return self.pr_manager.push_and_create_pr(branch, title, pr_body)

    def _build_context(self, task: dict) -> dict:
        project_path = Path(self.config.project.path)
        context: dict = {}

        context["file_tree"] = self._get_file_tree(project_path)
        context["progress_summary"] = self.state.get_progress_summary(last_n=10)
        context["recent_benchmarks"] = self.state.get_recent_benchmarks(last_n=5)
        context["completed_tasks"] = self.state.get_completed_tasks(last_n=10)

        target_files = task.get("target_files", [])
        file_contents: dict[str, str] = {}

        if target_files:
            for fpath in target_files:
                full = project_path / fpath
                if full.exists() and full.is_file():
                    try:
                        file_contents[fpath] = full.read_text(errors="replace")[:10000]
                    except OSError:
                        pass
        else:
            # Pick files based on task type by scanning include paths
            for inc in self.config.project.include_paths:
                inc_path = project_path / inc
                if not inc_path.exists():
                    continue
                for f in sorted(inc_path.rglob("*")):
                    if f.is_file() and not self._is_excluded(f, project_path):
                        rel = str(f.relative_to(project_path))
                        if len(file_contents) >= 10:
                            break
                        try:
                            file_contents[rel] = f.read_text(errors="replace")[:10000]
                        except OSError:
                            pass

        context["file_contents"] = file_contents
        return context

    def _get_file_tree(self, project_path: Path) -> str:
        lines: list[str] = []
        for inc in self.config.project.include_paths:
            inc_path = project_path / inc
            if not inc_path.exists():
                continue
            for f in sorted(inc_path.rglob("*")):
                if f.is_file() and not self._is_excluded(f, project_path):
                    lines.append(str(f.relative_to(project_path)))
        return "\n".join(lines[:200])

    def _is_excluded(self, filepath: Path, project_path: Path) -> bool:
        rel = str(filepath.relative_to(project_path))
        for exc in self.config.project.exclude_paths:
            if rel.startswith(exc) or f"/{exc}" in rel:
                return True
        return False

    def _check_battery_pause(self) -> bool:
        if not self.config.controls.pause_on_battery:
            return False
        try:
            result = subprocess.run(
                ["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5
            )
            return "Battery Power" in result.stdout
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _broadcast(self, event_type: str, data: dict) -> None:
        try:
            from vigil.api.websocket import broadcast_event

            broadcast_event(event_type, data)
        except Exception:
            pass
