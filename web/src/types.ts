export interface VigilStatus {
  running: boolean;
  paused: boolean;
  iteration: number;
  current_task: Task | null;
  daily_count: number;
  no_improve_streak: number;
  uptime_seconds: number;
  provider: string;
  branch: string;
  project_name?: string;
  project_path?: string;
  /** controls.work_branch — merge-queue target */
  merge_branch?: string;
  merge_queue_head?: string;
}

export interface Task {
  type: string;
  description: string;
  target_files?: string[];
  instructions?: string;
}

export type IterationStatus =
  | "success"
  | "merge_conflict"
  | "no_changes"
  | "tests_failed"
  | "benchmark_regression"
  | "safety_revert"
  | "llm_error"
  | "config_error"
  | "worktree_error"
  | "dry_run";

export interface IterationStep {
  label: string;
  ts: string;
  duration_ms: number;
  detail: string | Record<string, unknown> | null;
  status?: "running" | "done";
}

export interface Iteration {
  iteration: number;
  task_type: string;
  task_description: string;
  status: IterationStatus;
  benchmark_data: Record<string, unknown>;
  summary: string;
  timestamp: string;
  duration_ms?: number;
  steps?: IterationStep[];
  files_changed?: string[];
  diff?: string;
  commit_hash?: string;
  llm_response?: string;
  llm_prompt_system?: string;
  llm_prompt_user?: string;
  llm_tokens?: number;
  llm_duration_s?: number;
  changes_detail?: { file: string; action: string; lines_changed?: number }[];
  test_output?: string;
  step_count?: number;
  branch_name?: string;
  provider_name?: string;
  provider?: string;
  branch?: string;
  elapsed_ms?: number;
  started_at?: string;
}

export interface BenchmarkEntry {
  iteration: number;
  timestamp: string;
  results: Record<string, number>;
  delta_pct?: number;
}

export interface VigilStats {
  total_iterations: number;
  successes: number;
  failures: number;
  success_rate: number;
  coverage_trend: number[];
  llm_tokens_total?: number;
  duration_ms_total?: number;
}

export interface IterationsPageResponse {
  iterations: Iteration[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface ProjectConfig {
  path: string;
  language: string;
  name: string;
  include_paths: string[];
  exclude_paths: string[];
}

export interface ProviderConfig {
  type: string;
  model: string;
  base_url: string;
  max_tokens: number;
  temperature: number;
}

export interface TestsConfig {
  command: string;
  timeout: number;
  coverage: {
    enabled: boolean;
    command: string;
    target: number;
  };
}

export interface BenchmarksConfig {
  enabled: boolean;
  command: string;
  timeout: number;
  regression_threshold: number;
  run_every: number;
}

export interface CustomTask {
  id: string;
  description: string;
  files: string[];
  priority: number;
}

export interface TasksConfig {
  priorities: string[];
  custom: CustomTask[];
  instructions: Record<string, string>;
  /** "improver" = original behaviour; "engineer" = work-source-driven forward work */
  priority_mode: "improver" | "engineer";
}

export interface GoalItem {
  id: string;
  description: string;
  /** 1 = most urgent, 5 = lowest */
  priority: number;
  context_files: string[];
  context_docs: string[];
  issue_ref: string | null;
}

export interface GoalsConfig {
  current: GoalItem[];
}

export interface GitHubIssuesConfig {
  enabled: boolean;
  repos: string[];
  labels_include: string[];
  labels_exclude: string[];
  max_tasks: number;
  poll_interval: number;
}

export interface WorkSourcesConfig {
  github_issues: GitHubIssuesConfig;
  prd_paths: string[];
  context_documents: string[];
}

export interface ControlsConfig {
  max_iterations_per_day: number;
  /** null = unlimited */
  max_iterations_total: number | null;
  sleep_between_iterations: number;
  sleep_after_failure: number;
  max_consecutive_no_improvement: number;
  /** If true, stop the daemon after a failed LLM call instead of retrying indefinitely. */
  stop_on_llm_error: boolean;
  min_improvement_threshold: number;
  /** Persistent branch Vigil uses between iterations (iteration branches are created from this). */
  work_branch: string;
  /** Prefix for auto-generated commit messages */
  commit_prefix: string;
  auto_commit: boolean;
  /** null = no limit on file count for that iteration */
  max_files_per_iteration: number | null;
  /** null = no limit on aggregate line metric for that iteration */
  max_lines_changed: number | null;
  require_test_pass: boolean;
  pause_on_battery: boolean;
  dry_run: boolean;
}

export interface PRConfig {
  enabled: boolean;
  strategy: string;
  base_branch: string;
  auto_push: boolean;
  labels: string[];
  reviewers: string[];
  use_llm_description: boolean;
}

/** GET /api/pr/status — live git / gh readiness for PR automation */
export interface PrStatusResponse {
  enabled: boolean;
  pr_active: boolean;
  push_enabled: boolean;
  gh_pr_enabled: boolean;
  strategy: string;
  base_branch: string;
  preflight_ok: boolean;
  preflight_message: string;
  /** HEAD of merge-queue worktree on work_branch (when available) */
  merge_queue_head?: string;
}

export interface VigilConfig {
  project: ProjectConfig;
  provider: ProviderConfig;
  tests: TestsConfig;
  benchmarks: BenchmarksConfig;
  tasks: TasksConfig;
  controls: ControlsConfig;
  pr: PRConfig;
  goals: GoalsConfig;
  work_sources: WorkSourcesConfig;
}

export interface SuggestedTask {
  type: string;
  label: string;
  description: string;
  reason: string;
  priority: number;
  enabled: boolean;
  instructions: string;
  category?: string;
  severity?: string;
  files?: string[];
  approach?: string;
  language_specific?: string;
  estimated_complexity?: string;
}

export interface WSEvent {
  type: string;
  data: unknown;
  timestamp: string;
}
