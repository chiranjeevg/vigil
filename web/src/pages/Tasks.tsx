import { useState, useEffect, useRef, useCallback } from "react";
import {
  ChevronUp,
  ChevronDown,
  Plus,
  Trash2,
  Save,
  ListTodo,
  FileText,
  FolderOpen,
  Loader2,
  Sparkles,
  StopCircle,
  Terminal,
} from "lucide-react";
import clsx from "clsx";
import { api, streamDeepSuggest } from "@/lib/api";
import { type VigilProjectListItem } from "@/lib/pathUtils";
import type { CustomTask, VigilConfig, SuggestedTask } from "@/types";

/** Schema placeholders the LLM sometimes copies literally instead of real ids. */
const BAD_SUGGESTED_TASK_TYPES = new Set([
  "slug",
  "title",
  "type",
  "task",
  "label",
  "unknown",
  "name",
  "id",
]);

function slugFromLabel(label: string): string {
  const s = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return s.slice(0, 64) || "task";
}

/** Stable key for priorities / instructions when type is missing or a placeholder. */
function priorityKeyForSuggestion(t: SuggestedTask, index: number): string {
  const raw = (t.type ?? "").trim().toLowerCase();
  if (raw && !BAD_SUGGESTED_TASK_TYPES.has(raw)) {
    return t.type!.trim();
  }
  return `${slugFromLabel(t.label)}-${index}`;
}

