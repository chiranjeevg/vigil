import { useState, useEffect } from "react";
import {
  Save,
  RotateCcw,
  FolderOpen,
  Cpu,
  TestTube,
  BarChart3,
  SlidersHorizontal,
  ChevronDown,
  ChevronRight,
  Loader2,
  GitPullRequest,
  ArrowLeftRight,
  Sun,
  Moon,
  Monitor,
} from "lucide-react";
import clsx from "clsx";
import { useTheme, type ThemePreference } from "@/context/ThemeContext";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";
import {
  pathsEqual,
  type VigilProjectListItem,
} from "@/lib/pathUtils";
import type { PRConfig, VigilConfig } from "@/types";

const DEFAULT_PR: PRConfig = {
  enabled: false,
  strategy: "per_iteration",
  base_branch: "main",
  auto_push: false,
  labels: [],
  reviewers: [],
  use_llm_description: false,
};

function withNormalizedPr(config: VigilConfig): VigilConfig {
  const c = structuredClone(config);
  c.pr = { ...DEFAULT_PR, ...c.pr };
  const d = c.controls;
  c.controls = {
    ...d,
    max_iterations_total:
      d.max_iterations_total === undefined ? null : d.max_iterations_total,
    sleep_after_failure: d.sleep_after_failure ?? 60,
    min_improvement_threshold: d.min_improvement_threshold ?? 0.1,
    commit_prefix: d.commit_prefix ?? "vigil",
    require_test_pass: d.require_test_pass ?? true,
  };
  return c;
}

interface LLMModel {
  name: string;
  provider: string;
  size_gb: number | null;
  family: string;
  parameter_size: string;
}

