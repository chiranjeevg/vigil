import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams, useLocation } from "react-router-dom";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { IterationDetailView } from "@/components/IterationDetailView";
import { PrStatusStrip } from "@/components/PrStatusStrip";
import type { Iteration } from "@/types";

/**
 * Full-page iteration log: branch, timeline, prompts, LLM I/O, files, diff, tests.
 * Open from Dashboard "Open full log" or navigate to /logs/iteration/:n?project=...
 */
export function IterationDetailPage() {
  const { iterationNum } = useParams();
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const projectPath = searchParams.get("project") ?? undefined;
  const num = iterationNum ? parseInt(iterationNum, 10) : NaN;
  const [detail, setDetail] = useState<Iteration | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!Number.isFinite(num) || num < 1) {
      setError("Invalid iteration number.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    api
      .getIterationDetail(num, projectPath)
      .then(setDetail)
      .catch(() => {
        setDetail(null);
        setError("Could not load this iteration. Check the project context or try again.");
      })
      .finally(() => setLoading(false));
  }, [num, projectPath]);

  useEffect(() => {
    if (loading || !detail) return;
    const anchor = location.hash.replace(/^#/, "");
    if (!anchor) return;
    const t = window.setTimeout(() => {
      document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 100);
    return () => window.clearTimeout(t);
  }, [detail, loading, location.hash]);

  const qs = projectPath ? `?project=${encodeURIComponent(projectPath)}` : "";
  const fullUrl = `${typeof window !== "undefined" ? window.location.origin : ""}/logs/iteration/${num}${qs}`;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          to="/logs"
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-slate-100 px-3 py-1.5 text-sm text-slate-800 hover:border-slate-400 hover:text-slate-900 dark:border-slate-600/60 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
          Iterations
        </Link>
        <Link
          to="/"
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-slate-100 px-3 py-1.5 text-sm text-slate-800 hover:border-slate-400 hover:text-slate-900 dark:border-slate-600/60 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
        >
          Dashboard
        </Link>
        <a
          href={fullUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900 dark:text-slate-500 dark:hover:text-slate-300"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          Open in new tab
        </a>
      </div>

      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          Iteration #{Number.isFinite(num) ? num : "—"}
        </h1>
        {projectPath && (
          <p className="mt-1 font-mono text-xs text-slate-600 dark:text-slate-500">{projectPath}</p>
        )}
      </div>

      <PrStatusStrip />

      <div className="rounded-xl border border-slate-200 bg-white/90 p-5 dark:border-slate-700/50 dark:bg-slate-800/30">
        <IterationDetailView
          detail={detail}
          loading={loading}
          emptyHint={error ?? undefined}
        />
      </div>
    </div>
  );
}
