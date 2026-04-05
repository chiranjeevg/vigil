import { useState, useEffect, useCallback, useRef } from "react";
import {
  FolderOpen,
  ChevronRight,
  ChevronUp,
  GitBranch,
  Loader2,
  Sparkles,
  Check,
  AlertCircle,
  Play,
  FileCode,
  TestTube,
  BarChart3,
  Settings2,
  GripVertical,
  Plus,
  Trash2,
  Pencil,
  X,
  Lightbulb,
  ArrowUp,
  ArrowDown,
  CheckCircle2,
  Brain,
  Terminal,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import type { AnalysisStreamEvent } from "@/lib/api";
import { useNavigate } from "react-router-dom";
import type { SuggestedTask } from "@/types";

type Step = "select" | "analyze" | "configure" | "ready";

interface DirectoryItem {
  name: string;
  path: string;
  is_git_repo: boolean;
}

interface Analysis {
  detected_languages: string[];
  is_git_repo: boolean;
  has_tests: boolean;
  has_benchmarks: boolean;
  file_count: number;
  config_files: string[];
}

export function Setup() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("select");

  const [currentPath, setCurrentPath] = useState<string>("");
  const [directories, setDirectories] = useState<DirectoryItem[]>([]);
  const [recentProjects, setRecentProjects] = useState<DirectoryItem[]>([]);
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);

  const [suggestedTasks, setSuggestedTasks] = useState<SuggestedTask[]>([]);
  const [availableTasks, setAvailableTasks] = useState<SuggestedTask[]>([]);
  const [taskSuggestionsLoading, setTaskSuggestionsLoading] = useState(false);
  const [llmEnhanced, setLlmEnhanced] = useState(false);
  const [editingTask, setEditingTask] = useState<string | null>(null);
  const [addingCustomTask, setAddingCustomTask] = useState(false);
  const [customTaskForm, setCustomTaskForm] = useState({
    label: "",
    description: "",
    instructions: "",
  });

  const [applying, setApplying] = useState(false);

  interface LogEntry {
    ts: number;
    msg: string;
    level: "info" | "detail" | "llm" | "error";
  }
  const [analysisLogs, setAnalysisLogs] = useState<LogEntry[]>([]);
  const [analysisPhase, setAnalysisPhase] = useState<string>("");
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadRecent();
    browse(undefined);
  }, []);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [analysisLogs]);

  async function loadRecent() {
    try {
      const { projects } = await api.getRecentProjects();
      setRecentProjects(projects);
    } catch {
      // ignore
    }
  }

  async function browse(path?: string) {
    setLoading(true);
    setError(null);
    try {
      const result = await api.browseDirectories(path);
      setCurrentPath(result.current);
      setParentPath(result.parent);
      setDirectories(result.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to browse");
    } finally {
      setLoading(false);
    }
  }

  async function selectProject(path: string) {
    setSelectedPath(path);
    setStep("analyze");
    setError(null);
    setAnalysisLogs([]);
    setAnalysisPhase("Starting...");

    const addLog = (msg: string, level: LogEntry["level"] = "info") => {
      setAnalysisLogs((prev) => [...prev, { ts: Date.now(), msg, level }]);
    };

    try {
      await api.analyzeProjectStream(path, (evt: AnalysisStreamEvent) => {
        switch (evt.type) {
          case "log": {
            const d = evt.data as { msg: string; level: string };
            addLog(d.msg, d.level as LogEntry["level"]);
            if (d.level === "info") setAnalysisPhase(d.msg);
            break;
          }
          case "scan_complete": {
            const d = evt.data;
            setAnalysis({
              detected_languages: (d.languages as string[]) ?? [],
              is_git_repo: !!d.is_git_repo,
              has_tests: !!d.has_tests,
              has_benchmarks: !!d.has_benchmarks,
              file_count: (d.file_count as number) ?? 0,
              config_files: (d.config_files as string[]) ?? [],
            });
            break;
          }
          case "config_ready":
            setConfig(evt.data as Record<string, unknown>);
            break;
          case "tasks_ready": {
            const d = evt.data as {
              suggested: SuggestedTask[];
              available: SuggestedTask[];
              llm_enhanced: boolean;
            };
            setSuggestedTasks(d.suggested);
            setAvailableTasks(d.available);
            setLlmEnhanced(d.llm_enhanced);
            break;
          }
          case "llm_prompt": {
            const d = evt.data as { system: string; user: string };
            addLog(`System: ${d.system}`, "llm");
            addLog(`Prompt: ${d.user}`, "llm");
            break;
          }
          case "llm_chunk": {
            const d = evt.data as { text: string };
            addLog(`LLM Response: ${d.text.slice(0, 500)}${d.text.length > 500 ? "..." : ""}`, "llm");
            break;
          }
          case "done":
            setStep("configure");
            break;
          case "error":
            setError((evt.data as { msg: string }).msg);
            setStep("select");
            break;
        }
      });
      if (step !== "configure") {
        setStep("configure");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
      setStep("select");
    }
  }

  const refreshTaskSuggestions = useCallback(async () => {
    if (!selectedPath) return;
    setTaskSuggestionsLoading(true);
    try {
      const result = await api.suggestTasks(selectedPath);
      setSuggestedTasks(result.suggested);
      setAvailableTasks(result.available);
      setLlmEnhanced(result.llm_enhanced);
    } catch {
      // keep existing suggestions
    } finally {
      setTaskSuggestionsLoading(false);
    }
  }, [selectedPath]);

  function moveTask(index: number, direction: "up" | "down") {
    const newTasks = [...suggestedTasks];
    const swapIdx = direction === "up" ? index - 1 : index + 1;
    if (swapIdx < 0 || swapIdx >= newTasks.length) return;
    const a = newTasks[index]!;
    const b = newTasks[swapIdx]!;
    newTasks[index] = b;
    newTasks[swapIdx] = a;
    newTasks.forEach((t, i) => (t.priority = i + 1));
    setSuggestedTasks(newTasks);
  }

  function removeTask(index: number) {
    const removed = suggestedTasks[index]!;
    const newSuggested = suggestedTasks.filter((_, i) => i !== index);
    newSuggested.forEach((t, i) => (t.priority = i + 1));
    setSuggestedTasks(newSuggested);
    const movedBack: SuggestedTask = { ...removed, enabled: false, priority: 0 };
    setAvailableTasks([...availableTasks, movedBack]);
  }

  function addFromAvailable(task: SuggestedTask) {
    const newTask = {
      ...task,
      enabled: true,
      priority: suggestedTasks.length + 1,
    };
    setSuggestedTasks([...suggestedTasks, newTask]);
    setAvailableTasks(availableTasks.filter((t) => t.type !== task.type));
  }

  function addCustomTask() {
    if (!customTaskForm.label.trim()) return;
    const slug = customTaskForm.label
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_|_$/g, "");
    const newTask: SuggestedTask = {
      type: `custom_${slug}`,
      label: customTaskForm.label,
      description: customTaskForm.description,
      reason: "Custom task added by user",
      priority: suggestedTasks.length + 1,
      enabled: true,
      instructions: customTaskForm.instructions,
    };
    setSuggestedTasks([...suggestedTasks, newTask]);
    setCustomTaskForm({ label: "", description: "", instructions: "" });
    setAddingCustomTask(false);
  }

  function updateTaskInstructions(index: number, instructions: string) {
    const newTasks = [...suggestedTasks];
    newTasks[index] = { ...newTasks[index]!, instructions };
    setSuggestedTasks(newTasks);
  }

  async function applyConfig() {
    if (!config) return;
    setApplying(true);
    setError(null);

    const enabledTasks = suggestedTasks.filter((t) => t.enabled);
    const finalConfig = {
      ...config,
      tasks: {
        priorities: enabledTasks.map((t) => t.type),
        custom: enabledTasks
          .filter((t) => t.type.startsWith("custom_"))
          .map((t) => ({
            id: t.type,
            description: t.description,
            files: [],
            priority: t.priority,
          })),
        instructions: Object.fromEntries(
          enabledTasks
            .filter((t) => t.instructions)
            .map((t) => [t.type, t.instructions]),
        ),
      },
    };

    try {
      await api.applySetup(finalConfig, true);
      setStep("ready");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to apply config");
    } finally {
      setApplying(false);
    }
  }

  function updateConfig(section: string, key: string, value: unknown) {
    if (!config) return;
    setConfig({
      ...config,
      [section]: {
        ...(config[section] as Record<string, unknown>),
        [key]: value,
      },
    });
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Setup New Project</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Select a project folder and Vigil will analyze it and suggest optimal
          configuration
        </p>
      </div>

      {/* Progress Steps */}
      <div className="flex items-center gap-2">
        {(
          [
            { key: "select", label: "Select" },
            { key: "analyze", label: "Analyze" },
            { key: "configure", label: "Configure" },
            { key: "ready", label: "Ready" },
          ] as const
        ).map((s, idx) => (
          <div key={s.key} className="flex items-center">
            <div
              className={clsx(
                "flex h-8 w-8 items-center justify-center rounded-full text-sm font-medium",
                step === s.key
                  ? "bg-blue-600 text-white"
                  : idx <
                      ["select", "analyze", "configure", "ready"].indexOf(step)
                    ? "bg-green-600 text-white"
                    : "bg-slate-300 text-slate-600 dark:bg-slate-700 dark:text-slate-400",
              )}
            >
              {idx <
              ["select", "analyze", "configure", "ready"].indexOf(step) ? (
                <Check className="h-4 w-4" />
              ) : (
                idx + 1
              )}
            </div>
            {idx < 3 && (
              <div
                className={clsx(
                  "mx-2 h-0.5 w-12",
                  idx <
                    ["select", "analyze", "configure", "ready"].indexOf(step)
                    ? "bg-green-600"
                    : "bg-slate-300 dark:bg-slate-700",
                )}
              />
            )}
          </div>
        ))}
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-400">
          <AlertCircle className="h-4 w-4" />
          {error}
        </div>
      )}

      {/* Step 1: Select Project */}
      {step === "select" && (
        <div className="space-y-6">
          {recentProjects.length > 0 && (
            <div className="rounded-xl border border-slate-200 bg-white/90 p-5 dark:border-slate-700/50 dark:bg-slate-800/50">
              <h2 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-300">
                Recent Projects
              </h2>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {recentProjects.slice(0, 6).map((proj) => (
                  <button
                    key={proj.path}
                    onClick={() => selectProject(proj.path)}
                    className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-left transition-all hover:border-blue-500/50 hover:bg-slate-100 dark:border-slate-700/50 dark:bg-slate-900/50 dark:hover:bg-slate-800"
                  >
                    {proj.is_git_repo ? (
                      <GitBranch className="h-4 w-4 text-green-400" />
                    ) : (
                      <FolderOpen className="h-4 w-4 text-slate-400" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-slate-900 dark:text-white">
                        {proj.name}
                      </div>
                      <div className="truncate text-xs text-slate-500">
                        {proj.path}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="rounded-xl border border-slate-200 bg-white/90 p-5 dark:border-slate-700/50 dark:bg-slate-800/50">
            <h2 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-300">
              Browse Folders
            </h2>
            <div className="mb-3 flex items-center gap-2 rounded-lg bg-slate-100 px-3 py-2 dark:bg-slate-900">
              <FolderOpen className="h-4 w-4 text-slate-500 dark:text-slate-400" />
              <span className="flex-1 truncate font-mono text-sm text-slate-800 dark:text-slate-300">
                {currentPath}
              </span>
              {parentPath && (
                <button
                  onClick={() => browse(parentPath)}
                  className="rounded p-1 text-slate-500 hover:bg-slate-200 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-white"
                >
                  <ChevronUp className="h-4 w-4" />
                </button>
              )}
            </div>
            <div className="max-h-80 space-y-1 overflow-y-auto">
              {loading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-blue-600 dark:text-blue-400" />
                </div>
              ) : (
                directories.map((dir) => (
                  <div key={dir.path} className="flex items-center gap-1">
                    <button
                      onClick={() => browse(dir.path)}
                      className="flex flex-1 items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-slate-200/80 dark:hover:bg-slate-700/50"
                    >
                      {dir.is_git_repo ? (
                        <GitBranch className="h-4 w-4 text-green-400" />
                      ) : (
                        <FolderOpen className="h-4 w-4 text-slate-400" />
                      )}
                      <span className="flex-1 truncate text-sm text-slate-900 dark:text-white">
                        {dir.name}
                      </span>
                      <ChevronRight className="h-4 w-4 text-slate-500" />
                    </button>
                    <button
                      onClick={() => selectProject(dir.path)}
                      className="rounded-lg bg-blue-600/20 px-3 py-1.5 text-xs font-medium text-blue-400 transition-colors hover:bg-blue-600/30"
                    >
                      Select
                    </button>
                  </div>
                ))
              )}
            </div>
            <button
              onClick={() => selectProject(currentPath)}
              className="mt-4 w-full rounded-lg bg-blue-600 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-500"
            >
              Use Current Folder
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Analyzing */}
      {step === "analyze" && (
        <div className="space-y-4">
          <div className="flex items-center gap-4 rounded-xl border border-slate-200 bg-white/90 p-5 dark:border-slate-700/50 dark:bg-slate-800/50">
            <div className="relative flex-shrink-0">
              <Loader2 className="h-10 w-10 animate-spin text-blue-600 dark:text-blue-400" />
              <Brain className="absolute left-1/2 top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 text-blue-600 dark:text-blue-300" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-900 dark:text-white">{analysisPhase}</p>
              <p className="mt-0.5 truncate text-xs text-slate-600 dark:text-slate-400">
                {selectedPath}
              </p>
            </div>
          </div>

          {/* Live log panel */}
          <div className="rounded-xl border border-slate-200 bg-slate-50 dark:border-slate-700/50 dark:bg-slate-900/80">
            <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-2 dark:border-slate-700/50">
              <Terminal className="h-3.5 w-3.5 text-slate-500" />
              <span className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
                Analysis Log
              </span>
              <span className="ml-auto text-[10px] text-slate-600">
                {analysisLogs.length} events
              </span>
            </div>
            <div className="max-h-80 overflow-y-auto p-3 font-mono text-xs leading-relaxed">
              {analysisLogs.length === 0 && (
                <div className="flex items-center gap-2 py-4 text-center text-slate-600">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Waiting for events...
                </div>
              )}
              {analysisLogs.map((entry, i) => (
                <div
                  key={i}
                  className={clsx(
                    "py-0.5",
                    entry.level === "info" && "text-slate-300",
                    entry.level === "detail" && "text-slate-500",
                    entry.level === "llm" && "text-purple-400/80",
                    entry.level === "error" && "text-red-400",
                  )}
                >
                  <span className="mr-2 text-slate-600">
                    {new Date(entry.ts).toLocaleTimeString("en-US", {
                      hour12: false,
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </span>
                  {entry.level === "llm" && (
                    <span className="mr-1 rounded bg-purple-500/20 px-1 py-px text-[9px] text-purple-400">
                      LLM
                    </span>
                  )}
                  {entry.msg}
                </div>
              ))}
              <div ref={logEndRef} />
            </div>
          </div>
        </div>
      )}

      {/* Step 3: Configure */}
      {step === "configure" && config && analysis && (
        <div className="space-y-6">
          {/* Analysis Summary */}
          <div className="rounded-xl border border-slate-200 bg-white/90 dark:border-slate-700/50 dark:bg-slate-800/50 p-5">
            <h2 className="mb-4 text-sm font-semibold text-slate-300">
              Project Analysis
            </h2>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatCard label="Language" value={analysis.detected_languages[0] || "Unknown"} />
              <StatCard label="Files" value={String(analysis.file_count)} />
              <StatCard
                label="Tests"
                value={analysis.has_tests ? "Detected" : "Not found"}
                color={analysis.has_tests ? "green" : "slate"}
              />
              <StatCard
                label="Git"
                value={analysis.is_git_repo ? "Yes" : "No"}
                color={analysis.is_git_repo ? "green" : "slate"}
              />
            </div>
          </div>

          {/* Task Suggestions — the main event */}
          <div className="rounded-xl border border-slate-200 bg-white/90 dark:border-slate-700/50 dark:bg-slate-800/50 p-5">
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-purple-400" />
                <h2 className="text-sm font-semibold text-slate-300">
                  Suggested Iteration Tasks
                </h2>
                {llmEnhanced && (
                  <span className="rounded-full bg-purple-600/20 px-2 py-0.5 text-[10px] font-medium text-purple-400">
                    AI-Enhanced
                  </span>
                )}
              </div>
              <button
                onClick={refreshTaskSuggestions}
                disabled={taskSuggestionsLoading}
                className="inline-flex items-center gap-1.5 rounded-lg bg-purple-600/20 px-3 py-1.5 text-xs font-medium text-purple-400 transition-colors hover:bg-purple-600/30 disabled:opacity-50"
              >
                {taskSuggestionsLoading ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Sparkles className="h-3 w-3" />
                )}
                {taskSuggestionsLoading ? "Refreshing..." : "Refresh with AI"}
              </button>
            </div>

            <p className="mb-4 text-xs text-slate-500">
              Vigil will work through these tasks in order. Drag to reorder,
              click to edit instructions, or add your own tasks.
            </p>

            {/* Task list */}
            <div className="space-y-2">
              {suggestedTasks.map((task, idx) => (
                <div
                  key={task.type}
                  className="group rounded-lg border border-slate-200 bg-slate-50 transition-all hover:border-slate-300 dark:border-slate-700/40 dark:bg-slate-900/50 dark:hover:border-slate-600/60"
                >
                  <div className="flex items-start gap-3 px-4 py-3">
                    <div className="flex flex-col items-center gap-0.5 pt-0.5">
                      <GripVertical className="h-4 w-4 text-slate-600" />
                      <span className="text-[10px] font-bold text-slate-500">
                        {idx + 1}
                      </span>
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="h-4 w-4 text-green-500" />
                        <span className="text-sm font-medium text-slate-900 dark:text-white">
                          {task.label}
                        </span>
                        <span className="rounded bg-slate-700/60 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                          {task.type}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-slate-400">
                        {task.description}
                      </p>
                      {task.reason && (
                        <div className="mt-1.5 flex items-start gap-1.5">
                          <Lightbulb className="mt-0.5 h-3 w-3 flex-shrink-0 text-amber-500/70" />
                          <p className="text-[11px] leading-relaxed text-amber-400/80">
                            {task.reason}
                          </p>
                        </div>
                      )}

                      {editingTask === task.type && (
                        <div className="mt-3">
                          <label className="mb-1 block text-[10px] font-medium uppercase tracking-wider text-slate-500">
                            Custom Instructions for this Task
                          </label>
                          <textarea
                            value={task.instructions}
                            onChange={(e) =>
                              updateTaskInstructions(idx, e.target.value)
                            }
                            placeholder="e.g. Focus on the API layer first. Use pytest fixtures for database tests."
                            rows={3}
                            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-xs text-slate-900 placeholder-slate-500 focus:border-purple-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:placeholder-slate-600"
                          />
                          <button
                            onClick={() => setEditingTask(null)}
                            className="mt-1.5 text-xs text-slate-500 hover:text-slate-300"
                          >
                            Done editing
                          </button>
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                      <button
                        onClick={() => moveTask(idx, "up")}
                        disabled={idx === 0}
                        className="rounded p-1 text-slate-500 hover:bg-slate-200 hover:text-slate-900 disabled:opacity-30 dark:hover:bg-slate-700 dark:hover:text-white"
                        title="Move up"
                      >
                        <ArrowUp className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => moveTask(idx, "down")}
                        disabled={idx === suggestedTasks.length - 1}
                        className="rounded p-1 text-slate-500 hover:bg-slate-200 hover:text-slate-900 disabled:opacity-30 dark:hover:bg-slate-700 dark:hover:text-white"
                        title="Move down"
                      >
                        <ArrowDown className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() =>
                          setEditingTask(
                            editingTask === task.type ? null : task.type,
                          )
                        }
                        className="rounded p-1 text-slate-500 hover:bg-slate-200 hover:text-slate-900 dark:hover:bg-slate-700 dark:hover:text-white"
                        title="Edit instructions"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => removeTask(idx)}
                        className="rounded p-1 text-slate-500 hover:bg-red-500/20 hover:text-red-400"
                        title="Remove"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Add available task */}
            {availableTasks.length > 0 && (
              <div className="mt-4">
                <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-slate-500">
                  More Tasks Available
                </p>
                <div className="flex flex-wrap gap-2">
                  {availableTasks.map((task) => (
                    <button
                      key={task.type}
                      onClick={() => addFromAvailable(task)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-slate-400 px-3 py-1.5 text-xs text-slate-600 transition-all hover:border-blue-500/50 hover:bg-slate-100 hover:text-slate-900 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
                    >
                      <Plus className="h-3 w-3" />
                      {task.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Add custom task */}
            <div className="mt-4 border-t border-slate-200 pt-4 dark:border-slate-700/50">
              {addingCustomTask ? (
                <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700/40 dark:bg-slate-900/50">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-slate-300">
                      Add Custom Task
                    </span>
                    <button
                      onClick={() => setAddingCustomTask(false)}
                      className="rounded p-1 text-slate-500 hover:text-slate-900 dark:hover:text-white"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                  <div>
                    <label className="mb-1 block text-[10px] font-medium uppercase tracking-wider text-slate-500">
                      Task Name
                    </label>
                    <input
                      type="text"
                      value={customTaskForm.label}
                      onChange={(e) =>
                        setCustomTaskForm({
                          ...customTaskForm,
                          label: e.target.value,
                        })
                      }
                      placeholder="e.g. Migrate to ESM modules"
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-500 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:placeholder-slate-600"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[10px] font-medium uppercase tracking-wider text-slate-500">
                      Description
                    </label>
                    <input
                      type="text"
                      value={customTaskForm.description}
                      onChange={(e) =>
                        setCustomTaskForm({
                          ...customTaskForm,
                          description: e.target.value,
                        })
                      }
                      placeholder="What should Vigil do?"
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-500 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:placeholder-slate-600"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[10px] font-medium uppercase tracking-wider text-slate-500">
                      Instructions (optional)
                    </label>
                    <textarea
                      value={customTaskForm.instructions}
                      onChange={(e) =>
                        setCustomTaskForm({
                          ...customTaskForm,
                          instructions: e.target.value,
                        })
                      }
                      placeholder="Specific instructions for the AI..."
                      rows={2}
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-xs text-slate-900 placeholder-slate-500 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:placeholder-slate-600"
                    />
                  </div>
                  <button
                    onClick={addCustomTask}
                    disabled={!customTaskForm.label.trim()}
                    className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:opacity-50"
                  >
                    <Plus className="h-4 w-4" />
                    Add Task
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setAddingCustomTask(true)}
                  className="inline-flex items-center gap-2 rounded-lg border border-dashed border-slate-400 px-4 py-2 text-sm text-slate-600 transition-colors hover:border-blue-500/50 hover:text-slate-900 dark:border-slate-700 dark:text-slate-400 dark:hover:text-white"
                >
                  <Plus className="h-4 w-4" />
                  Add Custom Task
                </button>
              )}
            </div>
          </div>

          {/* Configuration Sections */}
          <div className="space-y-4">
            <ConfigSection title="Tests" icon={TestTube} defaultOpen>
              <div className="space-y-3">
                <Field label="Test Command">
                  <input
                    type="text"
                    value={
                      ((config.tests as Record<string, unknown>)
                        ?.command as string) || ""
                    }
                    onChange={(e) =>
                      updateConfig("tests", "command", e.target.value)
                    }
                    placeholder="npm test, pytest, go test ./..."
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm text-slate-900 placeholder-slate-500 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                  />
                </Field>
                <p className="text-xs text-slate-500">
                  Command to run your test suite. Leave empty if no tests.
                </p>
              </div>
            </ConfigSection>

            <ConfigSection title="Benchmarks" icon={BarChart3}>
              <div className="space-y-3">
                <Field label="Benchmark Command">
                  <input
                    type="text"
                    value={
                      ((config.benchmarks as Record<string, unknown>)
                        ?.command as string) || ""
                    }
                    onChange={(e) =>
                      updateConfig("benchmarks", "command", e.target.value)
                    }
                    placeholder="npm run benchmark, pytest --benchmark-only"
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm text-slate-900 placeholder-slate-500 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                  />
                </Field>
                <p className="text-xs text-slate-500">
                  Optional. Vigil will revert changes that cause performance
                  regressions.
                </p>
              </div>
            </ConfigSection>

            <ConfigSection title="LLM Provider" icon={FileCode}>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Provider">
                  <select
                    value={
                      ((config.provider as Record<string, unknown>)
                        ?.type as string) || "ollama"
                    }
                    onChange={(e) =>
                      updateConfig("provider", "type", e.target.value)
                    }
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                  >
                    <option value="ollama">Ollama (Local)</option>
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                  </select>
                </Field>
                <Field label="Model">
                  <input
                    type="text"
                    value={
                      ((config.provider as Record<string, unknown>)
                        ?.model as string) || ""
                    }
                    onChange={(e) =>
                      updateConfig("provider", "model", e.target.value)
                    }
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                  />
                </Field>
              </div>
            </ConfigSection>

            <ConfigSection title="Controls" icon={Settings2}>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Work Branch">
                  <input
                    type="text"
                    value={
                      ((config.controls as Record<string, unknown>)
                        ?.work_branch as string) || "vigil-improvements"
                    }
                    onChange={(e) =>
                      updateConfig("controls", "work_branch", e.target.value)
                    }
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                  />
                </Field>
                <Field label="Max Iterations/Day">
                  <input
                    type="number"
                    value={
                      ((config.controls as Record<string, unknown>)
                        ?.max_iterations_per_day as number) || 100
                    }
                    onChange={(e) =>
                      updateConfig(
                        "controls",
                        "max_iterations_per_day",
                        Number(e.target.value),
                      )
                    }
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                  />
                </Field>
              </div>
            </ConfigSection>
          </div>

          {/* Apply Button */}
          <div className="flex items-center justify-between">
            <button
              onClick={() => setStep("select")}
              className="rounded-lg px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200 dark:text-slate-300 dark:hover:bg-slate-700/50"
            >
              Back
            </button>
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-500">
                {suggestedTasks.length} task
                {suggestedTasks.length !== 1 ? "s" : ""} configured
              </span>
              <button
                onClick={applyConfig}
                disabled={applying || suggestedTasks.length === 0}
                className="inline-flex items-center gap-2 rounded-lg bg-green-600 px-6 py-2 text-sm font-medium text-white transition-colors hover:bg-green-500 disabled:opacity-50"
              >
                {applying ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                {applying ? "Applying..." : "Apply & Start"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Step 4: Ready */}
      {step === "ready" && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-green-600/20">
            <Check className="h-8 w-8 text-green-400" />
          </div>
          <h2 className="mt-4 text-xl font-bold text-slate-900 dark:text-white">
            Project Configured!
          </h2>
          <p className="mt-2 text-sm text-slate-400">
            Vigil is now configured for{" "}
            <span className="font-medium text-slate-900 dark:text-white">
              {(config?.project as Record<string, unknown>)?.name as string}
            </span>
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Configuration saved to {selectedPath}/vigil.yaml
          </p>
          <div className="mt-3 rounded-lg bg-slate-100 px-4 py-2 text-xs text-slate-600 dark:bg-slate-800/50 dark:text-slate-400">
            {suggestedTasks.length} iteration task
            {suggestedTasks.length !== 1 ? "s" : ""} configured
          </div>
          <button
            onClick={() => navigate("/")}
            className="mt-6 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-500"
          >
            <Play className="h-4 w-4" />
            Go to Dashboard
          </button>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  color = "white",
}: {
  label: string;
  value: string;
  color?: "white" | "green" | "slate";
}) {
  const colorClass = {
    white: "text-slate-900 dark:text-white",
    green: "text-green-700 dark:text-green-400",
    slate: "text-slate-600 dark:text-slate-500",
  }[color];

  return (
    <div className="rounded-lg bg-slate-100/90 p-3 dark:bg-slate-900/50">
      <div className="text-xs text-slate-600 dark:text-slate-400">{label}</div>
      <div className={clsx("mt-1 text-sm font-medium", colorClass)}>
        {value}
      </div>
    </div>
  );
}

function ConfigSection({
  title,
  icon: Icon,
  children,
  defaultOpen = false,
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
        className="flex w-full items-center gap-3 px-5 py-3 text-left"
      >
        <Icon className="h-4 w-4 text-blue-600 dark:text-blue-400" />
        <span className="flex-1 text-sm font-medium text-slate-900 dark:text-white">{title}</span>
        <ChevronRight
          className={clsx(
            "h-4 w-4 text-slate-500 transition-transform",
            open && "rotate-90",
          )}
        />
      </button>
      {open && (
        <div className="border-t border-slate-200 px-5 py-4 dark:border-slate-700/50">{children}</div>
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
      <label className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
        {label}
      </label>
      {children}
    </div>
  );
}
