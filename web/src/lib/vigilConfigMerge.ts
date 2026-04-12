import type {
  BenchmarksConfig,
  ControlsConfig,
  GoalsConfig,
  PRConfig,
  ProjectConfig,
  ProviderConfig,
  TasksConfig,
  TestsConfig,
  VigilConfig,
  WorkSourcesConfig,
} from "@/types";

/** PR defaults aligned with Settings.tsx (UI expectations). */
export const DEFAULT_PR: PRConfig = {
  enabled: false,
  strategy: "per_iteration",
  base_branch: "main",
  auto_push: false,
  labels: [],
  reviewers: [],
  use_llm_description: false,
};

const DEFAULT_PROJECT: ProjectConfig = {
  path: "",
  name: "My Project",
  language: "auto",
  include_paths: ["src/", "lib/", "test/", "tests/"],
  exclude_paths: ["node_modules/", "venv/", ".git/", "build/", "dist/"],
};

const DEFAULT_PROVIDER: ProviderConfig = {
  type: "ollama",
  model: "qwen2.5-coder:14b",
  base_url: "http://localhost:11434",
  max_tokens: 8192,
  temperature: 0.2,
};

const DEFAULT_TESTS: TestsConfig = {
  command: "",
  timeout: 300,
  coverage: {
    enabled: false,
    command: "",
    target: 90,
  },
};

const DEFAULT_BENCHMARKS: BenchmarksConfig = {
  enabled: false,
  command: "",
  timeout: 600,
  regression_threshold: -2,
  run_every: 3,
};

const DEFAULT_TASKS: TasksConfig = {
  priorities: [
    "fix_tests",
    "run_benchmarks",
    "test_coverage",
    "optimize_performance",
    "modernize_code",
    "reduce_complexity",
    "fix_warnings",
    "refactor",
  ],
  custom: [],
  instructions: {},
  priority_mode: "improver",
};

const DEFAULT_GOALS: GoalsConfig = {
  current: [],
};

const DEFAULT_GITHUB_ISSUES = {
  enabled: false,
  repos: [] as string[],
  labels_include: [] as string[],
  labels_exclude: ["wontfix", "duplicate", "question"],
  max_tasks: 20,
  poll_interval: 300,
};

const DEFAULT_WORK_SOURCES: WorkSourcesConfig = {
  github_issues: DEFAULT_GITHUB_ISSUES,
  prd_paths: [],
  context_documents: [],
};

const DEFAULT_CONTROLS_BASE: ControlsConfig = {
  max_iterations_per_day: 200,
  max_iterations_total: null,
  sleep_between_iterations: 30,
  sleep_after_failure: 60,
  max_consecutive_no_improvement: 10,
  stop_on_llm_error: true,
  min_improvement_threshold: 0.1,
  work_branch: "vigil-improvements",
  auto_commit: true,
  commit_prefix: "vigil",
  max_files_per_iteration: 5,
  max_lines_changed: 200,
  require_test_pass: true,
  pause_on_battery: true,
  dry_run: false,
};

function isRecord(x: unknown): x is Record<string, unknown> {
  return x !== null && typeof x === "object" && !Array.isArray(x);
}

function toBool(v: unknown, fallback: boolean): boolean {
  if (v === undefined || v === null) return fallback;
  if (typeof v === "boolean") return v;
  if (typeof v === "string") {
    const s = v.trim().toLowerCase();
    if (s === "true" || s === "1" || s === "yes") return true;
    if (s === "false" || s === "0" || s === "no") return false;
  }
  if (typeof v === "number") return v !== 0;
  return fallback;
}

function mergeProject(raw: unknown): ProjectConfig {
  const p = isRecord(raw) ? raw : {};
  return {
    ...DEFAULT_PROJECT,
    ...p,
    include_paths: Array.isArray(p.include_paths)
      ? (p.include_paths as string[])
      : DEFAULT_PROJECT.include_paths,
    exclude_paths: Array.isArray(p.exclude_paths)
      ? (p.exclude_paths as string[])
      : DEFAULT_PROJECT.exclude_paths,
  };
}

function mergeProvider(raw: unknown): ProviderConfig {
  const p = isRecord(raw) ? raw : {};
  return {
    ...DEFAULT_PROVIDER,
    ...p,
    max_tokens:
      typeof p.max_tokens === "number" ? p.max_tokens : DEFAULT_PROVIDER.max_tokens,
    temperature:
      typeof p.temperature === "number" ? p.temperature : DEFAULT_PROVIDER.temperature,
  };
}

