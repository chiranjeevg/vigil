import { useState, useEffect, useCallback, useRef } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Save,
  RotateCcw,
  RefreshCw,
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
  Target,
  Globe,
  Trash2,
  Plus,
  Network,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import clsx from "clsx";
import { useTheme, type ThemePreference } from "@/context/ThemeContext";
import { usePolling } from "@/hooks/usePolling";
import { api, ApiError } from "@/lib/api";
import {
  pathsEqual,
  type VigilProjectListItem,
} from "@/lib/pathUtils";
import { mergeVigilConfigFromApi } from "@/lib/vigilConfigMerge";
import { NewProjectLink } from "@/components/NewProjectLink";
import type { GoalItem, VigilConfig } from "@/types";

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
  id,
}: {
  title: string;
  icon: typeof FolderOpen;
  children: React.ReactNode;
  defaultOpen?: boolean;
  /** Anchor for deep links (e.g. Setup → Provider). */
  id?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div
      id={id}
      className="scroll-mt-24 rounded-xl border border-slate-200 bg-white/90 dark:border-slate-700/50 dark:bg-slate-800/50"
    >
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
  const location = useLocation();
  const continueSetupPath =
    (location.state as { returnTo?: string } | null)?.returnTo ?? null;

  const { preference: themePreference, setPreference: setThemePreference } =
    useTheme();
  const { data: daemonStatus, refetch: refetchStatus } = usePolling(
    () => api.getStatus(),
    5000,
  );
  const { data: prRuntime } = usePolling(() => api.getPrStatus(), 8000);
  const [projects, setProjects] = useState<VigilProjectListItem[]>([]);
  /** Empty string = active daemon's config (GET /config). Non-empty = that path's vigil.yaml. */
  const [settingsProjectPath, setSettingsProjectPath] = useState("");
  const [draft, setDraft] = useState<VigilConfig | null>(null);
  const [configLoading, setConfigLoading] = useState(true);
  const [configError, setConfigError] = useState<string | null>(null);
  const [loadRetryToken, setLoadRetryToken] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [availableModels, setAvailableModels] = useState<LLMModel[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [providerTestLoading, setProviderTestLoading] = useState(false);
  const [providerTestResult, setProviderTestResult] = useState<{
    latency_ms: number;
    preview: string;
    provider_name: string;
    tokens_used: number;
  } | null>(null);
  const [providerTestError, setProviderTestError] = useState<string | null>(null);

  const loadProjects = useCallback(() => {
    api.getVigilProjects().then((r) => setProjects(r.projects || []));
  }, []);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible") loadProjects();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [loadProjects]);

  useEffect(() => {
    setProviderTestResult(null);
    setProviderTestError(null);
  }, [settingsProjectPath]);

  useEffect(() => {
    let cancelled = false;
    setConfigLoading(true);
    setConfigError(null);
    const fetcher = settingsProjectPath
      ? api.getConfigByProject(settingsProjectPath)
      : api.getConfig();

    fetcher
      .then((cfg) => {
        if (cancelled) return;
        try {
          setDraft(mergeVigilConfigFromApi(cfg));
        } catch (e) {
          setDraft(null);
          setConfigError(
            e instanceof Error ? e.message : "Could not parse configuration",
          );
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setDraft(null);
        const msg =
          e instanceof Error
            ? e.message
            : typeof e === "object" && e !== null && "message" in e
              ? String((e as { message: unknown }).message)
              : "Failed to load configuration";
        setConfigError(msg);
      })
      .finally(() => {
        if (!cancelled) setConfigLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [settingsProjectPath, loadRetryToken]);

  useEffect(() => {
    if (configLoading || configError || !draft) return;
    if (window.location.hash !== "#settings-provider") return;
    const timer = window.setTimeout(() => {
      document
        .getElementById("settings-provider")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 150);
    return () => window.clearTimeout(timer);
  }, [configLoading, configError, draft]);

  const modelsFetchFirstRef = useRef(true);

  useEffect(() => {
    modelsFetchFirstRef.current = true;
  }, [settingsProjectPath]);

  const fetchModelsForProvider = useCallback((d: VigilConfig) => {
    setLoadingModels(true);
    const ptype = d.provider.type;
    let opts: { openaiBaseUrl?: string; ollamaBaseUrl?: string } | undefined;
    if (ptype === "openai" && d.provider.base_url?.trim()) {
      opts = { openaiBaseUrl: d.provider.base_url.trim() };
    } else if (ptype === "ollama" && d.provider.base_url?.trim()) {
      opts = { ollamaBaseUrl: d.provider.base_url.trim() };
    }
    return api
      .getModels(opts)
      .then((data) =>
        setAvailableModels(Array.isArray(data.models) ? data.models : []),
      )
      .catch(() => setAvailableModels([]))
      .finally(() => setLoadingModels(false));
  }, []);

  useEffect(() => {
    if (!draft) return;
    const d = draft;
    const delay = modelsFetchFirstRef.current ? 0 : 400;
    modelsFetchFirstRef.current = false;
    const timer = window.setTimeout(() => {
      void fetchModelsForProvider(d);
    }, delay);
    return () => window.clearTimeout(timer);
  }, [
    draft?.provider.type,
    draft?.provider.base_url,
    settingsProjectPath,
    fetchModelsForProvider,
  ]);

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

  /** Patch a single field of a goal entry at the given list index. */
  function updateGoal(idx: number, patch: Partial<GoalItem>) {
    setDraft((prev) => {
      if (!prev) return prev;
      const updated: GoalItem[] = prev.goals.current.map((g, i) =>
        i === idx ? ({ ...g, ...patch } as GoalItem) : g,
      );
      return { ...prev, goals: { ...prev.goals, current: updated } };
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
      .then((cfg) => {
        try {
          setDraft(mergeVigilConfigFromApi(cfg));
        } catch {
          /* ignore */
        }
      })
      .catch(() => {});
  }

  async function handleTestProvider() {
    if (!draft) return;
    setProviderTestLoading(true);
    setProviderTestError(null);
    setProviderTestResult(null);
    try {
      const r = await api.testProviderConnection(
        draft.provider as unknown as Record<string, unknown>,
      );
      setProviderTestResult({
        latency_ms: r.latency_ms,
        preview: r.preview,
        provider_name: r.provider_name,
        tokens_used: r.tokens_used,
      });
    } catch (e: unknown) {
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : "Connectivity test failed";
      setProviderTestError(msg);
    } finally {
      setProviderTestLoading(false);
    }
  }

  const editingLabel = settingsProjectPath
    ? projects.find((p) => p.path === settingsProjectPath)?.name ??
      draft?.project?.name ??
      "Project"
    : daemonStatus?.project_name ?? draft?.project?.name ?? "Active project";

  const selectionIsActive =
    !settingsProjectPath ||
    pathsEqual(settingsProjectPath, daemonStatus?.project_path);

  if (configLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
      </div>
    );
  }

  if (configError || !draft) {
    return (
      <div className="rounded-xl border border-red-300/60 bg-red-50/90 p-6 dark:border-red-900/50 dark:bg-red-950/30">
        <h2 className="text-lg font-semibold text-red-900 dark:text-red-200">
          Could not load settings
        </h2>
        <p className="mt-2 text-sm text-red-800/95 dark:text-red-300/90">
          {configError ?? "Configuration is unavailable. Check that Vigil is running and the API is reachable."}
        </p>
        <button
          type="button"
          onClick={() => {
            setLoadRetryToken((n) => n + 1);
          }}
          className="mt-4 inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-500"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {continueSetupPath && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-cyan-500/35 bg-cyan-500/5 px-4 py-3 dark:border-cyan-500/25 dark:bg-cyan-950/25">
          <p className="text-sm text-cyan-950 dark:text-cyan-100/95">
            After you <strong>Save</strong> provider (or other) changes, return to the new-project wizard to pick a
            folder and finish setup.
          </p>
          <Link
            to={continueSetupPath}
            className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-cyan-500 dark:bg-cyan-600 dark:hover:bg-cyan-500"
          >
            Continue setup
          </Link>
        </div>
      )}

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
            Per-project <code className="rounded bg-slate-200 px-1.5 py-0.5 font-mono text-xs text-slate-800 dark:bg-slate-800 dark:text-slate-200">vigil.yaml</code>
            — pick which repo to edit, then save. Use &quot;Switch daemon&quot; so Start/Stop runs on that
            repo. To register another codebase, use{" "}
            <span className="font-medium text-slate-800 dark:text-slate-200">New project</span> (setup
            wizard).
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <NewProjectLink fromSettings />
          <div className="relative min-w-[220px]">
            <FolderOpen className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
            <select
              value={settingsProjectPath}
              onChange={(e) => setSettingsProjectPath(e.target.value)}
              className="w-full appearance-none rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-8 text-xs font-medium text-slate-800 outline-none transition-colors hover:border-slate-400 focus:border-blue-500 dark:border-slate-700/50 dark:bg-slate-800/50 dark:text-slate-300 dark:hover:border-slate-600"
              aria-label="Project to edit"
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
              value={(draft.project.include_paths ?? []).join(", ")}
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
              value={(draft.project.exclude_paths ?? []).join(", ")}
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

      <Section id="settings-provider" title="Provider" icon={Cpu}>
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
            {draft.provider.type === "openai" && (
              <p className="mb-2 text-[11px] text-slate-500 dark:text-slate-400">
                With a base URL set, Vigil loads models from{" "}
                <code className="rounded bg-slate-200 px-1 font-mono text-[10px] dark:bg-slate-800">
                  /v1/models
                </code>{" "}
                (e.g. <code className="font-mono text-[10px]">curl -s http://localhost:4000/v1/models</code>
                ).
              </p>
            )}
            {loadingModels ? (
              <div className="flex items-center gap-2 py-2">
                <Loader2 className="h-4 w-4 animate-spin text-blue-600 dark:text-blue-400" />
                <span className="text-sm text-slate-600 dark:text-slate-400">Loading models…</span>
              </div>
            ) : (availableModels ?? []).length > 0 ? (
              <div className="space-y-2">
                <div className="flex flex-wrap items-stretch gap-2">
                  <select
                    value={draft.provider.model}
                    onChange={(e) => update("provider", "model", e.target.value)}
                    className={clsx(selectClass, "min-w-0 flex-1")}
                  >
                    {!(availableModels ?? []).some((m) => m.name === draft.provider.model) && (
                      <option value={draft.provider.model}>{draft.provider.model} (current)</option>
                    )}
                    {(availableModels ?? []).map((m) => (
                      <option key={`${m.provider}-${m.name}`} value={m.name}>
                        {m.name}
                        {m.provider === "openai" ? " (OpenAI-compatible)" : ""}
                        {m.parameter_size ? ` (${m.parameter_size})` : ""}
                        {m.size_gb ? ` — ${m.size_gb}GB` : ""}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    title="Refresh model list from server"
                    onClick={() => draft && void fetchModelsForProvider(draft)}
                    disabled={loadingModels}
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    Refresh
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <input
                  type="text"
                  value={draft.provider.model}
                  onChange={(e) => update("provider", "model", e.target.value)}
                  placeholder="e.g. gpt-4o-mini or qwen2.5-coder:14b"
                  className={clsx(inputClass, "font-mono")}
                />
                {(draft.provider.type === "openai" || draft.provider.type === "ollama") &&
                  draft.provider.base_url?.trim() && (
                    <button
                      type="button"
                      onClick={() => draft && void fetchModelsForProvider(draft)}
                      disabled={loadingModels}
                      className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-400"
                    >
                      <RefreshCw className="h-3 w-3" />
                      Try loading models from server
                    </button>
                  )}
              </div>
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
        <div className="mt-4 border-t border-slate-200 pt-4 dark:border-slate-700/50">
          <p className="mb-2 text-xs text-slate-600 dark:text-slate-400">
            Verify base URL, model, and API key (if required) with a tiny request. Uses the
            values above — you do not need to save first.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void handleTestProvider()}
              disabled={providerTestLoading}
              className="inline-flex items-center gap-2 rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs font-medium text-cyan-900 transition-colors hover:bg-cyan-500/15 disabled:opacity-50 dark:border-cyan-600/45 dark:bg-cyan-950/35 dark:text-cyan-200 dark:hover:bg-cyan-900/45"
            >
              {providerTestLoading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Network className="h-3.5 w-3.5" />
              )}
              {providerTestLoading ? "Testing…" : "Test connection"}
            </button>
            {providerTestResult && (
              <span className="inline-flex items-center gap-1 text-xs text-green-700 dark:text-green-400">
                <CheckCircle2 className="h-3.5 w-3.5" />
                OK · {providerTestResult.latency_ms} ms
              </span>
            )}
          </div>
          {providerTestResult && (
            <div className="mt-2 rounded-lg bg-green-500/10 px-3 py-2 text-xs text-green-900 dark:text-green-100/90">
              <p className="font-mono text-[11px] text-green-800/90 dark:text-green-200/85">
                {providerTestResult.provider_name}
              </p>
              <p className="mt-1 text-slate-700 dark:text-slate-300">
                {providerTestResult.tokens_used > 0 && (
                  <span className="mr-2">
                    {providerTestResult.tokens_used} tokens ·{" "}
                  </span>
                )}
                Preview: {providerTestResult.preview || "(empty)"}
              </p>
            </div>
          )}
          {providerTestError && (
            <div className="mt-2 flex gap-2 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-800 dark:text-red-200/95">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <p className="min-w-0 break-words">{providerTestError}</p>
            </div>
          )}
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
              min={1}
              value={draft.controls.max_files_per_iteration ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                update(
                  "controls",
                  "max_files_per_iteration",
                  v === "" ? null : Number(v),
                );
              }}
              className={inputClass}
              placeholder="Unlimited if empty"
            />
            <p className="mt-1 text-xs text-slate-500">
              Leave empty for no limit (large refactors). Otherwise max files touched per iteration.
            </p>
          </Field>
          <Field label="Max Lines Changed">
            <input
              type="number"
              min={1}
              value={draft.controls.max_lines_changed ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                update(
                  "controls",
                  "max_lines_changed",
                  v === "" ? null : Number(v),
                );
              }}
              className={inputClass}
              placeholder="Unlimited if empty"
            />
            <p className="mt-1 text-xs text-slate-500">
              Leave empty for no limit. Otherwise cap on the SEARCH+REPLACE line metric per iteration.
            </p>
          </Field>

          <div className="col-span-full grid grid-cols-2 gap-4 md:grid-cols-4">
            {(
              [
                ["auto_commit", "Auto commit"],
                ["require_test_pass", "Require tests to pass"],
                ["pause_on_battery", "Pause on battery"],
                ["dry_run", "Dry run"],
                ["stop_on_llm_error", "Stop on LLM error"],
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

      <Section
        title="Pull requests (Git branch / PR)"
        icon={GitPullRequest}
        defaultOpen
        id="settings-pr"
      >
        <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
          <strong>PR workflow off:</strong> Vigil only creates local branches{" "}
          <code className="rounded bg-slate-200 px-1 font-mono text-xs dark:bg-slate-800">vigil/…</code>{" "}
          from <strong>Work branch</strong> below — no push, no GitHub PR.
          <br />
          <strong>PR workflow on:</strong> After a successful iteration, Vigil can{" "}
          <code className="rounded bg-slate-200 px-1 font-mono text-xs dark:bg-slate-800">git push</code>{" "}
          and run <code className="rounded bg-slate-200 px-1 font-mono text-xs dark:bg-slate-800">gh pr create</code>{" "}
          (requires <code className="font-mono text-xs">gh</code> on the machine where Vigil runs — not Cursor MCP).
          Set <strong>Auto push</strong> on and save <code className="font-mono text-xs">vigil.yaml</code>, then restart Vigil.
        </p>

        {prRuntime && (
          <div
            className={clsx(
              "mb-4 rounded-lg border px-4 py-3 sm:px-5",
              prRuntime.preflight_ok
                ? "border-emerald-400/40 bg-emerald-50/90 dark:border-emerald-500/25 dark:bg-emerald-950/20"
                : "border-slate-300/80 bg-slate-100/90 dark:border-slate-600/50 dark:bg-slate-900/40",
            )}
          >
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              {prRuntime.preflight_ok ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
              ) : (
                <AlertCircle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
              )}
              Runtime checks (this host)
            </div>
            <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-slate-700 dark:text-slate-300">
              <li>
                <code className="font-mono text-xs">pr.enabled</code> in running process:{" "}
                {prRuntime.pr_active ? "true" : "false"} (saved config:{" "}
                {prRuntime.enabled ? "yes" : "no"})
              </li>
              <li>
                Git push to <code className="font-mono text-xs">origin</code>:{" "}
                {prRuntime.push_enabled ? (
                  <span className="text-emerald-700 dark:text-emerald-400">ready</span>
                ) : (
                  <span className="text-amber-800 dark:text-amber-300">blocked</span>
                )}
              </li>
              <li>
                <code className="font-mono text-xs">gh pr create</code>:{" "}
                {prRuntime.gh_pr_enabled ? (
                  <span className="text-emerald-700 dark:text-emerald-400">ready</span>
                ) : (
                  <span className="text-amber-800 dark:text-amber-300">blocked</span>
                )}
              </li>
            </ul>
            <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">
              {prRuntime.preflight_message}
            </p>
            {prRuntime.merge_queue_head ? (
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-500">
                Merge queue HEAD:{" "}
                <code className="font-mono">{prRuntime.merge_queue_head.slice(0, 12)}…</code>
              </p>
            ) : null}
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Enable PR Workflow">
            <button
              type="button"
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
            <p className="mt-1 text-xs text-slate-500">
              Maps to <code className="font-mono">pr.enabled</code> in vigil.yaml
            </p>
          </Field>
          <Field label="Use LLM for PR Description">
            <button
              type="button"
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
            <p className="mt-1 text-xs text-slate-500">
              <code className="font-mono">pr.use_llm_description</code>
            </p>
          </Field>

          <Field label="Work branch (local iterations)">
            <input
              type="text"
              value={draft.controls.work_branch}
              onChange={(e) =>
                update("controls", "work_branch", e.target.value)
              }
              className={clsx(inputClass, "font-mono")}
              placeholder="vigil-improvements"
            />
            <p className="mt-1 text-xs text-slate-500">
              <code className="font-mono">controls.work_branch</code> — branch Vigil returns to between iterations; iteration branches fork from here when PR is off (or as the chain base).
            </p>
          </Field>

          <Field label="Base branch (GitHub PR target)">
            <input
              type="text"
              value={draft.pr.base_branch}
              onChange={(e) => update("pr", "base_branch", e.target.value)}
              placeholder="main"
              className={clsx(inputClass, "font-mono")}
            />
            <p className="mt-1 text-xs text-slate-500">
              <code className="font-mono">pr.base_branch</code> — target for opened PRs
            </p>
          </Field>

          <Field label="Strategy">
            <select
              value={draft.pr.strategy}
              onChange={(e) => update("pr", "strategy", e.target.value)}
              className={selectClass}
            >
              <option value="per_iteration">Per Iteration</option>
            </select>
            <p className="mt-1 text-xs text-slate-500">
              <code className="font-mono">pr.strategy</code>
            </p>
          </Field>

          <Field label="Auto Push">
            <button
              type="button"
              onClick={() => update("pr", "auto_push", !draft.pr.auto_push)}
              className={clsx(
                "rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200",
                draft.pr.auto_push
                  ? "bg-green-600/15 text-green-800 dark:bg-green-600/20 dark:text-green-400"
                  : "bg-slate-200 text-slate-600 dark:bg-slate-700/50 dark:text-slate-400",
              )}
            >
              {draft.pr.auto_push ? "On" : "Off"}
            </button>
            <p className="mt-1 text-xs text-slate-500">
              <code className="font-mono">pr.auto_push</code> — must be on for push + gh PR after each iteration
            </p>
          </Field>

          <Field label="Labels (comma-separated)">
            <input
              type="text"
              value={(draft.pr.labels ?? []).join(", ")}
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
            <p className="mt-1 text-xs text-slate-500">
              <code className="font-mono">pr.labels</code>
            </p>
          </Field>

          <Field label="Reviewers (comma-separated)">
            <input
              type="text"
              value={(draft.pr.reviewers ?? []).join(", ")}
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
            <p className="mt-1 text-xs text-slate-500">
              <code className="font-mono">pr.reviewers</code> — GitHub usernames
            </p>
          </Field>
        </div>

        <div className="mt-4 rounded-lg border border-amber-400/35 bg-amber-50 px-4 py-3 dark:border-amber-500/20 dark:bg-amber-500/5">
          <p className="text-sm font-medium text-amber-950 dark:text-amber-200">
            Checklist for automated PRs
          </p>
          <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-amber-900 dark:text-amber-400/95">
            <li>
              <code className="font-mono">pr.enabled</code> and <code className="font-mono">pr.auto_push</code> set to on, then Save
            </li>
            <li>
              <code className="font-mono">git remote</code> points to GitHub (<code className="font-mono">origin</code>)
            </li>
            <li>
              GitHub CLI: <code className="font-mono">gh --version</code> and <code className="font-mono">gh auth login</code> on the same machine as Vigil
            </li>
            <li>Restart Vigil after saving so the orchestrator picks up the new config</li>
          </ul>
        </div>
      </Section>

      {/* ------------------------------------------------------------------ */}
      {/* Engineer mode                                                        */}
      {/* ------------------------------------------------------------------ */}
      <Section title="Engineer mode" icon={Target} defaultOpen>
        <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
          Switch Vigil from a code-improvement loop to a 24/7 software engineer.
          In <strong>Engineer</strong> mode Vigil works through your goals and work sources first,
          only falling back to improvement tasks when nothing actionable remains.
        </p>
        <Field label="Priority mode">
          <div className="flex gap-3">
            {(["improver", "engineer"] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => update("tasks", "priority_mode", mode)}
                className={clsx(
                  "rounded-lg px-5 py-2 text-sm font-medium capitalize transition-all duration-200",
                  draft.tasks.priority_mode === mode
                    ? "bg-blue-600 text-white shadow"
                    : "bg-slate-200 text-slate-600 dark:bg-slate-700/50 dark:text-slate-400",
                )}
              >
                {mode}
              </button>
            ))}
          </div>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-500">
            <strong>Improver</strong> — original behaviour: walks the static priority list.{" "}
            <strong>Engineer</strong> — goals and work sources first; improvements only as fallback.
          </p>
        </Field>
      </Section>

      {/* ------------------------------------------------------------------ */}
      {/* Goals                                                                */}
      {/* ------------------------------------------------------------------ */}
      <Section title="Goals" icon={Target} defaultOpen={draft.tasks.priority_mode === "engineer"}>
        <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
          Define what Vigil should build or fix next. Goals take highest priority in Engineer mode.
          Each goal can reference source files to edit and design documents to read as requirements.
        </p>

        <div className="space-y-3">
          {draft.goals.current.map((goal, idx) => (
            <div
              key={goal.id}
              className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900/40"
            >
              <div className="flex items-start gap-3">
                <div className="flex-1 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800 dark:bg-blue-900/40 dark:text-blue-300">
                      P{goal.priority}
                    </span>
                    {goal.issue_ref && (
                      <span className="rounded bg-slate-200 px-2 py-0.5 font-mono text-xs text-slate-600 dark:bg-slate-700 dark:text-slate-400">
                        {goal.issue_ref}
                      </span>
                    )}
                  </div>
                  <input
                    type="text"
                    value={goal.description}
                    onChange={(e) =>
                      updateGoal(idx, { description: e.target.value })
                    }
                    placeholder="Describe what to build or fix…"
                    className={clsx(inputClass, "font-medium")}
                  />
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="mb-1 block text-xs text-slate-500">Priority (1–5)</label>
                      <input
                        type="number"
                        min={1}
                        max={5}
                        value={goal.priority}
                        onChange={(e) =>
                          updateGoal(idx, { priority: Number(e.target.value) })
                        }
                        className={inputClass}
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-xs text-slate-500">Issue ref (optional)</label>
                      <input
                        type="text"
                        value={goal.issue_ref ?? ""}
                        onChange={(e) =>
                          updateGoal(idx, { issue_ref: e.target.value || null })
                        }
                        placeholder="org/repo#42"
                        className={clsx(inputClass, "font-mono")}
                      />
                    </div>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-slate-500">
                      Context files (comma-separated relative paths)
                    </label>
                    <input
                      type="text"
                      value={goal.context_files.join(", ")}
                      onChange={(e) =>
                        updateGoal(idx, {
                          context_files: e.target.value
                            .split(",")
                            .map((s) => s.trim())
                            .filter(Boolean),
                        })
                      }
                      placeholder="src/matching/engine.ts, src/types.ts"
                      className={clsx(inputClass, "font-mono text-xs")}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-slate-500">
                      Design docs / PRDs (comma-separated paths — read-only for LLM)
                    </label>
                    <input
                      type="text"
                      value={goal.context_docs.join(", ")}
                      onChange={(e) =>
                        updateGoal(idx, {
                          context_docs: e.target.value
                            .split(",")
                            .map((s) => s.trim())
                            .filter(Boolean),
                        })
                      }
                      placeholder="docs/PRDs/price-feed.md"
                      className={clsx(inputClass, "font-mono text-xs")}
                    />
                  </div>
                </div>
                <button
                  onClick={() => {
                    const updated = draft.goals.current.filter((_, i) => i !== idx);
                    update("goals", "current", updated);
                  }}
                  className="mt-1 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-red-100 hover:text-red-600 dark:hover:bg-red-900/30 dark:hover:text-red-400"
                  title="Remove goal"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}

          <button
            onClick={() => {
              const newGoal = {
                id: `goal-${Date.now()}`,
                description: "",
                priority: 1,
                context_files: [],
                context_docs: [],
                issue_ref: null,
              };
              update("goals", "current", [...draft.goals.current, newGoal]);
            }}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 py-3 text-sm text-slate-500 transition-colors hover:border-blue-400 hover:text-blue-600 dark:border-slate-600 dark:hover:border-blue-500 dark:hover:text-blue-400"
          >
            <Plus className="h-4 w-4" />
            Add goal
          </button>
        </div>
      </Section>

      {/* ------------------------------------------------------------------ */}
      {/* Work sources                                                          */}
      {/* ------------------------------------------------------------------ */}
      <Section title="Work sources" icon={Globe} defaultOpen={false}>
        <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
          Automatically feed tasks from external sources. Active in Engineer mode.
          GitHub issues require <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs dark:bg-slate-800">gh</code> to be authenticated.
        </p>

        <div className="space-y-6">
          {/* GitHub Issues */}
          <div>
            <div className="mb-3 flex items-center gap-3">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                GitHub Issues
              </span>
              <button
                onClick={() =>
                  update("work_sources", "github_issues", {
                    ...draft.work_sources.github_issues,
                    enabled: !draft.work_sources.github_issues.enabled,
                  })
                }
                className={clsx(
                  "rounded-lg px-3 py-1 text-xs font-medium transition-all duration-200",
                  draft.work_sources.github_issues.enabled
                    ? "bg-green-600/15 text-green-800 dark:bg-green-600/20 dark:text-green-400"
                    : "bg-slate-200 text-slate-600 dark:bg-slate-700/50 dark:text-slate-400",
                )}
              >
                {draft.work_sources.github_issues.enabled ? "Enabled" : "Disabled"}
              </button>
            </div>

            {draft.work_sources.github_issues.enabled && (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div className="col-span-full">
                  <label className="mb-1 block text-xs text-slate-500">
                    Repositories (comma-separated, e.g. org/repo)
                  </label>
                  <input
                    type="text"
                    value={draft.work_sources.github_issues.repos.join(", ")}
                    onChange={(e) =>
                      update("work_sources", "github_issues", {
                        ...draft.work_sources.github_issues,
                        repos: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                      })
                    }
                    placeholder="myorg/exchange-core, myorg/matching-engine"
                    className={clsx(inputClass, "font-mono text-xs")}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-slate-500">
                    Labels to include (comma-separated)
                  </label>
                  <input
                    type="text"
                    value={draft.work_sources.github_issues.labels_include.join(", ")}
                    onChange={(e) =>
                      update("work_sources", "github_issues", {
                        ...draft.work_sources.github_issues,
                        labels_include: e.target.value
                          .split(",")
                          .map((s) => s.trim())
                          .filter(Boolean),
                      })
                    }
                    placeholder="bug, feature, p0, p1"
                    className={clsx(inputClass, "font-mono text-xs")}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-slate-500">
                    Labels to exclude (comma-separated)
                  </label>
                  <input
                    type="text"
                    value={draft.work_sources.github_issues.labels_exclude.join(", ")}
                    onChange={(e) =>
                      update("work_sources", "github_issues", {
                        ...draft.work_sources.github_issues,
                        labels_exclude: e.target.value
                          .split(",")
                          .map((s) => s.trim())
                          .filter(Boolean),
                      })
                    }
                    placeholder="wontfix, duplicate"
                    className={clsx(inputClass, "font-mono text-xs")}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-slate-500">Max tasks per poll</label>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={draft.work_sources.github_issues.max_tasks}
                    onChange={(e) =>
                      update("work_sources", "github_issues", {
                        ...draft.work_sources.github_issues,
                        max_tasks: Number(e.target.value),
                      })
                    }
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-slate-500">
                    Poll interval (seconds)
                  </label>
                  <input
                    type="number"
                    min={60}
                    value={draft.work_sources.github_issues.poll_interval}
                    onChange={(e) =>
                      update("work_sources", "github_issues", {
                        ...draft.work_sources.github_issues,
                        poll_interval: Number(e.target.value),
                      })
                    }
                    className={inputClass}
                  />
                </div>
              </div>
            )}
          </div>

          {/* PRD paths */}
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
              PRD / Design doc paths
            </label>
            <p className="mb-2 text-xs text-slate-500">
              Vigil scans these markdown files for unchecked tasks and TODOs.
              Paths relative to the project root.
            </p>
            <input
              type="text"
              value={draft.work_sources.prd_paths.join(", ")}
              onChange={(e) =>
                update("work_sources", "prd_paths", e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean))
              }
              placeholder="docs/PRDs/matching-engine.md, docs/design/settlement.md"
              className={clsx(inputClass, "font-mono text-xs")}
            />
          </div>

          {/* Always-on context documents */}
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Always-on context documents
            </label>
            <p className="mb-2 text-xs text-slate-500">
              These documents are injected into every iteration prompt as read-only context
              (architecture overview, API spec, coding guidelines, etc.).
            </p>
            <input
              type="text"
              value={draft.work_sources.context_documents.join(", ")}
              onChange={(e) =>
                update("work_sources", "context_documents", e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean))
              }
              placeholder="docs/architecture.md, docs/api-spec.yaml"
              className={clsx(inputClass, "font-mono text-xs")}
            />
          </div>
        </div>
      </Section>
    </div>
  );
}
