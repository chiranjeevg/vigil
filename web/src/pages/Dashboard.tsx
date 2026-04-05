import { useState, useEffect } from "react";
import { flushSync } from "react-dom";
import { Link } from "react-router-dom";
import {
  Play,
  Pause,
  Square,
  RotateCcw,
  Hash,
  CheckCircle2,
  Shield,
  TrendingUp,
  Loader2,
  FolderOpen,
  ChevronDown,
  X,
  Trash2,
  ArrowUpDown,
} from "lucide-react";
import clsx from "clsx";
import { StatCard } from "@/components/StatCard";
import { IterationDetailView } from "@/components/IterationDetailView";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";
import { type VigilProjectListItem } from "@/lib/pathUtils";
import type { Iteration } from "@/types";

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatTimeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

const statusColors: Record<string, { bg: string; text: string; label: string }> = {
  success: { bg: "bg-green-500/10", text: "text-green-400", label: "Success" },
  no_changes: { bg: "bg-slate-500/10", text: "text-slate-400", label: "No changes" },
  tests_failed: { bg: "bg-red-500/10", text: "text-red-400", label: "Tests failed" },
  benchmark_regression: { bg: "bg-orange-500/10", text: "text-orange-400", label: "Regression" },
  safety_revert: { bg: "bg-yellow-500/10", text: "text-yellow-400", label: "Safety revert" },
  llm_error: { bg: "bg-red-500/10", text: "text-red-400", label: "LLM error" },
  dry_run: { bg: "bg-blue-500/10", text: "text-blue-400", label: "Dry run" },
};

const PAGE_SIZE = 10;