function mergeTests(raw: unknown): TestsConfig {
  const t = isRecord(raw) ? raw : {};
  const cov = isRecord(t.coverage) ? t.coverage : {};
  return {
    ...DEFAULT_TESTS,
    ...t,
    command: typeof t.command === "string" ? t.command : DEFAULT_TESTS.command,
    timeout: typeof t.timeout === "number" ? t.timeout : DEFAULT_TESTS.timeout,
    coverage: {
      ...DEFAULT_TESTS.coverage,
      ...cov,
      enabled: toBool(cov.enabled, DEFAULT_TESTS.coverage.enabled),
      command:
        typeof cov.command === "string" ? cov.command : DEFAULT_TESTS.coverage.command,
      target:
        typeof cov.target === "number" ? cov.target : DEFAULT_TESTS.coverage.target,
    },
  };
}

function mergeBenchmarks(raw: unknown): BenchmarksConfig {
  const b = isRecord(raw) ? raw : {};
  return {
    ...DEFAULT_BENCHMARKS,
    ...b,
    enabled: toBool(b.enabled, DEFAULT_BENCHMARKS.enabled),
    regression_threshold:
      typeof b.regression_threshold === "number"
        ? b.regression_threshold
        : DEFAULT_BENCHMARKS.regression_threshold,
    run_every:
      typeof b.run_every === "number" ? b.run_every : DEFAULT_BENCHMARKS.run_every,
  };
}

function mergeTasks(raw: unknown): TasksConfig {
  const t = isRecord(raw) ? raw : {};
  const mode = t.priority_mode;
  return {
    ...DEFAULT_TASKS,
    ...t,
    priorities: Array.isArray(t.priorities)
      ? (t.priorities as string[])
      : DEFAULT_TASKS.priorities,
    custom: Array.isArray(t.custom) ? (t.custom as TasksConfig["custom"]) : [],
    instructions:
      isRecord(t.instructions) ? (t.instructions as Record<string, string>) : {},
    priority_mode:
      mode === "engineer" || mode === "improver" ? mode : "improver",
  };
}

function mergeGoals(raw: unknown): GoalsConfig {
  const g = isRecord(raw) ? raw : {};
  const current = Array.isArray(g.current) ? g.current : DEFAULT_GOALS.current;
  return {
    current: current.map((item: unknown) => {
      const i = isRecord(item) ? item : {};
      return {
        id: typeof i.id === "string" ? i.id : "",
        description: typeof i.description === "string" ? i.description : "",
        priority: typeof i.priority === "number" ? i.priority : 1,
        context_files: Array.isArray(i.context_files)
          ? (i.context_files as string[])
          : [],
        context_docs: Array.isArray(i.context_docs)
          ? (i.context_docs as string[])
          : [],
        issue_ref:
          typeof i.issue_ref === "string" ? i.issue_ref : null,
      };
    }),
  };
}

function mergeWorkSources(raw: unknown): WorkSourcesConfig {
  const w = isRecord(raw) ? raw : {};
  const gh = isRecord(w.github_issues) ? w.github_issues : DEFAULT_WORK_SOURCES.github_issues;
  return {
    github_issues: {
      ...DEFAULT_GITHUB_ISSUES,
      ...gh,
      enabled: toBool(gh.enabled, DEFAULT_GITHUB_ISSUES.enabled),
      repos: Array.isArray(gh.repos) ? (gh.repos as string[]) : [],
      labels_include: Array.isArray(gh.labels_include)
        ? (gh.labels_include as string[])
        : [],
      labels_exclude: Array.isArray(gh.labels_exclude)
        ? (gh.labels_exclude as string[])
        : DEFAULT_GITHUB_ISSUES.labels_exclude,
      max_tasks:
        typeof gh.max_tasks === "number"
          ? gh.max_tasks
          : DEFAULT_GITHUB_ISSUES.max_tasks,
      poll_interval:
        typeof gh.poll_interval === "number"
          ? gh.poll_interval
          : DEFAULT_GITHUB_ISSUES.poll_interval,
    },
    prd_paths: Array.isArray(w.prd_paths) ? (w.prd_paths as string[]) : [],
    context_documents: Array.isArray(w.context_documents)
      ? (w.context_documents as string[])
      : [],
  };
}

/**
 * Match legacy Settings normalization for controls (null caps, defaults).
 */
export function normalizeControlsForUi(controls: ControlsConfig): ControlsConfig {
  const d = controls;
  return {
    ...d,
    max_iterations_total:
      d.max_iterations_total === undefined ? null : d.max_iterations_total,
    sleep_after_failure: d.sleep_after_failure ?? 60,
    min_improvement_threshold: d.min_improvement_threshold ?? 0.1,
    commit_prefix: d.commit_prefix ?? "vigil",
    require_test_pass: d.require_test_pass ?? true,
    stop_on_llm_error: d.stop_on_llm_error ?? true,
    max_files_per_iteration:
      d.max_files_per_iteration === undefined ? 5 : d.max_files_per_iteration,
    max_lines_changed:
      d.max_lines_changed === undefined ? 200 : d.max_lines_changed,
  };
}

