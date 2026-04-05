import type { LucideIcon } from "lucide-react";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import clsx from "clsx";

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: LucideIcon;
  trend?: "up" | "down" | "neutral";
}

const trendConfig = {
  up: { icon: TrendingUp, color: "text-green-400" },
  down: { icon: TrendingDown, color: "text-red-400" },
  neutral: { icon: Minus, color: "text-slate-400" },
};

export function StatCard({ title, value, subtitle, icon: Icon, trend }: StatCardProps) {
  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-800/50 p-5 transition-all duration-200 hover:border-slate-600/50 hover:bg-slate-800/70">
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium tracking-wide text-slate-400 uppercase">
            {title}
          </p>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-white">
            {value}
          </p>
          {subtitle && (
            <p className="mt-1 line-clamp-2 text-xs text-slate-500">{subtitle}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {trend && (() => {
            const { icon: TrendIcon, color } = trendConfig[trend];
            return <TrendIcon className={clsx("h-4 w-4", color)} />;
          })()}
          {Icon && (
            <div className="rounded-lg bg-slate-700/50 p-2">
              <Icon className="h-5 w-5 text-slate-300" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
