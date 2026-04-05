import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import clsx from "clsx";
import {
  LayoutDashboard,
  ListTodo,
  BarChart3,
  ScrollText,
  Settings,
  FolderPlus,
} from "lucide-react";
import { StatusBadge } from "./StatusBadge";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/setup", icon: FolderPlus, label: "New Project" },
  { to: "/tasks", icon: ListTodo, label: "Tasks" },
  { to: "/benchmarks", icon: BarChart3, label: "Benchmarks" },
  { to: "/logs", icon: ScrollText, label: "Logs" },
  { to: "/settings", icon: Settings, label: "Settings" },
] as const;

export function Layout({ children }: { children: ReactNode }) {
  const { data: status } = usePolling(() => api.getStatus(), 3000);

  const agentStatus = status
    ? status.running
      ? status.paused
        ? "paused"
        : "running"
      : "stopped"
    : "stopped";

  return (
    <div className="flex h-screen overflow-hidden bg-slate-100 dark:bg-slate-950">
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white/80 dark:border-slate-800 dark:bg-slate-900/50">
        <div className="flex h-16 items-center gap-3 border-b border-slate-200 px-6 dark:border-slate-800">
          <img
            src="/favicon.svg"
            alt=""
            width={32}
            height={32}
            className="h-8 w-8 shrink-0 drop-shadow-[0_0_14px_rgba(34,211,238,0.45)]"
            aria-hidden
          />
          <span className="bg-gradient-to-r from-cyan-600 via-slate-800 to-violet-700 bg-clip-text text-lg font-bold tracking-[0.2em] text-transparent dark:from-cyan-200 dark:via-white dark:to-violet-200">
            VIGIL
          </span>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-4">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200",
                  isActive
                    ? "bg-blue-600/15 text-blue-700 dark:bg-blue-600/10 dark:text-blue-400"
                    : "text-slate-600 hover:bg-slate-200/80 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/50 dark:hover:text-white",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="space-y-3 border-t border-slate-200 p-4 dark:border-slate-800">
          <StatusBadge status={agentStatus} />
          {status?.provider && (
            <p className="truncate font-mono text-xs text-slate-500 dark:text-slate-500">
              {status.provider}
            </p>
          )}
          {status?.branch && (
            <p className="truncate font-mono text-xs text-slate-600 dark:text-slate-600">
              {status.branch}
            </p>
          )}
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl p-6">{children}</div>
      </main>
    </div>
  );
}
