"""Benchmark runner — gates changes on performance regression."""

import json
import logging
import subprocess
from pathlib import Path

from vigil.config import BenchmarksConfig

log = logging.getLogger(__name__)


class BenchmarkRunner:
    def __init__(self, config: BenchmarksConfig, project_path: str):
        self._config = config
        self._cwd = Path(project_path)
        self._last_result: dict | None = None

    def run(self) -> dict | None:
        if not self._config.command:
            return None

        try:
            result = subprocess.run(
                self._config.command,
                shell=True,
                cwd=self._cwd,
                capture_output=True,
                text=True,
                timeout=self._config.timeout,
            )
        except subprocess.TimeoutExpired:
            log.warning("Benchmark timed out after %ds", self._config.timeout)
            return None
        except Exception as e:
            log.error("Benchmark execution failed: %s", e)
            return None

        parsed = self._parse_results(result.stdout, self._config.results_path)
        if parsed:
            self._last_result = parsed
        return parsed

    def run_and_compare(self) -> dict | None:
        previous = self._last_result
        current = self.run()
        if current is None:
            return None

        if previous and "duration" in previous and "duration" in current:
            old_dur = previous["duration"]
            new_dur = current["duration"]
            if old_dur > 0:
                current["delta_pct"] = round((new_dur - old_dur) / old_dur * 100, 2)
            else:
                current["delta_pct"] = 0.0
            current["previous_duration"] = old_dur
        else:
            current["delta_pct"] = 0.0

        return current

    def _parse_results(self, stdout: str, results_path: str) -> dict:
        if results_path:
            rp = self._cwd / results_path
            if rp.exists():
                try:
                    return json.loads(rp.read_text())
                except (json.JSONDecodeError, OSError) as e:
                    log.warning("Failed to read results file %s: %s", rp, e)

        # Fallback: extract basic timing from stdout
        data: dict = {"raw_output": stdout[:2000]}
        lines = stdout.strip().splitlines()
        for line in lines:
            lower = line.lower()
            if "time" in lower or "duration" in lower or "elapsed" in lower:
                for token in line.split():
                    try:
                        data["duration"] = float(token)
                        break
                    except ValueError:
                        continue
        return data
