import { useState, useEffect, useCallback, useRef } from "react";
import { Link } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  ScrollText,
  Filter,
  Wifi,
  WifiOff,
  FileCode,
  Bot,
  FolderOpen,
  Loader2,
  Timer,
  Zap,
  Activity,
  Radio,
  GitBranch,
  ChevronLeft,
  ArrowUpDown,
} from "lucide-react";
import clsx from "clsx";
import {
  IterationDetailView,
  StepTimeline,
  formatIterationDuration as formatDuration,
} from "@/components/IterationDetailView";
import { usePolling } from "@/hooks/usePolling";
import { useWebSocket } from "@/hooks/useWebSocket";
import { api } from "@/lib/api";
import { NewProjectLink } from "@/components/NewProjectLink";
import { PrStatusStrip } from "@/components/PrStatusStrip";
import {
  pathsEqual,
  type VigilProjectListItem,
} from "@/lib/pathUtils";
import type {
  Iteration,
  IterationStatus,
  IterationsPageResponse,
  VigilStats,
} from "@/types";

const PAGE_SIZE = 25;

const statusStyles: Record<
  IterationStatus,
  { dot: string; label: string; bg: string }
> = {
  success: { dot: "bg-green-500", label: "Success", bg: "bg-green-500/10 text-green-400" },
  merge_conflict: {
    dot: "bg-orange-500",
    label: "Merge conflict",
    bg: "bg-orange-500/10 text-orange-300",
  },
  no_changes: { dot: "bg-slate-500", label: "No changes", bg: "bg-slate-500/10 text-slate-400" },
  tests_failed: { dot: "bg-red-500", label: "Tests failed", bg: "bg-red-500/10 text-red-400" },
  benchmark_regression: { dot: "bg-amber-500", label: "Regression", bg: "bg-amber-500/10 text-amber-400" },
  safety_revert: { dot: "bg-amber-500", label: "Reverted", bg: "bg-amber-500/10 text-amber-400" },
  llm_error: { dot: "bg-red-500", label: "LLM error", bg: "bg-red-500/10 text-red-400" },
  config_error: { dot: "bg-red-600", label: "Config error", bg: "bg-red-600/10 text-red-300" },
  worktree_error: { dot: "bg-red-600", label: "Worktree error", bg: "bg-red-600/10 text-red-300" },
  dry_run: { dot: "bg-slate-400", label: "Dry run", bg: "bg-slate-400/10 text-slate-300" },
};

type StatusFilter = "all" | "success" | "failed";


/* ── Live Iteration Panel ────────────────────────────────────── */
function LiveIterationPanel() {
  const { data: live, refetch } = usePolling(() => api.getLiveIteration(), 1500);
  const { lastEvent } = useWebSocket();

  useEffect(() => {
    if (
      lastEvent &&
      (lastEvent.type === "iteration_step" ||
        lastEvent.type === "iteration_start" ||
        lastEvent.type === "iteration_complete")
    ) {
      refetch();
    }
  }, [lastEvent, refetch]);

  if (!live) return null;

  return (
    <div className="overflow-hidden rounded-xl border border-blue-300/40 bg-gradient-to-r from-blue-50 via-slate-50 to-slate-50 dark:border-blue-500/30 dark:from-blue-500/5 dark:via-slate-800/50 dark:to-slate-800/50">
      <div className="flex items-center gap-3 border-b border-blue-200/80 px-5 py-3 dark:border-blue-500/20">
        <Radio className="h-4 w-4 animate-pulse text-blue-600 dark:text-blue-400" />
        <span className="text-sm font-semibold text-blue-800 dark:text-blue-300">
          Live — Iteration #{live.iteration}
        </span>
        <span className="rounded bg-slate-200 px-2 py-0.5 text-xs text-slate-800 dark:bg-slate-700/50 dark:text-slate-300">
          {live.task_type}
        </span>
        <span className="flex-1 truncate text-sm text-slate-600 dark:text-slate-400">
          {live.task_description}
        </span>
        <div className="flex items-center gap-3 text-[11px] text-slate-600 dark:text-slate-500">
          {live.provider && (
            <span className="flex items-center gap-1">
              <Bot className="h-3 w-3" /> {live.provider}
            </span>
          )}
          {live.branch && (
            <span className="flex items-center gap-1">
              <GitBranch className="h-3 w-3 text-cyan-500" />
              <code className="font-mono text-cyan-400">{live.branch}</code>
            </span>
          )}
          <span className="flex items-center gap-1">
            <Timer className="h-3 w-3" /> {formatDuration(live.elapsed_ms || 0)}
          </span>
        </div>
      </div>
      <div className="px-5 py-4">
        <StepTimeline steps={live.steps || []} live />
      </div>
    </div>
  );
}

