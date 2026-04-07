import { useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  FileCode,
  GitCommitHorizontal,
  Clock,
  Bot,
  Loader2,
  Timer,
  Zap,
  FlaskConical,
  Terminal,
  MessageSquare,
  AlertTriangle,
  GitBranch,
} from "lucide-react";
import clsx from "clsx";
import type { Iteration, IterationStep } from "@/types";

export function formatIterationDuration(ms: number): string {
  if (!ms) return "";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

function CollapsibleSection({
  title,
  icon,
  defaultOpen = false,
  badge,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  defaultOpen?: boolean;
  badge?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/80 dark:border-slate-700/40 dark:bg-slate-900/30">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-600 transition-colors hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-300"
      >
        {icon}
        {title}
        {badge && (
          <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-medium normal-case text-slate-600 dark:bg-slate-700/50 dark:text-slate-400">
            {badge}
          </span>
        )}
        <span className="ml-auto">
          {open ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </span>
      </button>
      {open && <div className="border-t border-slate-200 px-4 py-3 dark:border-slate-800/50">{children}</div>}
    </div>
  );
}

function DiffViewer({ diff }: { diff: string }) {
  if (!diff) return null;
  const allLines = diff.split("\n");
  const lines = allLines.slice(0, 400);
  return (
    <pre className="max-h-[500px] overflow-auto rounded-lg border border-slate-200 bg-slate-100 p-3 font-mono text-[11px] leading-relaxed dark:border-transparent dark:bg-slate-950">
      {lines.map((line, i) => {
        let cls = "text-slate-600 dark:text-slate-400";
        if (line.startsWith("+") && !line.startsWith("+++")) cls = "bg-green-500/10 text-green-800 dark:text-green-400 dark:bg-green-500/5";
        else if (line.startsWith("-") && !line.startsWith("---")) cls = "bg-red-500/10 text-red-700 dark:text-red-400 dark:bg-red-500/5";
        else if (line.startsWith("@@")) cls = "text-blue-700 dark:text-blue-400";
        else if (line.startsWith("diff ") || line.startsWith("index ")) cls = "font-semibold text-slate-600 dark:text-slate-500";
        return (
          <div key={i} className={clsx("px-1", cls)}>
            {line || "\u00A0"}
          </div>
        );
      })}
      {allLines.length > 400 && (
        <div className="mt-2 text-center text-xs text-slate-600 dark:text-slate-500">
          ... {allLines.length - 400} more lines
        </div>
      )}
    </pre>
  );
}

export function StepTimeline({
  steps,
  live = false,
}: {
  steps: IterationStep[];
  live?: boolean;
}) {
  if (!steps || steps.length === 0) return null;
  return (
    <div className="space-y-0">
      {steps.map((step, i) => {
        const isRunning = live && step.status === "running";
        return (
          <div key={i} className="flex gap-3">
            <div className="flex flex-col items-center">
              <div
                className={clsx(
                  "mt-1.5 h-2.5 w-2.5 rounded-full",
                  isRunning
                    ? "animate-pulse bg-blue-400"
                    : step.status === "done"
                      ? "bg-green-500/60"
                      : "bg-slate-400 dark:bg-slate-600",
                )}
              />
              {i < steps.length - 1 && <div className="w-px flex-1 bg-slate-300 dark:bg-slate-700/50" />}
            </div>
            <div className="min-w-0 flex-1 pb-3">
              <div className="flex items-center gap-2">
                <span
                  className={clsx(
                    "text-xs font-medium",
                    isRunning ? "text-blue-700 dark:text-blue-300" : "text-slate-700 dark:text-slate-300",
                  )}
                >
                  {step.label}
                </span>
                {isRunning && <Loader2 className="h-3 w-3 animate-spin text-blue-600 dark:text-blue-400" />}
                {step.duration_ms > 0 && (
                  <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] text-slate-600 dark:bg-slate-800 dark:text-slate-500">
                    {formatIterationDuration(step.duration_ms)}
                  </span>
                )}
              </div>
              {step.detail && (
                <div className="mt-1">
                  {typeof step.detail === "string" ? (
                    <p className="max-h-96 overflow-y-auto whitespace-pre-wrap text-[11px] leading-relaxed text-slate-600 dark:text-slate-400">
                      {step.detail}
                    </p>
                  ) : (
                    <pre className="max-h-40 overflow-auto rounded border border-slate-200 bg-slate-100 p-2 text-[10px] leading-relaxed text-slate-700 dark:border-transparent dark:bg-slate-950 dark:text-slate-500">
                      {JSON.stringify(step.detail, null, 2)}
                    </pre>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function PromptViewer({ content }: { content: string }) {
  if (!content) return null;
  return (
    <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-100 p-3 font-mono text-[11px] leading-relaxed text-slate-800 dark:border-transparent dark:bg-slate-950 dark:text-slate-300">
      {content}
    </pre>
  );
}

/**
 * Full iteration detail: timeline, prompts, LLM output, files, diff, tests — same content as Logs expand view.
 */
export function IterationDetailView({
  detail,
  loading,
  emptyHint,
}: {
  detail: Iteration | null;
  loading?: boolean;
  emptyHint?: string;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-blue-600 dark:text-blue-400" />
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="py-12 text-center text-slate-600 dark:text-slate-400">
        {emptyHint ?? "Failed to load iteration details."}
      </div>
    );
  }

  const it = detail;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-lg bg-slate-100/90 px-4 py-3 dark:bg-slate-800/40">
        <span className="max-w-full whitespace-pre-wrap break-words text-sm text-slate-800 dark:text-slate-300">
          {it.summary}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-3 text-[11px] text-slate-600 dark:text-slate-500">
          {it.provider_name && (
            <span className="flex items-center gap-1 rounded bg-slate-200 px-1.5 py-0.5 text-slate-700 dark:bg-slate-700/50 dark:text-slate-400">
              <Bot className="h-3 w-3" /> {it.provider_name}
            </span>
          )}
          {it.branch_name && (
            <span className="flex items-center gap-1 rounded bg-slate-200 px-1.5 py-0.5 dark:bg-slate-700/50">
              <GitBranch className="h-3 w-3 text-cyan-500" />
              <code className="font-mono text-cyan-400">{it.branch_name}</code>
            </span>
          )}
          {it.duration_ms ? (
            <span className="flex items-center gap-1">
              <Timer className="h-3 w-3" /> {formatIterationDuration(it.duration_ms)}
            </span>
          ) : null}
          {it.llm_tokens ? (
            <span className="flex items-center gap-1">
              <Zap className="h-3 w-3" /> {it.llm_tokens} tokens
            </span>
          ) : null}
          {it.llm_duration_s ? (
            <span className="flex items-center gap-1">
              <Timer className="h-3 w-3" /> LLM {it.llm_duration_s}s
            </span>
          ) : null}
          {it.commit_hash && (
            <span className="flex items-center gap-1">
              <GitCommitHorizontal className="h-3 w-3" />
              <code className="font-mono text-cyan-400">{it.commit_hash.slice(0, 8)}</code>
            </span>
          )}
        </div>
      </div>

      {it.steps && it.steps.length > 0 && (
        <CollapsibleSection
          title="Execution timeline"
          icon={<Clock className="h-3 w-3" />}
          defaultOpen
          badge={`${it.steps.length} steps`}
        >
          <StepTimeline steps={it.steps} />
        </CollapsibleSection>
      )}

      {(it.llm_prompt_system || it.llm_prompt_user) && (
        <CollapsibleSection
          title="LLM prompts"
          icon={<MessageSquare className="h-3 w-3" />}
          badge={`sys: ${(it.llm_prompt_system?.length ?? 0).toLocaleString()} · user: ${(it.llm_prompt_user?.length ?? 0).toLocaleString()} chars`}
        >
          <div className="space-y-3">
            {it.llm_prompt_system && (
              <div>
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-500">
                  System prompt
                </p>
                <PromptViewer content={it.llm_prompt_system} />
              </div>
            )}
            {it.llm_prompt_user && (
              <div>
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-500">
                  User prompt (task + context)
                </p>
                <PromptViewer content={it.llm_prompt_user} />
              </div>
            )}
          </div>
        </CollapsibleSection>
      )}

      {it.llm_response && (
        <CollapsibleSection
          title="LLM response"
          icon={<Bot className="h-3 w-3" />}
          badge={`${it.llm_response.length.toLocaleString()} chars`}
          defaultOpen
        >
          <pre className="max-h-[min(70vh,32rem)] overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-100 p-3 font-mono text-[11px] leading-relaxed text-slate-800 dark:border-transparent dark:bg-slate-950 dark:text-slate-300">
            {it.llm_response}
          </pre>
        </CollapsibleSection>
      )}

      {it.files_changed && it.files_changed.length > 0 && (
        <CollapsibleSection
          title="Files changed"
          icon={<FileCode className="h-3 w-3" />}
          defaultOpen
          badge={`${it.files_changed.length} files`}
        >
          <div className="space-y-1">
            {it.changes_detail && it.changes_detail.length > 0
              ? it.changes_detail.map((c, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2 rounded bg-slate-100 px-3 py-1.5 dark:bg-slate-800/50"
                  >
                    <FileCode className="h-3 w-3 shrink-0 text-slate-500" />
                    <span className="font-mono text-[11px] text-slate-800 dark:text-slate-300">{c.file}</span>
                    <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] text-slate-700 dark:bg-slate-700 dark:text-slate-400">
                      {c.action}
                    </span>
                    {c.lines_changed != null && (
                      <span className="text-[10px] text-slate-600 dark:text-slate-500">~{c.lines_changed} lines</span>
                    )}
                  </div>
                ))
              : it.files_changed.map((f) => (
                  <div key={f} className="flex items-center gap-2 rounded bg-slate-100 px-3 py-1.5 dark:bg-slate-800/50">
                    <FileCode className="h-3 w-3 shrink-0 text-slate-500" />
                    <span className="font-mono text-[11px] text-slate-800 dark:text-slate-300">{f}</span>
                  </div>
                ))}
          </div>
        </CollapsibleSection>
      )}

      {it.diff && (
        <CollapsibleSection
          title="Git diff"
          icon={<GitCommitHorizontal className="h-3 w-3" />}
          badge={`${it.diff.split("\n").length} lines`}
        >
          <DiffViewer diff={it.diff} />
        </CollapsibleSection>
      )}

      {it.test_output && (
        <CollapsibleSection
          title="Test output"
          icon={<FlaskConical className="h-3 w-3" />}
          badge={it.status === "tests_failed" ? "FAILED" : "output"}
        >
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-100 p-3 font-mono text-[11px] leading-relaxed text-slate-800 dark:border-transparent dark:bg-slate-950 dark:text-slate-300">
            {it.test_output}
          </pre>
        </CollapsibleSection>
      )}

      {it.benchmark_data && Object.keys(it.benchmark_data).length > 0 && (
        <CollapsibleSection title="Benchmark data" icon={<Terminal className="h-3 w-3" />}>
          <pre className="rounded-lg border border-slate-200 bg-slate-100 p-3 font-mono text-xs text-slate-800 dark:border-transparent dark:bg-slate-950 dark:text-slate-300">
            {JSON.stringify(it.benchmark_data, null, 2)}
          </pre>
        </CollapsibleSection>
      )}

      {!it.steps?.length && !it.llm_response && !it.diff && (
        <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600 dark:border-slate-700/30 dark:bg-slate-800/20 dark:text-slate-500">
          <AlertTriangle className="h-3.5 w-3.5" />
          This iteration has limited stored detail. Newer runs include timeline, prompts, and full LLM
          output here.
        </div>
      )}
    </div>
  );
}
