import clsx from "clsx";

type Status = "running" | "paused" | "stopped";

const config: Record<Status, { label: string; dot: string; text: string }> = {
  running: {
    label: "Running",
    dot: "bg-green-500 animate-pulse-dot",
    text: "text-green-400",
  },
  paused: {
    label: "Paused",
    dot: "bg-amber-500",
    text: "text-amber-400",
  },
  stopped: {
    label: "Stopped",
    dot: "bg-red-500",
    text: "text-red-400",
  },
};

export function StatusBadge({
  status,
  size = "sm",
}: {
  status: Status;
  size?: "sm" | "md";
}) {
  const { label, dot, text } = config[status];

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 font-medium",
        size === "sm" ? "text-xs" : "text-sm",
        "border-slate-200 bg-slate-100/90 dark:border-slate-700/50 dark:bg-slate-800/50",
      )}
    >
      <span className={clsx("h-2 w-2 rounded-full", dot)} />
      <span className={text}>{label}</span>
    </span>
  );
}
