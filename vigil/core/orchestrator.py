"""Core orchestration loop — drives the continuous improvement cycle."""

import logging
import re
import subprocess
import time
from datetime import datetime, timezone

from vigil.config import VigilConfig
from vigil.core.benchmark import BenchmarkRunner
from vigil.core.code_applier import CodeApplier
from vigil.core.git_ops import GitManager
from vigil.core.merge_queue import MergeQueue
from vigil.core.pr_manager import PRManager, iteration_branch_name
from vigil.core.state import StateManager
from vigil.core.task_planner import TaskPlanner
from vigil.core.worktree import WorktreeManager, require_git_worktree_support
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
        from vigil.core.context_engine import ContextEngine

        self.context_engine = ContextEngine(config)
        # Always available for GET /api/pr/status and hot-reload (not only after start()).
        self.pr_manager = PRManager(config.project.path, config.pr)
        self.worktree_mgr = WorktreeManager(config.project.path)
        self.merge_queue = MergeQueue(
            config.project.path,
            config.controls.work_branch,
            base_if_missing=config.pr.base_branch,
        )
        self._pr_enabled = False
        self._pr_push_enabled = False
        self._pr_gh_enabled = False
        self._running = False
        self._paused = False
        self._current_task: dict | None = None
        self._current_iteration = 0
        self._current_ilog = None
        self._daily_count = 0
        self._no_improve_streak = 0
        self._start_time: datetime | None = None
        self._iteration_branch_label: str | None = None

    def _fork_parent_ref(self) -> str:
        """Branch to fork each iteration worktree from (independent iterations)."""
        if self.config.pr.enabled:
            return self.config.pr.base_branch
        return self.config.controls.work_branch

    def apply_pr_config_from_config(self) -> None:
        """Refresh PRManager and preflight flags from ``self.config`` (startup and PUT /config)."""
        self.pr_manager = PRManager(self.config.project.path, self.config.pr)
        self._pr_push_enabled = False
        self._pr_gh_enabled = False
        self._pr_enabled = bool(self.config.pr.enabled)

        if self.config.pr.enabled:
            push_ok, push_msg = self.pr_manager.preflight_push()
            gh_ok, gh_msg = self.pr_manager.preflight_gh_pr()
            self._pr_push_enabled = push_ok
            self._pr_gh_enabled = gh_ok
            if push_ok and gh_ok:
                log.info(
                    "PR section enabled — push + gh pr create ready (base %s)",
                    self.config.pr.base_branch,
                )
            elif push_ok:
                log.warning(
                    "Git push enabled; gh pr disabled (%s). Branches will push; open PRs manually or fix gh.",
                    gh_msg,
                )
            elif gh_ok:
                log.warning(
                    "gh ready but push disabled (%s). Configure origin to push branches.",
                    push_msg,
                )
            else:
                log.warning(
                    "PR automation limited — push: %s; gh: %s",
                    push_msg,
                    gh_msg,
                )

            _pr_msgs = []
            if not push_ok:
                _pr_msgs.append(push_msg)
            if not gh_ok:
                _pr_msgs.append(gh_msg)
            self._broadcast(
                "pr_status",
                {
                    "enabled": True,
                    "push_enabled": push_ok,
                    "gh_pr_enabled": gh_ok,
                    "preflight_message": (
                        " ".join(_pr_msgs) if _pr_msgs else "PR workflow ready"
                    ),
                },
            )
        else:
            log.info(
                "PR disabled — local iteration branches from %s via worktrees",
                self._fork_parent_ref(),
            )
            self._broadcast(
                "pr_status",
                {
                    "enabled": False,
                    "push_enabled": False,
                    "gh_pr_enabled": False,
                    "preflight_message": "PR disabled — local iteration branches only",
                },
            )

    def start(self) -> None:
        self._running = True
        self._start_time = datetime.now(timezone.utc)
        log.info("Vigil starting — provider: %s", self.provider.name())

        try:
            require_git_worktree_support()
        except RuntimeError as e:
            log.error("%s", e)
            self._running = False
            return

        try:
            self.merge_queue.ensure_worktree()
        except Exception as e:
            log.warning("Merge queue worktree not ready (merges may fail): %s", e)

        removed = self.worktree_mgr.cleanup_stale()
        if removed:
            log.info("Removed %d stale worktree path(s) on startup", removed)

        self.apply_pr_config_from_config()

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
        """Main repo branch; during iteration prefer the iteration branch name."""
        if self._iteration_branch_label:
            return self._iteration_branch_label
        b = self.git.get_current_branch()
        return b if b else self.config.controls.work_branch

    def get_status(self) -> dict:
        uptime = 0.0
        if self._start_time:
            uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds()
        mq_head = ""
        try:
            mq_head = self.merge_queue.current_head()
        except Exception:
            pass
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
            "merge_branch": self.config.controls.work_branch,
            "merge_queue_head": mq_head,
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

        pr_branch = iteration_branch_name(
            iteration, task["type"], task.get("description", ""),
        )
        parent = self._fork_parent_ref()
        wt_handle = None
        iter_git: GitManager | None = None
        self._iteration_branch_label = pr_branch

        _provider_name = self.provider.name()

        def _finalize_failure(
            status: str,
            summary: str,
            bench: dict | None = None,
            *,
            delete_iteration_branch: bool = True,
            **kw,
        ) -> None:
            entry = ilog.to_dict(
                status, summary, bench or {},
                branch_name=pr_branch,
                provider_name=_provider_name,
                **kw,
            )
            self.state.save_iteration(entry)
            self._current_ilog = None
            self._iteration_branch_label = None
            self._no_improve_streak += 1
            self._broadcast("iteration_complete", {
                "iteration": iteration, "status": status, "summary": summary,
                "duration_ms": entry.get("duration_ms", 0),
            })
            if wt_handle is not None:
                self.worktree_mgr.remove(wt_handle, delete_branch=delete_iteration_branch)

        if not self.pr_manager or not self.pr_manager.local_branch_exists(parent):
            ilog.begin_step("Iteration workspace")
            ilog.end_step(
                f"Missing local branch {parent!r} — create it or set pr.base_branch / controls.work_branch"
            )
            _finalize_failure(
                "config_error",
                f"Fork parent branch {parent!r} does not exist locally",
                delete_iteration_branch=False,
            )
            return

        try:
            ilog.begin_step("Creating iteration worktree")
            wt_handle = self.worktree_mgr.create(pr_branch, parent)
            ilog.end_step(f"Worktree: {wt_handle.path} (branch {pr_branch} from {parent})")
        except Exception as e:
            log.error("Failed to create iteration worktree: %s", e)
            ilog.end_step(f"Failed: {e}")
            _finalize_failure("worktree_error", str(e), delete_iteration_branch=False)
            return

        iter_git = GitManager(str(wt_handle.path))
        iter_applier = CodeApplier(
            str(wt_handle.path),
            self.config.project.read_only_paths,
        )
        iter_bench = BenchmarkRunner(self.config.benchmarks, str(wt_handle.path))
        wt_root = wt_handle.path

        ilog.begin_step("Building context")
        context = self.context_engine.build(
            task,
            progress_summary=self.state.get_progress_summary(last_n=10),
            recent_benchmarks=self.state.get_recent_benchmarks(last_n=5),
            completed_tasks=self.state.get_completed_tasks(last_n=10),
            project_root=wt_root,
        )
        file_count = len(context.get("file_contents", {}))
        ilog.end_step({
            "files_scanned": file_count,
            "file_tree_lines": len(context.get("file_tree", "").splitlines()),
            "files_included": list(context.get("file_contents", {}).keys()),
            "reference_docs": list(context.get("reference_docs", {}).keys()),
        })

        from vigil.prompts.system import get_system_prompt
        from vigil.prompts.tasks import get_task_prompt

        system_prompt = get_system_prompt(self.config)
        user_prompt = get_task_prompt(task, context, self.config)
        ilog.add_step("Prompts prepared", {
            "system_prompt_len": len(system_prompt),
            "user_prompt_len": len(user_prompt),
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
            if self.config.controls.stop_on_llm_error:
                log.warning(
                    "Stopping Vigil after LLM error (controls.stop_on_llm_error). "
                    "Fix the provider or set stop_on_llm_error: false in vigil.yaml to retry."
                )
                self._running = False
                self._broadcast(
                    "orchestrator_stop",
                    {"reason": "llm_error", "message": str(e)},
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
        changes, blocked_readonly = iter_applier.parse_and_apply(response.text)
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
        ok, validation_msg = iter_applier.validate_changes(
            changes,
            self.config.controls.max_files_per_iteration,
            self.config.controls.max_lines_changed,
        )
        if not ok:
            ilog.end_step(validation_msg)
            iter_git.revert_all()
            ilog.add_step(
                "Working tree reverted",
                "All edits from this iteration were discarded so the repo matches the pre-iteration state.",
            )
            _finalize_failure(
                "safety_revert",
                validation_msg,
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
            test_ok, test_output = self._run_tests_capture(cwd=str(wt_root))
            ilog.end_step({
                "passed": test_ok,
                "output_lines": len(test_output.splitlines()),
                "output_preview": test_output[:2000],
            })
            if not test_ok:
                iter_git.revert_all()
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
            bench_result = iter_bench.run_and_compare()
            ilog.end_step(bench_result or "No result")
            if bench_result and bench_result.get("delta_pct", 0) < self.config.benchmarks.regression_threshold:
                iter_git.revert_all()
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
        diff_before_commit = iter_git.get_diff()

        ilog.begin_step("Committing changes")
        commit_msg = f"{self.config.controls.commit_prefix}: {task['type']} — {task['description']}"
        if analysis_text:
            first_line = analysis_text.split("\n")[0].strip().lstrip("*").strip()
            if first_line and len(first_line) < 200:
                commit_msg += f"\n\n{analysis_text[:500]}"
        commit_hash = ""
        if iter_git.has_changes():
            iter_git.commit(commit_msg)
            commit_hash = iter_git.get_last_commit_hash()
        ilog.end_step({"commit_hash": commit_hash, "message": commit_msg})

        merge_ok = False
        merge_msg = ""
        try:
            ilog.begin_step("Merge queue (into work branch)")
            mr = self.merge_queue.try_merge(
                pr_branch,
                merge_message=f"vigil: merge {pr_branch}",
            )
            merge_ok = mr.success
            merge_msg = mr.message
            if mr.success:
                ilog.end_step({"merged": True, "commit": mr.commit_hash})
            else:
                ilog.end_step({"merged": False, "detail": merge_msg[:500]})
        except Exception as e:
            log.warning("Merge queue error: %s", e)
            ilog.end_step(f"Merge queue error: {e}")
            merge_msg = str(e)

        summary = f"Applied {len(changes)} change(s)"
        if analysis_text:
            reason = analysis_text.split("\n")[0].strip().lstrip("*").strip()
            if reason:
                summary += f" — {reason[:120]}"
        if bench_result:
            summary += f", benchmark delta: {bench_result.get('delta_pct', 0):.2f}%"
            self.state.save_benchmark(bench_result)
        if not merge_ok:
            summary += f" — merge queue: {merge_msg[:200]}"

        pr_url = None
        if self.pr_manager:
            if self.config.pr.enabled:
                if not self.config.pr.auto_push:
                    ilog.add_step(
                        "Push skipped",
                        "pr.auto_push is false — set true in vigil.yaml to push after each iteration.",
                    )
                elif self._pr_push_enabled:
                    ilog.begin_step("Pushing branch to origin")
                    pushed_ok, push_err = self.pr_manager.push_branch(pr_branch)
                    ilog.end_step(
                        "Pushed to origin"
                        if pushed_ok
                        else f"Failed: {push_err[:800]}",
                    )
                    if pushed_ok and self._pr_gh_enabled:
                        ilog.begin_step("Creating pull request")
                        pr_url = self._create_pr(iter_git, pr_branch, task, bench_result)
                        if pr_url:
                            summary += f" — PR: {pr_url}"
                        ilog.end_step(pr_url or "PR creation failed")
                    elif pushed_ok and not self._pr_gh_enabled:
                        ilog.add_step(
                            "PR not created automatically",
                            "Branch pushed to origin. Install and authenticate GitHub CLI (gh) "
                            "for automatic PRs, or open a PR manually on GitHub.",
                        )
                else:
                    ilog.add_step(
                        "Push skipped",
                        "No git remote or git unavailable — add `origin` to push branches.",
                    )
            else:
                ilog.add_step(
                    "Local iteration branch",
                    f"Set pr.enabled: true in vigil.yaml to push and open PRs. Branch: {pr_branch}",
                )

        final_status = "success" if merge_ok else "merge_conflict"
        if not merge_ok and commit_hash:
            summary = (
                f"{summary} (iteration commit OK; merge into {self.config.controls.work_branch} failed — "
                f"resolve conflicts manually or delete branch {pr_branch})"
            )

        final_diff = ""
        if commit_hash:
            final_diff = iter_git.get_commit_diff(commit_hash)
        if not final_diff:
            final_diff = diff_before_commit

        ilog.add_step("Iteration complete", summary)

        entry = ilog.to_dict(
            final_status, summary, bench_result or {},
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
            branch_name=pr_branch,
            provider_name=self.provider.name(),
        )
        self.state.save_iteration(entry)
        self._current_ilog = None
        self._iteration_branch_label = None

        if wt_handle is not None:
            self.worktree_mgr.remove(wt_handle, delete_branch=False)

        self._no_improve_streak = 0
        self._daily_count += 1
        log.info("Iteration %d finished: %s", iteration, summary)
        self._broadcast("iteration_complete", {
            "iteration": iteration,
            "status": final_status,
            "summary": summary,
            "pr_url": pr_url,
            "duration_ms": entry.get("duration_ms", 0),
        })

    def _run_tests(self) -> bool:
        ok, _ = self._run_tests_capture()
        return ok

    def _run_tests_capture(self, cwd: str | None = None) -> tuple[bool, str]:
        root = cwd if cwd is not None else self.config.project.path
        try:
            result = subprocess.run(
                self.config.tests.command,
                shell=True,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=self.config.tests.timeout,
            )
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            return result.returncode == 0, output.strip()
        except subprocess.TimeoutExpired:
            log.warning("Tests timed out")
            return False, "Tests timed out"

    def _create_pr(
        self,
        iter_git: GitManager,
        branch: str,
        task: dict,
        bench_result: dict | None,
    ) -> str | None:
        """Generate PR description and create the pull request."""
        commit_hash = iter_git.get_last_commit_hash()
        diff = iter_git.get_commit_diff(commit_hash)
        files = iter_git.get_commit_files(commit_hash)

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

        if not self.pr_manager:
            return None
        return self.pr_manager.create_pr_with_gh(branch, title, pr_body)

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