export function Dashboard() {
  const [showProjectSelector, setShowProjectSelector] = useState(false);
  const [projects, setProjects] = useState<VigilProjectListItem[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [selectedIteration, setSelectedIteration] = useState<number | null>(null);
  const [iterationDetail, setIterationDetail] = useState<Iteration | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [activityPage, setActivityPage] = useState(0);
  /** Recent activity sort: desc = newest first (matches default API), asc = oldest first */
  const [activityOrder, setActivityOrder] = useState<"asc" | "desc">("desc");

  const { data: status, error: statusError, refetch: refetchStatus } = usePolling(
    () => api.getStatus(),
    3000,
  );
  const { data: stats, refetch: refetchStats } = usePolling(() => api.getStats(), 5000);
  const { data: iterPage, refetch: refetchIterations } = usePolling(
    () =>
      api.getIterationsPage({
        limit: PAGE_SIZE,
        offset: activityPage * PAGE_SIZE,
        order: activityOrder,
      }),
    5000,
    [activityPage, activityOrder],
  );
  const iterations = iterPage?.iterations ?? [];
  const totalIterations = iterPage?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalIterations / PAGE_SIZE));
  const hasMore = iterPage?.has_more ?? false;

  useEffect(() => {
    if (!showProjectSelector) return;
    setLoadingProjects(true);
    api
      .getVigilProjects()
      .then((data) => {
        const list = data.projects || [];
        if (list.length === 0) {
          return fetch("/api/projects?scan_filesystem=true")
            .then((r) => r.json())
            .then((d: { projects?: VigilProjectListItem[] }) => d.projects || []);
        }
        return list;
      })
      .then((list) => setProjects(list))
      .catch(() => {})
      .finally(() => setLoadingProjects(false));
  }, [showProjectSelector]);

  useEffect(() => {
    if (selectedIteration !== null) {
      setLoadingDetail(true);
      api
        .getIterationDetail(selectedIteration, status?.project_path)
        .then(setIterationDetail)
        .catch(() => setIterationDetail(null))
        .finally(() => setLoadingDetail(false));
    }
  }, [selectedIteration, status?.project_path]);

  const isRunning = status?.running && !status?.paused;
  const isPaused = status?.running && status?.paused;
  const isStopped = !status?.running;

  async function handleStart() {
    try {
      await api.start();
    } catch {}
  }
  async function handlePause() {
    try {
      if (isPaused) await api.resume();
      else await api.pause();
    } catch {}
  }
  async function handleStop() {
    try {
      await api.stop();
    } catch {}
  }

  const [switching, setSwitching] = useState(false);
  const [removingPath, setRemovingPath] = useState<string | null>(null);

  async function switchProject(projectPath: string) {
    setShowProjectSelector(false);
    setSwitching(true);
    let switched = false;
    try {
      try {
        await api.switchProject(projectPath);
        switched = true;
      } catch {
        try {
          const result = await api.analyzeProject(projectPath);
          await api.applySetup(result.config, false);
          switched = true;
        } catch (e) {
          console.error("Failed to switch project:", e);
        }
      }
      if (switched) {
        flushSync(() => setActivityPage(0));
        await Promise.all([
          refetchStatus(),
          refetchStats(),
          refetchIterations(() =>
            api.getIterationsPage({
              limit: PAGE_SIZE,
              offset: 0,
              order: activityOrder,
            }),
          ),
        ]);
      }
    } finally {
      setSwitching(false);
    }
  }

  async function removeProjectFromList(proj: VigilProjectListItem) {
    const ok = window.confirm(
      `Remove "${proj.name}" from Vigil?\n\nThis removes it from the dashboard only. ` +
        `Your files and vigil.yaml on disk are not deleted. Iteration history in the database is kept but hidden.`,
    );
    if (!ok) return;
    setRemovingPath(proj.path);
    try {
      await api.removeProject(proj.path);
      const data = await api.getVigilProjects();
      setProjects(data.projects || []);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to remove project";
      window.alert(msg);
    } finally {
      setRemovingPath(null);
    }
  }

  const offline = statusError !== null;
  const projectName = status?.project_name;
  const projectPath = status?.project_path;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Dashboard</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            {offline
              ? "Unable to connect to Vigil backend"
              : `Iteration #${status?.iteration ?? 0} • ${formatUptime(status?.uptime_seconds ?? 0)} uptime`}
          </p>

          {/* Project Selector */}
          <div className="relative mt-2">
            <button
              onClick={() => setShowProjectSelector(!showProjectSelector)}
              disabled={switching}
              className="inline-flex items-center gap-2 rounded-lg bg-slate-200 px-3 py-1.5 text-sm transition-colors hover:bg-slate-300 dark:bg-slate-800 dark:hover:bg-slate-700"
            >
              {switching ? (
                <Loader2 className="h-4 w-4 animate-spin text-blue-600 dark:text-blue-400" />
              ) : (
                <FolderOpen className="h-4 w-4 text-blue-600 dark:text-blue-400" />
              )}
              <span className="font-medium text-slate-900 dark:text-white">
                {switching ? "Switching..." : projectName || "Select Project"}
              </span>
              <ChevronDown className={clsx("h-4 w-4 text-slate-500 transition-transform dark:text-slate-400", showProjectSelector && "rotate-180")} />
            </button>

            {showProjectSelector && (
              <div className="absolute left-0 top-full z-[100] mt-2 w-80 rounded-xl border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-800">
                <div className="p-2">
                  <div className="mb-2 px-2 text-xs font-semibold text-slate-500 uppercase">
                    Vigil Projects
                  </div>
                  {loadingProjects ? (
                    <div className="flex items-center justify-center py-4">
                      <Loader2 className="h-5 w-5 animate-spin text-blue-600 dark:text-blue-400" />
                    </div>
                  ) : projects.length === 0 ? (
                    <div className="px-2 py-4 text-center text-sm text-slate-600 dark:text-slate-400">
                      No projects found. Use Setup to add one.
                    </div>
                  ) : (
                    <div className="max-h-64 overflow-y-auto space-y-1">
                      {projects.map((proj) => (
                        <div
                          key={proj.path}
                          className={clsx(
                            "group flex items-center gap-1 rounded-lg pr-1 transition-colors",
                            proj.path === projectPath
                              ? "bg-blue-600/15 dark:bg-blue-600/20"
                              : "hover:bg-slate-100 dark:hover:bg-slate-700/80",
                          )}
                        >
                          <button
                            type="button"
                            onClick={() => switchProject(proj.path)}
                            disabled={switching || removingPath !== null}
                            className={clsx(
                              "flex min-w-0 flex-1 items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors",
                              proj.path === projectPath
                                ? "text-blue-700 dark:text-blue-400"
                                : "text-slate-900 dark:text-white",
                            )}
                          >
                            <FolderOpen className="h-4 w-4 flex-shrink-0" />
                            <div className="min-w-0 flex-1">
                              <div className="truncate font-medium">{proj.name}</div>
                              <div className="truncate text-xs text-slate-500">
                                {proj.iteration_count} iterations
                              </div>
                            </div>
                          </button>
                          <button
                            type="button"
                            title="Remove from Vigil list"
                            disabled={switching || removingPath !== null}
                            onClick={(e) => {
                              e.stopPropagation();
                              removeProjectFromList(proj);
                            }}
                            className="flex-shrink-0 rounded-md p-2 text-slate-500 opacity-70 transition-colors hover:bg-red-500/20 hover:text-red-400 group-hover:opacity-100"
                          >
                            {removingPath === proj.path ? (
                              <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
                            ) : (
                              <Trash2 className="h-4 w-4" />
                            )}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isStopped ? (
            <button
              onClick={handleStart}
              className="inline-flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white transition-all duration-200 hover:bg-green-500"
            >
              <Play className="h-4 w-4" />
              Start
            </button>
          ) : (
            <>
              <button
                onClick={handlePause}
                className="inline-flex items-center gap-2 rounded-lg bg-slate-600 px-4 py-2 text-sm font-medium text-white transition-all duration-200 hover:bg-slate-500 dark:bg-slate-700 dark:hover:bg-slate-600"
              >
                {isPaused ? (
                  <>
                    <RotateCcw className="h-4 w-4" />
                    Resume
                  </>
                ) : (
                  <>
                    <Pause className="h-4 w-4" />
                    Pause
                  </>
                )}
              </button>
              <button
                onClick={handleStop}
                className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition-all duration-200 hover:bg-red-500"
              >
                <Square className="h-4 w-4" />
                Stop
              </button>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Iterations"
          value={stats?.total_iterations ?? "—"}
          subtitle={`${stats?.successes ?? 0} successful`}
          icon={Hash}
        />
        <StatCard
          title="Success Rate"
          value={
            stats?.success_rate != null
              ? `${Math.round(stats.success_rate)}%`
              : "—"
          }
          subtitle={`${stats?.successes ?? 0} successful / ${stats?.failures ?? 0} failed`}
          icon={CheckCircle2}
          trend={
            stats?.success_rate != null
              ? stats.success_rate >= 70
                ? "up"
                : stats.success_rate >= 40
                  ? "neutral"
                  : "down"
              : undefined
          }
        />
        <StatCard
          title="Coverage"
          value={
            stats?.coverage_trend && stats.coverage_trend.length > 0
              ? `${Math.round(stats.coverage_trend[stats.coverage_trend.length - 1] ?? 0)}%`
              : "—"
          }
          subtitle="Test coverage"
          icon={Shield}
          trend={
            stats?.coverage_trend && stats.coverage_trend.length > 0
              ? (stats.coverage_trend[stats.coverage_trend.length - 1] ?? 0) >= 80
                ? "up"
                : "neutral"
              : undefined
          }
        />
        <StatCard
          title="No-Improve Streak"
          value={status?.no_improve_streak ?? "—"}
          subtitle="Consecutive iterations without progress"
          icon={TrendingUp}
          trend={
            status?.no_improve_streak != null
              ? status.no_improve_streak === 0
                ? "up"
                : status.no_improve_streak > 5
                  ? "down"
                  : "neutral"
              : undefined
          }
        />
      </div>

      {status?.current_task && (
        <div
          className={clsx(
            "rounded-xl border p-5",
            isRunning
              ? "animate-border-glow border-blue-500/50 bg-blue-500/5"
              : "border-slate-200 bg-slate-100/90 dark:border-slate-700/50 dark:bg-slate-800/50",
          )}
        >
          <div className="flex items-center gap-3">
            {isRunning && (
              <Loader2 className="h-5 w-5 animate-spin text-blue-600 dark:text-blue-400" />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="rounded-md bg-blue-500/15 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-500/10 dark:text-blue-400">
                  {status.current_task.type}
                </span>
                <span className="text-sm font-medium text-slate-900 dark:text-white">
                  Current Task
                </span>
              </div>
              <p className="mt-1 truncate text-sm text-slate-700 dark:text-slate-300">
                {status.current_task.description}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Iteration #{status.iteration}
                {status.daily_count > 0 &&
                  ` • ${status.daily_count} today`}
                {status.no_improve_streak > 0 &&
                  ` • ${status.no_improve_streak} streak without improvement`}
              </p>
            </div>
          </div>
        </div>
      )}

      <div>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
            Recent Activity
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            {totalIterations > 0 && (
              <span className="text-xs text-slate-500">
                {totalIterations} total iteration{totalIterations !== 1 ? "s" : ""}
              </span>
            )}
            <button
              type="button"
              onClick={() => {
                setActivityOrder((o) => (o === "desc" ? "asc" : "desc"));
                setActivityPage(0);
              }}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 transition-colors hover:border-slate-400 hover:text-slate-900 dark:border-slate-600/60 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
              title="Toggle sort by time"
            >
              <ArrowUpDown className="h-3.5 w-3.5" />
              {activityOrder === "desc" ? "Newest first" : "Oldest first"}
            </button>
          </div>
        </div>
        {iterations && iterations.length > 0 ? (
          <>
            <div className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white/90 dark:divide-slate-800 dark:border-slate-700/50 dark:bg-slate-800/30">
              {iterations.map((it) => (
                <IterationRowClickable
                  key={it.iteration}
                  iteration={it}
                  onClick={() => setSelectedIteration(it.iteration)}
                />
              ))}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="mt-3 flex items-center justify-center gap-2">
                <button
                  onClick={() => setActivityPage(0)}
                  disabled={activityPage === 0}
                  className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-200 hover:text-slate-900 disabled:opacity-30 disabled:hover:bg-transparent dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-white"
                >
                  First
                </button>
                <button
                  onClick={() => setActivityPage((p) => Math.max(0, p - 1))}
                  disabled={activityPage === 0}
                  className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-200 hover:text-slate-900 disabled:opacity-30 disabled:hover:bg-transparent dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-white"
                >
                  Prev
                </button>
                <span className="rounded-lg bg-slate-200 px-3 py-1.5 text-xs font-medium text-slate-900 dark:bg-slate-800 dark:text-white">
                  {activityPage + 1} / {totalPages}
                </span>
                <button
                  onClick={() => setActivityPage((p) => p + 1)}
                  disabled={!hasMore}
                  className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-200 hover:text-slate-900 disabled:opacity-30 disabled:hover:bg-transparent dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-white"
                >
                  Next
                </button>
                <button
                  onClick={() => setActivityPage(totalPages - 1)}
                  disabled={!hasMore}
                  className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-200 hover:text-slate-900 disabled:opacity-30 disabled:hover:bg-transparent dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-white"
                >
                  Last
                </button>
              </div>
            )}
          </>
        ) : (
          <div className="rounded-xl border border-slate-200 bg-white/90 py-12 text-center dark:border-slate-700/50 dark:bg-slate-800/30">
            <Hash className="mx-auto h-8 w-8 text-slate-400 dark:text-slate-600" />
            <p className="mt-3 text-sm text-slate-600 dark:text-slate-400">
              No iterations yet. Start Vigil to begin improving your codebase.
            </p>
          </div>
        )}
      </div>

      {/* Iteration Detail Modal */}
      {selectedIteration !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 dark:bg-black/60">
          <div className="relative max-h-[90vh] w-full max-w-4xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
            <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-6 py-4 dark:border-slate-700">
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
                <Hash className="h-5 w-5 shrink-0 text-blue-600 dark:text-blue-400" />
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                  Iteration #{selectedIteration}
                </h2>
                {iterationDetail && (
                  <span className={clsx(
                    "rounded-md px-2 py-0.5 text-xs font-medium",
                    statusColors[iterationDetail.status]?.bg ?? "bg-slate-500/10",
                    statusColors[iterationDetail.status]?.text ?? "text-slate-400"
                  )}>
                    {statusColors[iterationDetail.status]?.label || iterationDetail.status}
                  </span>
                )}
                <Link
                  to={`/logs/iteration/${selectedIteration}${status?.project_path ? `?project=${encodeURIComponent(status.project_path)}` : ""}`}
                  className="ml-auto shrink-0 rounded-lg border border-slate-300 bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-slate-400 hover:text-slate-900 sm:ml-0 dark:border-slate-600/60 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
                >
                  Open full log
                </Link>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSelectedIteration(null);
                  setIterationDetail(null);
                }}
                className="shrink-0 rounded-lg p-2 text-slate-500 hover:bg-slate-200 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="max-h-[calc(90vh-80px)] overflow-y-auto p-6">
              <IterationDetailView
                detail={iterationDetail}
                loading={loadingDetail}
                emptyHint="Failed to load iteration details."
              />
            </div>
          </div>
        </div>
      )}

      {/* Click outside to close project selector */}
      {showProjectSelector && (
        <div
          className="fixed inset-0 z-[90]"
          onClick={() => setShowProjectSelector(false)}
        />
      )}
    </div>
  );
}

function IterationRowClickable({
  iteration,
  onClick,
}: {
  iteration: Iteration;
  onClick: () => void;
}) {
  const statusStyle = statusColors[iteration.status] ?? { bg: "bg-slate-500/10", text: "text-slate-400", label: iteration.status };

  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-4 px-4 py-3 text-left transition-colors hover:bg-slate-100 dark:hover:bg-slate-800/50"
    >
      <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-slate-200 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-400">
        #{iteration.iteration}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="rounded bg-slate-200 px-1.5 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-300">
            {iteration.task_type}
          </span>
          <span className="truncate text-sm text-slate-700 dark:text-slate-300">
            {iteration.task_description}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span
          className={clsx(
            "rounded-md px-2 py-0.5 text-xs font-medium",
            statusStyle.bg,
            statusStyle.text
          )}
        >
          {statusStyle.label}
        </span>
        <span className="text-xs text-slate-500">
          {formatTimeAgo(iteration.timestamp)}
        </span>
      </div>
    </button>
  );
}