function Section({
  title,
  icon: Icon,
  children,
  defaultOpen = true,
}: {
  title: string;
  icon: typeof FolderOpen;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-xl border border-slate-200 bg-white/90 dark:border-slate-700/50 dark:bg-slate-800/50">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 px-6 py-4 text-left transition-colors hover:bg-slate-100 dark:hover:bg-slate-800/70"
      >
        <Icon className="h-5 w-5 text-blue-600 dark:text-blue-400" />
        <span className="flex-1 text-base font-semibold text-slate-900 dark:text-white">
          {title}
        </span>
        {open ? (
          <ChevronDown className="h-4 w-4 text-slate-500" />
        ) : (
          <ChevronRight className="h-4 w-4 text-slate-500" />
        )}
      </button>
      {open && (
        <div className="border-t border-slate-200 px-6 py-5 dark:border-slate-700/50">
          {children}
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
        {label}
      </label>
      {children}
    </div>
  );
}

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-500 transition-colors focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:placeholder-slate-500";

const selectClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 transition-colors focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white";

const themeOptions: {
  value: ThemePreference;
  label: string;
  icon: typeof Sun;
}[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "auto", label: "Auto", icon: Monitor },
];

export function Settings() {
  const { preference: themePreference, setPreference: setThemePreference } =
    useTheme();
  const { data: daemonStatus, refetch: refetchStatus } = usePolling(
    () => api.getStatus(),
    5000,
  );
  const [projects, setProjects] = useState<VigilProjectListItem[]>([]);
  /** Empty string = active daemon's config (GET /config). Non-empty = that path's vigil.yaml. */
  const [settingsProjectPath, setSettingsProjectPath] = useState("");
  const [draft, setDraft] = useState<VigilConfig | null>(null);
  const [configLoading, setConfigLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [availableModels, setAvailableModels] = useState<LLMModel[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);

  useEffect(() => {
    api.getVigilProjects().then((r) => setProjects(r.projects || []));
  }, []);

  useEffect(() => {
    setConfigLoading(true);
    const fetcher = settingsProjectPath
      ? api.getConfigByProject(settingsProjectPath)
      : api.getConfig();

    fetcher
      .then((cfg) => {
        setDraft(withNormalizedPr(cfg as VigilConfig));
      })
      .catch(() => {
        setDraft(null);
      })
      .finally(() => setConfigLoading(false));
  }, [settingsProjectPath]);

  useEffect(() => {
    setLoadingModels(true);
    api.getModels()
      .then((data) => setAvailableModels(data.models))
      .catch(() => {})
      .finally(() => setLoadingModels(false));
  }, []);

  function update<K extends keyof VigilConfig>(
    section: K,
    key: keyof VigilConfig[K],
    value: VigilConfig[K][typeof key],
  ) {
    setDraft((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        [section]: { ...prev[section], [key]: value },
      };
    });
  }

  async function handleSave() {
    if (!draft) return;
    setSaving(true);
    try {
      const targetIsActive =
        !settingsProjectPath ||
        pathsEqual(settingsProjectPath, daemonStatus?.project_path);
      if (targetIsActive) {
        await api.updateConfig(draft);
      } else {
        await api.updateConfigByProject(settingsProjectPath, draft);
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      void refetchStatus();
    } catch {
      // silently handle
    } finally {
      setSaving(false);
    }
  }

  async function handleSwitchDaemonToSelection() {
    if (!settingsProjectPath) return;
    setSwitching(true);
    try {
      await api.switchProject(settingsProjectPath);
      await refetchStatus();
    } catch {
      /* ignore */
    } finally {
      setSwitching(false);
    }
  }

  function handleReset() {
    const fetcher = settingsProjectPath
      ? api.getConfigByProject(settingsProjectPath)
      : api.getConfig();
    void fetcher
      .then((cfg) => setDraft(withNormalizedPr(cfg as VigilConfig)))
      .catch(() => {});
  }

  const editingLabel = settingsProjectPath
    ? projects.find((p) => p.path === settingsProjectPath)?.name ??
      draft?.project?.name ??
      "Project"
    : daemonStatus?.project_name ?? draft?.project?.name ?? "Active project";

  const selectionIsActive =
    !settingsProjectPath ||
    pathsEqual(settingsProjectPath, daemonStatus?.project_path);

  if (configLoading || !draft) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-200 bg-white/90 p-5 dark:border-slate-700/50 dark:bg-slate-800/50">
        <div className="mb-3 flex items-center gap-2">
          <Monitor className="h-5 w-5 text-blue-600 dark:text-blue-400" />
          <h2 className="text-base font-semibold text-slate-900 dark:text-white">
            Appearance
          </h2>
        </div>
        <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
          Choose how the dashboard looks. Auto follows your system light or dark mode.
        </p>
        <div className="flex flex-wrap gap-2">
          {themeOptions.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              type="button"
              onClick={() => setThemePreference(value)}
              className={clsx(
                "inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
                themePreference === value
                  ? "border-blue-500 bg-blue-500/10 text-blue-800 dark:text-blue-300"
                  : "border-slate-200 bg-slate-50 text-slate-800 hover:border-slate-300 dark:border-slate-600 dark:bg-slate-900/40 dark:text-slate-300 dark:hover:border-slate-500",
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Settings</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Per-project <code className="rounded bg-slate-200 px-1.5 py-0.5 font-mono text-xs text-slate-800 dark:bg-slate-800 dark:text-slate-200">vigil.yaml</code>{" "}
            — choose a project, edit, then save. Use &quot;Switch daemon&quot; so Start/Stop runs on that repo.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {projects.length > 0 && (
            <div className="relative min-w-[220px]">
              <FolderOpen className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
              <select
                value={settingsProjectPath}
                onChange={(e) => setSettingsProjectPath(e.target.value)}
                className="w-full appearance-none rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-8 text-xs font-medium text-slate-800 outline-none transition-colors hover:border-slate-400 focus:border-blue-500 dark:border-slate-700/50 dark:bg-slate-800/50 dark:text-slate-300 dark:hover:border-slate-600"
              >
                <option value="">
                  Active daemon — {daemonStatus?.project_name ?? "loading…"}
                </option>
                {projects.map((p) => (
                  <option key={p.path} value={p.path}>
                    {p.name}
                    {pathsEqual(p.path, daemonStatus?.project_path) ? " (active)" : ""}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
            </div>
          )}
          {settingsProjectPath && !selectionIsActive && (
            <button
              type="button"
              onClick={() => void handleSwitchDaemonToSelection()}
              disabled={switching}
              className="inline-flex items-center gap-2 rounded-lg border border-cyan-500/40 bg-cyan-50 px-3 py-2 text-xs font-medium text-cyan-900 transition-colors hover:bg-cyan-100 disabled:opacity-50 dark:border-cyan-600/50 dark:bg-cyan-950/40 dark:text-cyan-200 dark:hover:bg-cyan-900/50"
            >
              {switching ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <ArrowLeftRight className="h-3.5 w-3.5" />
              )}
              Switch daemon here
            </button>
          )}
          <button
            type="button"
            onClick={handleReset}
            className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-slate-700 transition-all duration-200 hover:bg-slate-200 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-700/50 dark:hover:text-white"
          >
            <RotateCcw className="h-4 w-4" />
            Reset
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving}
            className={clsx(
              "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200",
              saved
                ? "bg-green-600 text-white"
                : "bg-blue-600 text-white hover:bg-blue-500",
            )}
          >
            <Save className="h-4 w-4" />
            {saved ? "Saved!" : saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>

      {settingsProjectPath && !selectionIsActive && (
        <div className="rounded-xl border border-amber-400/40 bg-amber-50 px-4 py-3 text-sm text-amber-950 dark:border-amber-500/25 dark:bg-amber-500/5 dark:text-amber-100/95">
          Editing settings for <strong>{editingLabel}</strong>. The running daemon is still on{" "}
          <strong>{daemonStatus?.project_name ?? "…"}</strong> (
          <code className="text-xs text-amber-900 dark:text-amber-200/90">{daemonStatus?.project_path}</code>). Save writes this
          project&apos;s <code className="text-xs">vigil.yaml</code>. Use &quot;Switch daemon here&quot; before
          Start if you want iterations to run in <strong>{editingLabel}</strong>.
        </div>
      )}

      <Section title="Project" icon={FolderOpen}>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Project Name">
            <input
              type="text"
              value={draft.project.name}
              onChange={(e) => update("project", "name", e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Language">
            <input
              type="text"
              value={draft.project.language}
              onChange={(e) => update("project", "language", e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Path">
            <input
              type="text"
              value={draft.project.path}
              onChange={(e) => update("project", "path", e.target.value)}
              className={clsx(inputClass, "font-mono")}
            />
          </Field>
          <div />
          <Field label="Include Paths">
            <input
              type="text"
              value={draft.project.include_paths.join(", ")}
              onChange={(e) =>
                update(
                  "project",
                  "include_paths",
                  e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                )
              }
              placeholder="src/, lib/"
              className={clsx(inputClass, "font-mono")}
            />
          </Field>
          <Field label="Exclude Paths">
            <input
              type="text"
              value={draft.project.exclude_paths.join(", ")}
              onChange={(e) =>
                update(
                  "project",
                  "exclude_paths",
                  e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                )
              }
              placeholder="node_modules/, .git/"
              className={clsx(inputClass, "font-mono")}
            />
          </Field>
        </div>
      </Section>

      <Section title="Provider" icon={Cpu}>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Type">
            <select
              value={draft.provider.type}
              onChange={(e) => update("provider", "type", e.target.value)}
              className={selectClass}
            >
              <option value="ollama">Ollama</option>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="openrouter">OpenRouter</option>
              <option value="custom">Custom</option>
            </select>
          </Field>
          <Field label="Model">
            {loadingModels ? (
              <div className="flex items-center gap-2 py-2">
                <Loader2 className="h-4 w-4 animate-spin text-blue-600 dark:text-blue-400" />
                <span className="text-sm text-slate-600 dark:text-slate-400">Detecting models...</span>
              </div>
            ) : availableModels.length > 0 ? (
              <div className="space-y-2">
                <select
                  value={draft.provider.model}
                  onChange={(e) => update("provider", "model", e.target.value)}
                  className={selectClass}
                >
                  {!availableModels.some((m) => m.name === draft.provider.model) && (
                    <option value={draft.provider.model}>{draft.provider.model} (current)</option>
                  )}
                  {availableModels.map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.name}{m.parameter_size ? ` (${m.parameter_size})` : ""}{m.size_gb ? ` — ${m.size_gb}GB` : ""}
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <input
                type="text"
                value={draft.provider.model}
                onChange={(e) => update("provider", "model", e.target.value)}
                placeholder="e.g. qwen2.5-coder:14b"
                className={clsx(inputClass, "font-mono")}
              />
            )}
          </Field>
          <Field label="Base URL">
            <input
              type="text"
              value={draft.provider.base_url}
              onChange={(e) => update("provider", "base_url", e.target.value)}
              className={clsx(inputClass, "font-mono")}
            />
          </Field>
          <Field label="Max Tokens">
            <input
              type="number"
              value={draft.provider.max_tokens}
              onChange={(e) =>
                update("provider", "max_tokens", Number(e.target.value))
              }
              className={inputClass}
            />
          </Field>
          <Field label={`Temperature: ${draft.provider.temperature}`}>
            <input
              type="range"
              min="0"
              max="2"
              step="0.1"
              value={draft.provider.temperature}
              onChange={(e) =>
                update("provider", "temperature", Number(e.target.value))
              }
              className="w-full accent-blue-500"
            />
          </Field>
        </div>
      </Section>

      <Section title="Tests" icon={TestTube}>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Test Command">
            <input
              type="text"
              value={draft.tests.command}
              onChange={(e) => update("tests", "command", e.target.value)}
              placeholder="npm test"
              className={clsx(inputClass, "font-mono")}
            />
          </Field>
          <Field label="Timeout (seconds)">
            <input
              type="number"
              value={draft.tests.timeout}
              onChange={(e) =>
                update("tests", "timeout", Number(e.target.value))
              }
              className={inputClass}
            />
          </Field>
          <Field label="Coverage Enabled">
            <button
              onClick={() =>
                setDraft((prev) =>
                  prev
                    ? {
                        ...prev,
                        tests: {
                          ...prev.tests,
                          coverage: {
                            ...prev.tests.coverage,
                            enabled: !prev.tests.coverage.enabled,
                          },
                        },
                      }
                    : prev,
                )
              }
              className={clsx(
                "rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200",
                draft.tests.coverage.enabled
                  ? "bg-green-600/15 text-green-800 dark:bg-green-600/20 dark:text-green-400"
                  : "bg-slate-200 text-slate-600 dark:bg-slate-700/50 dark:text-slate-400",
              )}
            >
              {draft.tests.coverage.enabled ? "Enabled" : "Disabled"}
            </button>
          </Field>
          {draft.tests.coverage.enabled && (
            <>
              <Field label="Coverage Command">
                <input
                  type="text"
                  value={draft.tests.coverage.command}
                  onChange={(e) =>
                    setDraft((prev) =>
                      prev
                        ? {
                            ...prev,
                            tests: {
                              ...prev.tests,
                              coverage: {
                                ...prev.tests.coverage,
                                command: e.target.value,
                              },
                            },
                          }
                        : prev,
                    )
                  }
                  className={clsx(inputClass, "font-mono")}
                />
              </Field>
              <Field label="Coverage Target (%)">
                <input
                  type="number"
                  value={draft.tests.coverage.target}
                  onChange={(e) =>
                    setDraft((prev) =>
                      prev
                        ? {
                            ...prev,
                            tests: {
                              ...prev.tests,
                              coverage: {
                                ...prev.tests.coverage,
                                target: Number(e.target.value),
                              },
                            },
                          }
                        : prev,
                    )
                  }
                  className={inputClass}
                />
              </Field>
            </>
          )}
        </div>
      </Section>

      <Section title="Benchmarks" icon={BarChart3} defaultOpen={false}>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Enabled">
            <button
              onClick={() =>
                update("benchmarks", "enabled", !draft.benchmarks.enabled)
              }
              className={clsx(
                "rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200",
                draft.benchmarks.enabled
                  ? "bg-green-600/15 text-green-800 dark:bg-green-600/20 dark:text-green-400"
                  : "bg-slate-200 text-slate-600 dark:bg-slate-700/50 dark:text-slate-400",
              )}
            >
              {draft.benchmarks.enabled ? "Enabled" : "Disabled"}
            </button>
          </Field>
          {draft.benchmarks.enabled && (
            <>
              <Field label="Command">
                <input
                  type="text"
                  value={draft.benchmarks.command}
                  onChange={(e) =>
                    update("benchmarks", "command", e.target.value)
                  }
                  className={clsx(inputClass, "font-mono")}
                />
              </Field>
              <Field label="Timeout (seconds)">
                <input
                  type="number"
                  value={draft.benchmarks.timeout}
                  onChange={(e) =>
                    update("benchmarks", "timeout", Number(e.target.value))
                  }
                  className={inputClass}
                />
              </Field>
              <Field label="Regression Threshold (%)">
                <input
                  type="number"
                  step="0.1"
                  value={draft.benchmarks.regression_threshold}
                  onChange={(e) =>
                    update(
                      "benchmarks",
                      "regression_threshold",
                      Number(e.target.value),
                    )
                  }
                  className={inputClass}
                />
              </Field>
              <Field label="Run Every N Iterations">
                <input
                  type="number"
                  value={draft.benchmarks.run_every}
                  onChange={(e) =>
                    update("benchmarks", "run_every", Number(e.target.value))
                  }
                  className={inputClass}
                />
              </Field>
            </>
          )}
        </div>
      </Section>

      <Section title="Git & iteration controls" icon={SlidersHorizontal} defaultOpen>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Max Iterations Per Day">
            <input
              type="number"
              value={draft.controls.max_iterations_per_day}
              onChange={(e) =>
                update(
                  "controls",
                  "max_iterations_per_day",
                  Number(e.target.value),
                )
              }
              className={inputClass}
            />
          </Field>
          <Field label="Sleep Between Iterations (seconds)">
            <input
              type="number"
              value={draft.controls.sleep_between_iterations}
              onChange={(e) =>
                update(
                  "controls",
                  "sleep_between_iterations",
                  Number(e.target.value),
                )
              }
              className={inputClass}
            />
          </Field>
          <Field label="Max Consecutive No Improvement">
            <input
              type="number"
              value={draft.controls.max_consecutive_no_improvement}
              onChange={(e) =>
                update(
                  "controls",
                  "max_consecutive_no_improvement",
                  Number(e.target.value),
                )
              }
              className={inputClass}
            />
          </Field>
          <Field label="Work branch">
            <input
              type="text"
              value={draft.controls.work_branch}
              onChange={(e) =>
                update("controls", "work_branch", e.target.value)
              }
              className={clsx(inputClass, "font-mono")}
            />
            <p className="mt-1 text-xs text-slate-500">
              Base branch Vigil returns to between iterations; iteration branches are created from here.
            </p>
          </Field>
          <Field label="Commit message prefix">
            <input
              type="text"
              value={draft.controls.commit_prefix}
              onChange={(e) =>
                update("controls", "commit_prefix", e.target.value)
              }
              className={clsx(inputClass, "font-mono")}
              placeholder="vigil"
            />
          </Field>
          <Field label="Max iterations total (empty = unlimited)">
            <input
              type="number"
              min={1}
              value={draft.controls.max_iterations_total ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                update(
                  "controls",
                  "max_iterations_total",
                  v === "" ? null : Number(v),
                );
              }}
              className={inputClass}
              placeholder="Unlimited"
            />
          </Field>
          <Field label="Sleep after failure (seconds)">
            <input
              type="number"
              value={draft.controls.sleep_after_failure}
              onChange={(e) =>
                update(
                  "controls",
                  "sleep_after_failure",
                  Number(e.target.value),
                )
              }
              className={inputClass}
            />
          </Field>
          <Field label={`Min improvement threshold (${draft.controls.min_improvement_threshold})`}>
            <input
              type="number"
              step="0.05"
              min={0}
              max={1}
              value={draft.controls.min_improvement_threshold}
              onChange={(e) =>
                update(
                  "controls",
                  "min_improvement_threshold",
                  Number(e.target.value),
                )
              }
              className={inputClass}
            />
          </Field>
          <Field label="Max Files Per Iteration">
            <input
              type="number"
              value={draft.controls.max_files_per_iteration}
              onChange={(e) =>
                update(
                  "controls",
                  "max_files_per_iteration",
                  Number(e.target.value),
                )
              }
              className={inputClass}
            />
          </Field>
          <Field label="Max Lines Changed">
            <input
              type="number"
              value={draft.controls.max_lines_changed}
              onChange={(e) =>
                update(
                  "controls",
                  "max_lines_changed",
                  Number(e.target.value),
                )
              }
              className={inputClass}
            />
          </Field>

          <div className="col-span-full grid grid-cols-2 gap-4 md:grid-cols-4">
            {(
              [
                ["auto_commit", "Auto commit"],
                ["require_test_pass", "Require tests to pass"],
                ["pause_on_battery", "Pause on battery"],
                ["dry_run", "Dry run"],
              ] as const
            ).map(([key, label]) => (
              <Field key={key} label={label}>
                <button
                  onClick={() =>
                    update("controls", key, !draft.controls[key])
                  }
                  className={clsx(
                    "rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200",
                    draft.controls[key]
                      ? "bg-green-600/15 text-green-800 dark:bg-green-600/20 dark:text-green-400"
                      : "bg-slate-200 text-slate-600 dark:bg-slate-700/50 dark:text-slate-400",
                  )}
                >
                  {draft.controls[key] ? "On" : "Off"}
                </button>
              </Field>
            ))}
          </div>
        </div>
      </Section>

      <Section title="Pull requests (Git branch / PR)" icon={GitPullRequest} defaultOpen>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Enable PR Workflow">
            <button
              onClick={() => update("pr", "enabled", !draft.pr.enabled)}
              className={clsx(
                "rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200",
                draft.pr.enabled
                  ? "bg-green-600/15 text-green-800 dark:bg-green-600/20 dark:text-green-400"
                  : "bg-slate-200 text-slate-600 dark:bg-slate-700/50 dark:text-slate-400",
              )}
            >
              {draft.pr.enabled ? "Enabled" : "Disabled"}
            </button>
          </Field>
          <Field label="Use LLM for PR Description">
            <button
              onClick={() =>
                update("pr", "use_llm_description", !draft.pr.use_llm_description)
              }
              className={clsx(
                "rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200",
                draft.pr.use_llm_description
                  ? "bg-green-600/15 text-green-800 dark:bg-green-600/20 dark:text-green-400"
                  : "bg-slate-200 text-slate-600 dark:bg-slate-700/50 dark:text-slate-400",
              )}
            >
              {draft.pr.use_llm_description ? "LLM Generated" : "Static Template"}
            </button>
          </Field>
          {draft.pr.enabled && (
            <>
              <Field label="Base Branch">
                <input
                  type="text"
                  value={draft.pr.base_branch}
                  onChange={(e) => update("pr", "base_branch", e.target.value)}
                  placeholder="main"
                  className={clsx(inputClass, "font-mono")}
                />
              </Field>
              <Field label="Strategy">
                <select
                  value={draft.pr.strategy}
                  onChange={(e) => update("pr", "strategy", e.target.value)}
                  className={selectClass}
                >
                  <option value="per_iteration">Per Iteration</option>
                </select>
              </Field>
              <Field label="Labels (comma-separated)">
                <input
                  type="text"
                  value={draft.pr.labels.join(", ")}
                  onChange={(e) =>
                    update(
                      "pr",
                      "labels",
                      e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                    )
                  }
                  placeholder="vigil, automated"
                  className={clsx(inputClass, "font-mono")}
                />
              </Field>
              <Field label="Reviewers (comma-separated)">
                <input
                  type="text"
                  value={draft.pr.reviewers.join(", ")}
                  onChange={(e) =>
                    update(
                      "pr",
                      "reviewers",
                      e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                    )
                  }
                  placeholder="username1, username2"
                  className={clsx(inputClass, "font-mono")}
                />
              </Field>
              <Field label="Auto Push">
                <button
                  onClick={() =>
                    update("pr", "auto_push", !draft.pr.auto_push)
                  }
                  className={clsx(
                    "rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200",
                    draft.pr.auto_push
                      ? "bg-green-600/15 text-green-800 dark:bg-green-600/20 dark:text-green-400"
                      : "bg-slate-200 text-slate-600 dark:bg-slate-700/50 dark:text-slate-400",
                  )}
                >
                  {draft.pr.auto_push ? "On" : "Off"}
                </button>
              </Field>
            </>
          )}
        </div>
        {draft.pr.enabled && (
          <div className="mt-4 rounded-lg border border-amber-400/35 bg-amber-50 px-4 py-3 dark:border-amber-500/20 dark:bg-amber-500/5">
            <p className="text-sm text-amber-900 dark:text-amber-400">
              Requires GitHub CLI (<code className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-xs dark:bg-slate-800">gh</code>) to be installed and authenticated.
              The project must have a git remote configured.
            </p>
          </div>
        )}
      </Section>
    </div>
  );
}