export function Tasks() {
  const [projects, setProjects] = useState<VigilProjectListItem[]>([]);
  const [selectedProject, setSelectedProject] = useState<string>("");
  const [config, setConfig] = useState<VigilConfig | null>(null);
  const [loading, setLoading] = useState(true);

  const [priorities, setPriorities] = useState<string[]>([]);
  const [customTasks, setCustomTasks] = useState<CustomTask[]>([]);
  const [instructions, setInstructions] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [newTaskDesc, setNewTaskDesc] = useState("");
  const [newTaskFiles, setNewTaskFiles] = useState("");

  const [aiSuggested, setAiSuggested] = useState<SuggestedTask[]>([]);
  const [aiLoading, setAiLoading] = useState(false);
  const [llmEnhanced, setLlmEnhanced] = useState(false);
  const [aiLogs, setAiLogs] = useState<string[]>([]);
  const [aiPhase, setAiPhase] = useState("");
  const [showLogs, setShowLogs] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const taskPathForAI = selectedProject || config?.project?.path || "";

  useEffect(() => {
    api.getVigilProjects().then((r) => setProjects(r.projects || []));
  }, []);

  useEffect(() => {
    setLoading(true);
    const fetcher = selectedProject
      ? api.getConfigByProject(selectedProject)
      : api.getConfig();

    fetcher
      .then((cfg) => {
        setConfig(cfg);
        setPriorities(cfg.tasks.priorities);
        setCustomTasks(cfg.tasks.custom);
        setInstructions(cfg.tasks.instructions);
      })
      .catch(() => {
        setConfig(null);
        setPriorities([]);
        setCustomTasks([]);
        setInstructions({});
      })
      .finally(() => setLoading(false));
  }, [selectedProject]);

  useEffect(() => {
    setAiSuggested([]);
    setAiLogs([]);
    setAiPhase("");
  }, [selectedProject]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const appendLog = useCallback((msg: string) => {
    setAiLogs((prev) => [...prev, msg]);
    setTimeout(() => logEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
  }, []);

  function abortAISuggestions() {
    abortRef.current?.abort();
    abortRef.current = null;
  }

  function refreshAISuggestions() {
    if (!taskPathForAI) return;

    abortRef.current?.abort();
    setAiLoading(true);
    setAiLogs([]);
    setAiPhase("Starting deep analysis…");
    setShowLogs(true);
    setAiSuggested([]);
    setLlmEnhanced(false);

    const controller = streamDeepSuggest(
      taskPathForAI,
      (evt) => {
        if (evt.type === "log") {
          const d = evt.data as { msg?: string; level?: string };
          const msg = d.msg ?? "";
          appendLog(msg);

          if (msg.startsWith("Phase 1:")) setAiPhase("Phase 1 — Structural analysis");
          else if (msg.startsWith("Phase 2:")) setAiPhase("Phase 2 — Architecture understanding");
          else if (msg.startsWith("Phase 3")) setAiPhase("Phase 3 — Deep code tracing");
          else if (msg.startsWith("Phase 4:")) setAiPhase("Phase 4 — Synthesizing tasks");
          else if (msg.startsWith("Deep analysis complete")) setAiPhase("Complete");
        } else if (evt.type === "phase1_complete") {
          const d = evt.data as { source_file_count?: number; todo_count?: number; elapsed_seconds?: number };
          appendLog(`── Phase 1 done: ${d.source_file_count} files, ${d.todo_count} TODOs (${d.elapsed_seconds}s)`);
        } else if (evt.type === "architecture") {
          const d = evt.data as { domain?: string; architecture?: string };
          appendLog(`── Domain: ${d.domain}`);
          appendLog(`── Architecture: ${d.architecture}`);
        } else if (evt.type === "tasks_ready") {
          const d = evt.data as { suggested?: SuggestedTask[]; llm_enhanced?: boolean };
          setAiSuggested(d.suggested ?? []);
          setLlmEnhanced(d.llm_enhanced ?? false);
          setAiLoading(false);
          setAiPhase("Complete");
        } else if (evt.type === "done") {
          setAiLoading(false);
          setAiPhase("Complete");
        } else if (evt.type === "error") {
          const d = evt.data as { msg?: string };
          appendLog(`ERROR: ${d.msg}`);
          setAiLoading(false);
          setAiPhase("Failed");
        }
      },
      (err) => {
        appendLog(`Error: ${err.message}`);
        setAiLoading(false);
        setAiPhase("Failed");
      },
      () => {
        setAiLoading(false);
        setAiPhase("Complete");
      },
      () => {
        appendLog("Cancelled — analysis stopped.");
        setAiLoading(false);
        setAiPhase("Cancelled");
      },
    );

    abortRef.current = controller;
  }

  function toggleAiEnabled(index: number) {
    setAiSuggested((prev) => {
      const next = [...prev];
      const cur = next[index];
      if (!cur) return prev;
      next[index] = { ...cur, enabled: !cur.enabled };
      return next;
    });
  }

  function applyAISuggestions() {
    const enabled = aiSuggested.filter((t) => t.enabled);
    if (enabled.length === 0) return;
    setPriorities(enabled.map((t, i) => priorityKeyForSuggestion(t, i)));
    setInstructions((prev) => {
      const next = { ...prev };
      enabled.forEach((t, i) => {
        const key = priorityKeyForSuggestion(t, i);
        if (t.instructions) next[key] = t.instructions;
      });
      return next;
    });
    setCustomTasks(
      enabled
        .filter((t) => t.type.startsWith("custom_"))
        .map((t, i) => ({
          id: t.type,
          description: t.description,
          files: [] as string[],
          priority: i + 1,
        })),
    );
  }

  const projectName = selectedProject
    ? projects.find((p) => p.path === selectedProject)?.name ??
      "Selected project"
    : config?.project?.name ?? "Active daemon";

  function movePriority(index: number, direction: -1 | 1) {
    const next = [...priorities];
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index]!, next[target]!] = [next[target]!, next[index]!];
    setPriorities(next);
  }

  function addCustomTask() {
    if (!newTaskDesc.trim()) return;
    const id = `custom_${Date.now()}`;
    setCustomTasks((prev) => [
      ...prev,
      {
        id,
        description: newTaskDesc.trim(),
        files: newTaskFiles
          .split(",")
          .map((f) => f.trim())
          .filter(Boolean),
        priority: prev.length + 1,
      },
    ]);
    setNewTaskDesc("");
    setNewTaskFiles("");
  }

  function removeCustomTask(id: string) {
    setCustomTasks((prev) => prev.filter((t) => t.id !== id));
  }

  async function handleSave() {
    setSaving(true);
    try {
      const taskUpdate = { tasks: { priorities, custom: customTasks, instructions } };
      if (selectedProject) {
        await api.updateConfigByProject(selectedProject, taskUpdate);
      } else {
        await api.updateConfig(taskUpdate);
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // error handled silently
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Tasks</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Configure task priorities and custom tasks for{" "}
            <span className="font-medium text-slate-800 dark:text-slate-300">{projectName}</span>
          </p>
        </div>
        <div className="flex items-center gap-3">
          {projects.length > 0 && (
            <div className="relative">
              <FolderOpen className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
              <select
                value={selectedProject}
                onChange={(e) => setSelectedProject(e.target.value)}
                className="appearance-none rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-8 text-xs font-medium text-slate-800 outline-none transition-colors hover:border-slate-400 focus:border-blue-500 dark:border-slate-700/50 dark:bg-slate-800/50 dark:text-slate-300 dark:hover:border-slate-600"
              >
                <option value="">Active daemon (default)</option>
                {projects.map((p) => (
                  <option key={p.path} value={p.path}>
                    {p.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
            </div>
          )}
          <button
            onClick={handleSave}
            disabled={saving || loading}
            className={clsx(
              "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200",
              saved
                ? "bg-green-600 text-white"
                : "bg-blue-600 text-white hover:bg-blue-500",
            )}
          >
            <Save className="h-4 w-4" />
            {saved ? "Saved!" : saving ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
        </div>
      ) : (
        <>
          {taskPathForAI ? (
            <div className="rounded-xl border border-purple-300/50 bg-purple-50/80 p-6 dark:border-purple-500/20 dark:bg-slate-800/50">
              <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="flex items-center gap-2 text-base font-semibold text-slate-900 dark:text-white">
                    <Sparkles className="h-5 w-5 text-purple-400" />
                    AI task suggestions
                  </h2>
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                    Deep analysis: scans code structure, traces critical paths, reads key files,
                    then uses AI to find project-specific issues.
                  </p>
                  {llmEnhanced && (
                    <p className="mt-1 text-xs text-purple-800 dark:text-purple-300/90">
                      Deep analysis complete — domain-aware suggestions
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void refreshAISuggestions()}
                    disabled={aiLoading}
                    className="inline-flex items-center gap-2 rounded-lg border border-purple-400/50 bg-purple-100/80 px-3 py-2 text-sm font-medium text-purple-900 transition-colors hover:bg-purple-200/80 disabled:opacity-50 dark:border-purple-500/40 dark:bg-purple-500/10 dark:text-purple-200 dark:hover:bg-purple-500/20"
                  >
                    {aiLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Sparkles className="h-4 w-4" />
                    )}
                    {aiLoading ? "Deep analysis…" : "Refresh with AI"}
                  </button>
                  {aiLoading && (
                    <button
                      type="button"
                      onClick={abortAISuggestions}
                      className="inline-flex items-center gap-2 rounded-lg border border-red-400/60 bg-red-50 px-3 py-2 text-sm font-medium text-red-800 transition-colors hover:bg-red-100 dark:border-red-500/40 dark:bg-red-950/40 dark:text-red-200 dark:hover:bg-red-900/50"
                    >
                      <StopCircle className="h-4 w-4" />
                      Abort
                    </button>
                  )}
                  {aiSuggested.length > 0 && (
                    <button
                      type="button"
                      onClick={applyAISuggestions}
                      className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500"
                    >
                      Apply to priorities
                    </button>
                  )}
                </div>
              </div>

              {/* Phase progress bar */}
              {(aiLoading || aiPhase) && (
                <div className="mb-4">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {aiLoading && <Loader2 className="h-3.5 w-3.5 animate-spin text-purple-500" />}
                      <span className="text-xs font-medium text-purple-700 dark:text-purple-300">
                        {aiPhase || "Initializing…"}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setShowLogs((v) => !v)}
                      className="inline-flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                    >
                      <Terminal className="h-3 w-3" />
                      {showLogs ? "Hide logs" : "Show logs"}
                    </button>
                  </div>

                  {/* Phase step indicators */}
                  <div className="flex gap-1">
                    {["Phase 1", "Phase 2", "Phase 3", "Phase 4"].map((phase) => {
                      const isActive = aiPhase.includes(phase);
                      const phaseNum = parseInt(phase.split(" ")[1] ?? "0");
                      const currentNum = parseInt(
                        aiPhase.match(/Phase (\d)/)?.[1] ?? "0",
                      );
                      const isDone = phaseNum < currentNum || aiPhase === "Complete";
                      return (
                        <div
                          key={phase}
                          className={clsx(
                            "h-1.5 flex-1 rounded-full transition-all duration-500",
                            isDone
                              ? "bg-green-500"
                              : isActive
                                ? "animate-pulse bg-purple-500"
                                : "bg-slate-200 dark:bg-slate-700",
                          )}
                        />
                      );
                    })}
                  </div>

                  {/* Live log panel */}
                  {showLogs && aiLogs.length > 0 && (
                    <div className="mt-2 max-h-48 overflow-y-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] leading-relaxed text-green-400">
                      {aiLogs.map((line, i) => (
                        <div
                          key={i}
                          className={clsx(
                            line.startsWith("──") && "text-blue-400",
                            line.startsWith("ERROR") && "text-red-400",
                            line.includes("[P0]") && "text-red-400 font-bold",
                            line.includes("[P1]") && "text-amber-400",
                            line.startsWith("  →") && "text-slate-400",
                          )}
                        >
                          {line}
                        </div>
                      ))}
                      <div ref={logEndRef} />
                    </div>
                  )}
                </div>
              )}

              {aiSuggested.length > 0 ? (
                <ul className="space-y-3">
                  {aiSuggested.map((t, idx) => (
                    <li
                      key={`ai-suggest-${idx}`}
                      className={clsx(
                        "rounded-lg border px-4 py-3 transition-colors",
                        t.severity === "P0"
                          ? "border-red-300/60 bg-red-50/60 dark:border-red-500/30 dark:bg-red-950/20"
                          : t.severity === "P1"
                            ? "border-amber-300/60 bg-amber-50/50 dark:border-amber-500/20 dark:bg-amber-950/20"
                            : "border-slate-200 bg-white/90 dark:border-slate-700/50 dark:bg-slate-900/40",
                      )}
                    >
                      <div className="flex items-start gap-3">
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={t.enabled}
                          onChange={() => toggleAiEnabled(idx)}
                          aria-label={`Enable ${t.label}`}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            {t.severity && (
                              <span
                                className={clsx(
                                  "rounded px-1.5 py-0.5 text-xs font-bold",
                                  t.severity === "P0"
                                    ? "bg-red-500/15 text-red-700 dark:text-red-400"
                                    : t.severity === "P1"
                                      ? "bg-amber-500/15 text-amber-700 dark:text-amber-400"
                                      : t.severity === "P2"
                                        ? "bg-blue-500/10 text-blue-700 dark:text-blue-400"
                                        : "bg-slate-500/10 text-slate-600 dark:text-slate-400",
                                )}
                              >
                                {t.severity}
                              </span>
                            )}
                            {t.category && (
                              <span className="rounded bg-slate-200/80 px-1.5 py-0.5 text-xs text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                                {t.category}
                              </span>
                            )}
                            {t.type &&
                              !BAD_SUGGESTED_TASK_TYPES.has(
                                t.type.trim().toLowerCase(),
                              ) && (
                                <span
                                  className="font-mono text-xs text-slate-400"
                                  title="Internal task id (used in saved config)"
                                >
                                  {t.type}
                                </span>
                              )}
                          </div>
                          <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">
                            {t.label}
                          </p>
                          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                            {t.reason}
                          </p>
                          {t.approach && (
                            <p className="mt-1.5 rounded bg-slate-100/80 px-2 py-1 text-xs text-slate-700 dark:bg-slate-800/80 dark:text-slate-300">
                              <span className="font-semibold">Approach:</span> {t.approach}
                            </p>
                          )}
                          {t.files && t.files.length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1">
                              {t.files.slice(0, 5).map((f) => (
                                <span
                                  key={f}
                                  className="rounded bg-blue-100/60 px-1.5 py-0.5 font-mono text-[10px] text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
                                >
                                  {f}
                                </span>
                              ))}
                              {t.files.length > 5 && (
                                <span className="text-[10px] text-slate-400">+{t.files.length - 5} more</span>
                              )}
                            </div>
                          )}
                          {t.estimated_complexity && (
                            <span
                              className={clsx(
                                "mt-1 inline-block rounded px-1.5 py-0.5 text-[10px]",
                                t.estimated_complexity === "trivial"
                                  ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                                  : t.estimated_complexity === "significant"
                                    ? "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400"
                                    : "bg-slate-100 text-slate-600 dark:bg-slate-700/50 dark:text-slate-400",
                              )}
                            >
                              {t.estimated_complexity}
                            </span>
                          )}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-slate-600 dark:text-slate-500">
                  Click &quot;Refresh with AI&quot; to load suggestions for this project.
                </p>
              )}
            </div>
          ) : null}

          <div className="rounded-xl border border-slate-200 bg-white/90 p-6 dark:border-slate-700/50 dark:bg-slate-800/50">
            <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-slate-900 dark:text-white">
              <ListTodo className="h-5 w-5 text-blue-600 dark:text-blue-400" />
              Task Priorities
            </h2>
            <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
              Order determines which tasks Vigil picks first. Use arrows to
              reorder.
            </p>

            {priorities.length > 0 ? (
              <div className="space-y-2">
                {priorities.map((priority, i) => (
                  <div
                    key={`priority-${i}-${priority}`}
                    className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 transition-all duration-200 hover:border-slate-300 dark:border-slate-700/50 dark:bg-slate-900/50 dark:hover:border-slate-600/50"
                  >
                    <span className="w-6 text-center font-mono text-xs text-slate-500">
                      {i + 1}
                    </span>
                    <span className="flex-1 text-sm font-medium text-slate-900 dark:text-white">
                      {priority}
                    </span>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => movePriority(i, -1)}
                        disabled={i === 0}
                        className="rounded p-1 text-slate-500 transition-colors hover:bg-slate-200 hover:text-slate-900 disabled:opacity-30 dark:text-slate-400 dark:hover:bg-slate-700/50 dark:hover:text-white"
                      >
                        <ChevronUp className="h-4 w-4" />
                      </button>
                      <button
                        onClick={() => movePriority(i, 1)}
                        disabled={i === priorities.length - 1}
                        className="rounded p-1 text-slate-500 transition-colors hover:bg-slate-200 hover:text-slate-900 disabled:opacity-30 dark:text-slate-400 dark:hover:bg-slate-700/50 dark:hover:text-white"
                      >
                        <ChevronDown className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="py-8 text-center text-sm text-slate-600 dark:text-slate-500">
                No priorities configured yet.
              </p>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white/90 p-6 dark:border-slate-700/50 dark:bg-slate-800/50">
            <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-slate-900 dark:text-white">
              <Plus className="h-5 w-5 text-green-600 dark:text-green-400" />
              Custom Tasks
            </h2>

            {customTasks.length > 0 && (
              <div className="mb-4 space-y-2">
                {customTasks.map((task) => (
                  <div
                    key={task.id}
                    className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700/50 dark:bg-slate-900/50"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-slate-900 dark:text-white">
                        {task.description}
                      </p>
                      {task.files.length > 0 && (
                        <p className="mt-0.5 truncate font-mono text-xs text-slate-500">
                          {task.files.join(", ")}
                        </p>
                      )}
                    </div>
                    <button
                      onClick={() => removeCustomTask(task.id)}
                      className="rounded p-1.5 text-slate-400 transition-colors hover:bg-red-500/10 hover:text-red-400"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="space-y-3 rounded-lg border border-dashed border-slate-300 p-4 dark:border-slate-700">
              <input
                type="text"
                placeholder="Task description..."
                value={newTaskDesc}
                onChange={(e) => setNewTaskDesc(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-500 transition-colors focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:placeholder-slate-500"
              />
              <input
                type="text"
                placeholder="Target files (comma-separated, optional)"
                value={newTaskFiles}
                onChange={(e) => setNewTaskFiles(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm text-slate-900 placeholder-slate-500 transition-colors focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:placeholder-slate-500"
              />
              <button
                onClick={addCustomTask}
                disabled={!newTaskDesc.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-slate-600 px-3 py-2 text-sm font-medium text-white transition-all duration-200 hover:bg-slate-500 disabled:opacity-40 dark:bg-slate-700 dark:hover:bg-slate-600"
              >
                <Plus className="h-4 w-4" />
                Add Task
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white/90 p-6 dark:border-slate-700/50 dark:bg-slate-800/50">
            <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-slate-900 dark:text-white">
              <FileText className="h-5 w-5 text-amber-600 dark:text-amber-400" />
              Task Instructions
            </h2>
            <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
              Custom instructions for each task type. These guide how Vigil
              approaches each category.
            </p>

            <div className="space-y-4">
              {priorities.map((taskType, ti) => (
                <div key={`instr-${ti}-${taskType}`}>
                  <label className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
                    {taskType}
                  </label>
                  <textarea
                    value={instructions[taskType] ?? ""}
                    onChange={(e) =>
                      setInstructions((prev) => ({
                        ...prev,
                        [taskType]: e.target.value,
                      }))
                    }
                    rows={3}
                    placeholder={`Instructions for ${taskType} tasks...`}
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm text-slate-900 placeholder-slate-500 transition-colors focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:placeholder-slate-500"
                  />
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
