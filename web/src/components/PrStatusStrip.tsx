import { Link } from "react-router-dom";
import { GitBranch, Settings2 } from "lucide-react";
import clsx from "clsx";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";

/**
 * Compact git push / gh PR readiness (GET /api/pr/status) with link to Settings.
 */
export function PrStatusStrip() {
  const { data: pr } = usePolling(() => api.getPrStatus(), 8000);

  if (!pr) return null;

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white/90 px-4 py-3 dark:border-slate-700/50 dark:bg-slate-800/40 lg:flex-row lg:items-start lg:justify-between">
      <div className="flex min-w-0 items-center gap-2">
        <GitBranch className="h-4 w-4 shrink-0 text-slate-500 dark:text-slate-400" />
        <span className="text-sm font-semibold text-slate-900 dark:text-white">Push &amp; GitHub PR</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-400">
        <span>
          Workflow:{" "}
          <span className={pr.enabled ? "text-emerald-700 dark:text-emerald-400" : "text-slate-500"}>
            {pr.enabled ? "enabled" : "off"}
          </span>
        </span>
        <span>
          Push:{" "}
          <span
            className={clsx(
              pr.push_enabled ? "text-emerald-700 dark:text-emerald-400" : "text-amber-800 dark:text-amber-300",
            )}
          >
            {pr.push_enabled ? "ready" : "blocked"}
          </span>
        </span>
        <span>
          <code className="font-mono text-[10px]">gh pr create</code>:{" "}
          <span
            className={clsx(
              pr.gh_pr_enabled ? "text-emerald-700 dark:text-emerald-400" : "text-amber-800 dark:text-amber-300",
            )}
          >
            {pr.gh_pr_enabled ? "ready" : "blocked"}
          </span>
        </span>
      </div>
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:gap-3 lg:ml-auto lg:max-w-xl">
        <p className="min-w-0 flex-1 text-[11px] leading-snug text-slate-500 dark:text-slate-500" title={pr.preflight_message}>
          {pr.preflight_message}
        </p>
        <Link
          to="/settings#settings-pr"
          className="inline-flex shrink-0 items-center gap-1.5 self-start rounded-lg border border-slate-300 bg-slate-100 px-2.5 py-1.5 text-xs font-medium text-slate-800 hover:border-slate-400 dark:border-slate-600/60 dark:bg-slate-800/80 dark:text-slate-200 dark:hover:border-slate-500"
        >
          <Settings2 className="h-3.5 w-3.5" />
          Configure
        </Link>
      </div>
    </div>
  );
}
