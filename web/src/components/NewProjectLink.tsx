import { Link } from "react-router-dom";
import { FolderPlus } from "lucide-react";
import clsx from "clsx";

/** Primary CTA to the setup wizard — use anywhere users need to register another repo. */
export function NewProjectLink({
  className,
  variant = "default",
  fromSettings = false,
}: {
  className?: string;
  /** `default` = filled accent; `subtle` = border-only for dense toolbars */
  variant?: "default" | "subtle";
  /** When true, Setup shows a short hint (save provider, then refresh LLM status). */
  fromSettings?: boolean;
}) {
  return (
    <Link
      to="/setup"
      state={fromSettings ? { fromSettings: true } : undefined}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-colors",
        variant === "default" &&
          "border border-blue-500/35 bg-blue-500/10 text-blue-800 hover:bg-blue-500/15 dark:text-blue-200",
        variant === "subtle" &&
          "border border-slate-300 text-slate-800 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800/70",
        className,
      )}
    >
      <FolderPlus className="h-3.5 w-3.5 shrink-0" />
      New project
    </Link>
  );
}
