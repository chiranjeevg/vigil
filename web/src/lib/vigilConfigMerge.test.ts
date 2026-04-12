import { describe, expect, it } from "vitest";
import {
  mergeVigilConfigFromApi,
  normalizeControlsForUi,
} from "@/lib/vigilConfigMerge";

describe("mergeVigilConfigFromApi", () => {
  it("fills all sections from empty object", () => {
    const c = mergeVigilConfigFromApi({});
    expect(c.project.path).toBe("");
    expect(c.project.name).toBe("My Project");
    expect(c.provider.type).toBe("ollama");
    expect(c.tests.timeout).toBe(300);
    expect(c.controls.work_branch).toBe("vigil-improvements");
    expect(c.pr.base_branch).toBe("main");
    expect(c.pr.enabled).toBe(false);
  });

  it("merges partial API payload without dropping required UI fields", () => {
    const c = mergeVigilConfigFromApi({
      project: { path: "/tmp/foo", name: "Foo" },
      provider: { model: "mistral" },
    });
    expect(c.project.path).toBe("/tmp/foo");
    expect(c.project.name).toBe("Foo");
    expect(c.provider.model).toBe("mistral");
    expect(c.provider.base_url).toBe("http://localhost:11434");
    expect(c.tests.coverage.enabled).toBe(false);
    expect(c.benchmarks.enabled).toBe(false);
  });

  it("preserves nested coverage and benchmarks", () => {
    const c = mergeVigilConfigFromApi({
      tests: {
        command: "pytest",
        coverage: { enabled: true, command: "pytest --cov", target: 80 },
      },
      benchmarks: { enabled: true, regression_threshold: -5 },
    });
    expect(c.tests.command).toBe("pytest");
    expect(c.tests.coverage.enabled).toBe(true);
    expect(c.tests.coverage.target).toBe(80);
    expect(c.benchmarks.enabled).toBe(true);
    expect(c.benchmarks.regression_threshold).toBe(-5);
  });

  it("always exposes list fields as arrays for Settings (.length / .join)", () => {
    const c = mergeVigilConfigFromApi({});
    expect(Array.isArray(c.project.include_paths)).toBe(true);
    expect(Array.isArray(c.project.exclude_paths)).toBe(true);
    expect(Array.isArray(c.pr.labels)).toBe(true);
    expect(Array.isArray(c.pr.reviewers)).toBe(true);
    expect(Array.isArray(c.tasks.priorities)).toBe(true);
    expect(Array.isArray(c.tasks.custom)).toBe(true);
  });

  it("coerces YAML-style string booleans for controls and PR", () => {
    const c = mergeVigilConfigFromApi({
      controls: {
        dry_run: "true",
        auto_commit: "no",
        stop_on_llm_error: "0",
      },
      pr: { enabled: "yes", auto_push: "false" },
    });
    expect(c.controls.dry_run).toBe(true);
    expect(c.controls.auto_commit).toBe(false);
    expect(c.controls.stop_on_llm_error).toBe(false);
    expect(c.pr.enabled).toBe(true);
    expect(c.pr.auto_push).toBe(false);
  });
});

describe("normalizeControlsForUi", () => {
  it("applies null and default rules for controls", () => {
    const base = normalizeControlsForUi({
      max_iterations_per_day: 10,
      max_iterations_total: null,
      sleep_between_iterations: 5,
      sleep_after_failure: 0,
      max_consecutive_no_improvement: 1,
      stop_on_llm_error: false,
      min_improvement_threshold: 0.2,
      work_branch: "main",
      auto_commit: true,
      commit_prefix: "x",
      max_files_per_iteration: null,
      max_lines_changed: null,
      require_test_pass: false,
      pause_on_battery: false,
      dry_run: true,
    });
    expect(base.max_iterations_total).toBeNull();
    expect(base.sleep_after_failure).toBe(0);
    expect(base.max_files_per_iteration).toBeNull();
    expect(base.max_lines_changed).toBeNull();
  });
});