/* ── Iteration Card ──────────────────────────────────────────── */
function IterationCard({
  iteration,
  onExpand,
  expanded,
  detail,
  loadingDetail,
  projectPath,
}: {
  iteration: Iteration;
  onExpand: (num: number) => void;
  expanded: boolean;
  detail: Iteration | null;
  loadingDetail: boolean;
  projectPath: string;
}) {
  const style = statusStyles[iteration.status] ?? statusStyles.no_changes;
  const projectQs = projectPath ? `?project=${encodeURIComponent(projectPath)}` : "";

  return (
    <div className="border-b border-slate-200 last:border-0 dark:border-slate-800">
      <button
        type="button"
        onClick={() => onExpand(iteration.iteration)}
        className="flex w-full items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-slate-100 dark:hover:bg-slate-800/30"
      >
        {expanded ? <ChevronDown className="h-4 w-4 shrink-0 text-slate-500" /> : <ChevronRight className="h-4 w-4 shrink-0 text-slate-500" />}
        <span className="w-12 shrink-0 font-mono text-xs text-slate-500">#{iteration.iteration}</span>
        <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide", style.bg)}>
          <span className={clsx("mr-1.5 h-1.5 w-1.5 rounded-full", style.dot)} />
          {style.label}
        </span>
        <span className="shrink-0 rounded bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-800 dark:bg-slate-700/50 dark:text-slate-300">{iteration.task_type}</span>
        <span className="min-w-0 flex-1 truncate text-sm text-slate-800 dark:text-slate-300">{iteration.task_description}</span>
        <div className="flex shrink-0 items-center gap-2">
          {(iteration.llm_tokens ?? 0) > 0 && <span className="inline-flex items-center gap-1 text-[10px] text-slate-500"><Zap className="h-3 w-3" />{iteration.llm_tokens}tk</span>}
          {(iteration.files_changed?.length ?? 0) > 0 && <span className="inline-flex items-center gap-1 text-[10px] text-slate-500"><FileCode className="h-3 w-3" />{iteration.files_changed!.length}</span>}
          {(iteration.duration_ms ?? 0) > 0 && <span className="inline-flex items-center gap-1 text-[10px] text-slate-500"><Timer className="h-3 w-3" />{formatDuration(iteration.duration_ms!)}</span>}
          {(iteration.step_count ?? 0) > 0 && <span className="inline-flex items-center gap-1 text-[10px] text-slate-500"><Activity className="h-3 w-3" />{iteration.step_count}</span>}
        </div>
        <span className="w-28 shrink-0 text-right text-[10px] text-slate-500">
          {new Date(iteration.timestamp).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-slate-200 bg-slate-50/80 px-5 py-5 pl-12 dark:border-slate-800/50 dark:bg-slate-900/20">
          {loadingDetail ? (
            <div className="flex items-center gap-2 py-4 text-sm text-slate-600 dark:text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading iteration details...
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-end gap-2">
                <Link
                  to={`/logs/iteration/${iteration.iteration}${projectQs}`}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-800 hover:border-slate-400 hover:text-slate-900 dark:border-slate-600/60 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
                >
                  Open full log
                </Link>
                <Link
                  to={`/logs/iteration/${iteration.iteration}${projectQs}#iteration-section-diff`}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-slate-400 dark:border-slate-600/60 dark:bg-slate-900/40 dark:text-slate-300 dark:hover:border-slate-500"
                >
                  Code diff
                </Link>
                <Link
                  to={`/logs/iteration/${iteration.iteration}${projectQs}#iteration-section-llm`}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-slate-400 dark:border-slate-600/60 dark:bg-slate-900/40 dark:text-slate-300 dark:hover:border-slate-500"
                >
                  LLM
                </Link>
              </div>
              <IterationDetailView detail={detail ?? iteration} loading={false} showSectionNav={false} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Main Logs Page ──────────────────────────────────────────── */
export function Logs() {
  const [projects, setProjects] = useState<VigilProjectListItem[]>([]);
  const [selectedProject, setSelectedProject] = useState<string>("");
  const [filter, setFilter] = useState<StatusFilter>("all");
  /** Sort iteration list by time: desc = newest first (default), asc = oldest first */
  const [listOrder, setListOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [iterPage, setIterPage] = useState<IterationsPageResponse | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detailCache, setDetailCache] = useState<Record<number, Iteration>>({});
  const [loadingDetail, setLoadingDetail] = useState(false);
  const { isConnected, lastEvent } = useWebSocket();
  const { data: daemonStatus } = usePolling(() => api.getStatus(), 3000);

  /** Live panel when viewing the project the daemon is actually running (not only "no filter"). */
  const showLivePanel =
    !selectedProject ||
    pathsEqual(selectedProject, daemonStatus?.project_path);

  const statusFilter =
    filter === "all" ? undefined : filter === "success" ? "success" : "failed";

  const loadList = useCallback(async () => {
    setListLoading(true);
    try {
      const offset = (page - 1) * PAGE_SIZE;
      const r = await api.getIterationsPage({
        limit: PAGE_SIZE,
        offset,
        status: statusFilter,
        projectPath: selectedProject || undefined,
        order: listOrder,
      });
      setIterPage(r);
    } catch {
      setIterPage(null);
    } finally {
      setListLoading(false);
    }
  }, [page, statusFilter, selectedProject, listOrder]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    setPage(1);
    setExpandedId(null);
    setDetailCache({});
  }, [filter, selectedProject, listOrder]);

  const loadListRef = useRef(loadList);
  loadListRef.current = loadList;

  const { data: stats, refetch: refetchStats } = usePolling(
    () => api.getStats(selectedProject || undefined),
    10000,
    [selectedProject],
  );

  useEffect(() => {
    void refetchStats();
  }, [selectedProject, refetchStats]);

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
    if (lastEvent?.type === "iteration_complete") {
      void loadListRef.current();
      void refetchStats();
    }
  }, [lastEvent, refetchStats]);

  const handleExpand = useCallback(
    async (iterNum: number) => {
      if (expandedId === iterNum) {
        setExpandedId(null);
        return;
      }
      setExpandedId(iterNum);
      if (!detailCache[iterNum]) {
        setLoadingDetail(true);
        try {
          const detail = await api.getIterationDetail(
            iterNum,
            selectedProject || undefined,
          );
          setDetailCache((prev) => ({ ...prev, [iterNum]: detail }));
        } catch {
          /* detail unavailable */
        } finally {
          setLoadingDetail(false);
        }
      }
    },
    [expandedId, detailCache, selectedProject],
  );

  const iterations = iterPage?.iterations ?? [];
  const total = iterPage?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE) || 1);
  const rangeStart = total === 0 ? 0 : (iterPage?.offset ?? 0) + 1;
  const rangeEnd = (iterPage?.offset ?? 0) + iterations.length;

  const headerStats: VigilStats | null = stats;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 shrink-0">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Iterations</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            {headerStats ? (
              <>
                {headerStats.total_iterations} total &middot; {headerStats.successes}{" "}
                succeeded &middot; {headerStats.failures} failed
                {(headerStats.llm_tokens_total ?? 0) > 0 && (
                  <>
                    {" "}
                    &middot; {(headerStats.llm_tokens_total ?? 0).toLocaleString()}{" "}
                    tokens
                  </>
                )}
                {(headerStats.duration_ms_total ?? 0) > 0 && (
                  <>
                    {" "}
                    &middot; {formatDuration(headerStats.duration_ms_total ?? 0)} total
                    time
                  </>
                )}
              </>
            ) : (
              "Loading..."
            )}
          </p>
          <p className="mt-2 max-w-2xl text-xs leading-relaxed text-slate-500 dark:text-slate-500">
            Browse every run below. Expand a row for a summary, or open the full page for{" "}
            <strong className="text-slate-700 dark:text-slate-400">timeline</strong>,{" "}
            <strong className="text-slate-700 dark:text-slate-400">LLM prompts &amp; output</strong>,{" "}
            <strong className="text-slate-700 dark:text-slate-400">file list</strong>, and{" "}
            <strong className="text-slate-700 dark:text-slate-400">git diff</strong>. Automated{" "}
            <code className="font-mono text-[10px]">git push</code> / PRs are configured under Push &amp; PR
            (or Settings).
          </p>
        </div>
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white/90 p-2 sm:p-3 dark:border-slate-700/40 dark:bg-slate-900/40">
            <NewProjectLink variant="subtle" className="shrink-0 py-2" />
            <div className="relative min-w-[min(100%,220px)] max-w-full flex-1 basis-[200px] sm:max-w-[280px]">
              <FolderOpen className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
              <select
                value={selectedProject}
                onChange={(e) => setSelectedProject(e.target.value)}
                className="w-full appearance-none rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-8 text-xs font-medium text-slate-800 outline-none transition-colors hover:border-slate-400 focus:border-blue-500 dark:border-slate-700/50 dark:bg-slate-800/50 dark:text-slate-300 dark:hover:border-slate-600"
                aria-label="Project for iteration history"
              >
                <option value="">
                  Active project — history + live
                </option>
                {projects.map((p) => (
                  <option key={p.path} value={p.path}>
                    {p.name}
                    {" — history"}
                    {pathsEqual(p.path, daemonStatus?.project_path)
                      ? " (active)"
                      : ""}{" "}
                    ({p.iteration_count} iters)
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
            </div>
            <span
              className={clsx(
                "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-100 px-2.5 text-xs dark:border-slate-700/50 dark:bg-slate-800/50",
                isConnected ? "text-green-700 dark:text-green-400" : "text-slate-500",
              )}
            >
              {isConnected ? (
                <Wifi className="h-3.5 w-3.5" />
              ) : (
                <WifiOff className="h-3.5 w-3.5" />
              )}
              {isConnected ? "Live" : "Polling"}
            </span>
            <div className="flex h-9 items-center gap-0.5 rounded-lg border border-slate-200 bg-slate-100 px-1 dark:border-slate-700/50 dark:bg-slate-800/50">
              <Filter className="ml-1 h-3.5 w-3.5 shrink-0 text-slate-500" />
              {(["all", "success", "failed"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setFilter(f)}
                  className={clsx(
                    "rounded-md px-2.5 py-1.5 text-xs font-medium capitalize transition-all duration-200",
                    filter === f
                      ? "bg-blue-600 text-white"
                      : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white",
                  )}
                >
                  {f}
                </button>
              ))}
            </div>
            <div className="ml-auto flex h-9 items-center gap-0.5 rounded-lg border border-slate-200 bg-slate-100 px-1 dark:border-slate-700/50 dark:bg-slate-800/50">
              <ArrowUpDown className="ml-1 h-3.5 w-3.5 shrink-0 text-slate-500" />
              <button
                type="button"
                onClick={() => setListOrder("desc")}
                className={clsx(
                  "rounded-md px-2.5 py-1.5 text-xs font-medium transition-all duration-200",
                  listOrder === "desc"
                    ? "bg-blue-600 text-white"
                    : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white",
                )}
              >
                Newest first
              </button>
              <button
                type="button"
                onClick={() => setListOrder("asc")}
                className={clsx(
                  "rounded-md px-2.5 py-1.5 text-xs font-medium transition-all duration-200",
                  listOrder === "asc"
                    ? "bg-blue-600 text-white"
                    : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white",
                )}
              >
                Oldest first
              </button>
            </div>
        </div>
      </div>

      <PrStatusStrip />

      {selectedProject && !pathsEqual(selectedProject, daemonStatus?.project_path) && (
        <p className="rounded-lg border border-amber-400/40 bg-amber-50 px-4 py-3 text-sm text-amber-950 dark:border-amber-500/25 dark:bg-amber-500/5 dark:text-amber-200/90">
          Showing iteration history for a project that is not the active daemon. The live
          feed below matches the active project (
          <span className="font-medium text-amber-900 dark:text-amber-100">
            {daemonStatus?.project_name ?? "unknown"}
          </span>
          ). Switch the dashboard project or select &quot;Active project&quot; above to align
          both views.
        </p>
      )}

      {/* Live current iteration — same feed whenever the list is for the active project */}
      {showLivePanel && <LiveIterationPanel />}

      {/* Paginated list */}
      {listLoading && !iterPage ? (
        <div className="flex h-48 items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        </div>
      ) : iterations.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white/90 dark:border-slate-700/50 dark:bg-slate-800/30">
          <div
            className={clsx(
              "transition-opacity duration-150",
              listLoading && "pointer-events-none opacity-60",
            )}
          >
            {iterations.map((it) => (
              <IterationCard
                key={it.iteration}
                iteration={it}
                onExpand={handleExpand}
                expanded={expandedId === it.iteration}
                detail={detailCache[it.iteration] ?? null}
                loadingDetail={loadingDetail && expandedId === it.iteration}
                projectPath={selectedProject}
              />
            ))}
          </div>
          {total > 0 && (
            <div className="flex flex-col gap-3 border-t border-slate-200 px-4 py-3 sm:flex-row sm:items-center sm:justify-between dark:border-slate-800/60">
              <p className="text-xs text-slate-600 dark:text-slate-500">
                Showing{" "}
                <span className="font-medium text-slate-800 dark:text-slate-400">
                  {rangeStart}–{rangeEnd}
                </span>{" "}
                of <span className="font-medium text-slate-800 dark:text-slate-400">{total}</span>
                {filter !== "all" && (
                  <span className="text-slate-500 dark:text-slate-600"> (filtered)</span>
                )}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={page <= 1 || listLoading}
                  onClick={() => setPage(1)}
                  className="rounded-lg border border-slate-300 bg-slate-100 px-2.5 py-1.5 text-xs text-slate-800 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-600/50 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:bg-slate-700"
                >
                  First
                </button>
                <button
                  type="button"
                  disabled={page <= 1 || listLoading}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-slate-100 px-2.5 py-1.5 text-xs text-slate-800 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-600/50 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:bg-slate-700"
                >
                  <ChevronLeft className="h-3.5 w-3.5" /> Prev
                </button>
                <span className="px-2 text-xs tabular-nums text-slate-700 dark:text-slate-400">
                  Page {page} / {totalPages}
                </span>
                <button
                  type="button"
                  disabled={!iterPage?.has_more || listLoading}
                  onClick={() => setPage((p) => p + 1)}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-slate-100 px-2.5 py-1.5 text-xs text-slate-800 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-600/50 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:bg-slate-700"
                >
                  Next <ChevronRight className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  disabled={page >= totalPages || listLoading}
                  onClick={() => setPage(totalPages)}
                  className="rounded-lg border border-slate-300 bg-slate-100 px-2.5 py-1.5 text-xs text-slate-800 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-600/50 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:bg-slate-700"
                >
                  Last
                </button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-xl border border-slate-200 bg-white/90 py-16 text-center dark:border-slate-700/50 dark:bg-slate-800/30">
          <ScrollText className="mx-auto h-12 w-12 text-slate-400 dark:text-slate-600" />
          <h2 className="mt-4 text-lg font-semibold text-slate-900 dark:text-white">No logs to show</h2>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            {filter !== "all"
              ? "Try changing the filter to see more results."
              : selectedProject
                ? "No iterations found for this project."
                : "Iterations will appear here once Vigil starts running."}
          </p>
        </div>
      )}
    </div>
  );
}