function mergeControls(raw: unknown): ControlsConfig {
  const c = isRecord(raw) ? raw : {};
  const base: ControlsConfig = {
    ...DEFAULT_CONTROLS_BASE,
    ...c,
    stop_on_llm_error: toBool(c.stop_on_llm_error, DEFAULT_CONTROLS_BASE.stop_on_llm_error),
    require_test_pass: toBool(c.require_test_pass, DEFAULT_CONTROLS_BASE.require_test_pass),
    auto_commit: toBool(c.auto_commit, DEFAULT_CONTROLS_BASE.auto_commit),
    pause_on_battery: toBool(c.pause_on_battery, DEFAULT_CONTROLS_BASE.pause_on_battery),
    dry_run: toBool(c.dry_run, DEFAULT_CONTROLS_BASE.dry_run),
  };
  return normalizeControlsForUi(base);
}

function mergePr(raw: unknown): PRConfig {
  const p = isRecord(raw) ? raw : {};
  return {
    ...DEFAULT_PR,
    ...p,
    enabled: toBool(p.enabled, DEFAULT_PR.enabled),
    auto_push: toBool(p.auto_push, DEFAULT_PR.auto_push),
    use_llm_description: toBool(
      p.use_llm_description,
      DEFAULT_PR.use_llm_description,
    ),
    labels: Array.isArray(p.labels) ? (p.labels as string[]) : DEFAULT_PR.labels,
    reviewers: Array.isArray(p.reviewers)
      ? (p.reviewers as string[])
      : DEFAULT_PR.reviewers,
  };
}

/** Last-line defense: never leave list fields undefined (Settings uses .length / .join). */
function enforceArrayFields(c: VigilConfig): VigilConfig {
  return {
    ...c,
    project: {
      ...c.project,
      include_paths: Array.isArray(c.project.include_paths)
        ? c.project.include_paths
        : DEFAULT_PROJECT.include_paths,
      exclude_paths: Array.isArray(c.project.exclude_paths)
        ? c.project.exclude_paths
        : DEFAULT_PROJECT.exclude_paths,
    },
    tasks: {
      ...c.tasks,
      priorities: Array.isArray(c.tasks.priorities)
        ? c.tasks.priorities
        : DEFAULT_TASKS.priorities,
      custom: Array.isArray(c.tasks.custom) ? c.tasks.custom : [],
    },
    pr: {
      ...c.pr,
      labels: Array.isArray(c.pr.labels) ? c.pr.labels : DEFAULT_PR.labels,
      reviewers: Array.isArray(c.pr.reviewers) ? c.pr.reviewers : DEFAULT_PR.reviewers,
    },
    goals: {
      ...c.goals,
      current: Array.isArray(c.goals.current) ? c.goals.current : [],
    },
    work_sources: {
      ...c.work_sources,
      github_issues: {
        ...c.work_sources.github_issues,
        repos: Array.isArray(c.work_sources.github_issues.repos)
          ? c.work_sources.github_issues.repos
          : [],
        labels_include: Array.isArray(c.work_sources.github_issues.labels_include)
          ? c.work_sources.github_issues.labels_include
          : [],
        labels_exclude: Array.isArray(c.work_sources.github_issues.labels_exclude)
          ? c.work_sources.github_issues.labels_exclude
          : DEFAULT_GITHUB_ISSUES.labels_exclude,
      },
      prd_paths: Array.isArray(c.work_sources.prd_paths)
        ? c.work_sources.prd_paths
        : [],
      context_documents: Array.isArray(c.work_sources.context_documents)
        ? c.work_sources.context_documents
        : [],
    },
  };
}

/**
 * Merge API / partial JSON into a full VigilConfig safe for Settings UI.
 * Avoids crashes when the backend omits sections or returns minimal payloads.
 */
export function mergeVigilConfigFromApi(raw: unknown): VigilConfig {
  const r = isRecord(raw) ? raw : {};
  return enforceArrayFields({
    project: mergeProject(r.project),
    provider: mergeProvider(r.provider),
    tests: mergeTests(r.tests),
    benchmarks: mergeBenchmarks(r.benchmarks),
    tasks: mergeTasks(r.tasks),
    controls: mergeControls(r.controls),
    pr: mergePr(r.pr),
    goals: mergeGoals(r.goals),
    work_sources: mergeWorkSources(r.work_sources),
  });
}
