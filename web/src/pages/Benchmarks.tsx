import { useState, useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { BarChart3, TrendingUp, Award, Activity } from "lucide-react";
import clsx from "clsx";
import { StatCard } from "@/components/StatCard";
import { useTheme } from "@/context/ThemeContext";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";

type Range = "50" | "100" | "all";

export function Benchmarks() {
  const { resolved: theme } = useTheme();
  const { data: benchmarks, loading } = usePolling(
    () => api.getBenchmarks(),
    10000,
  );
  const [range, setRange] = useState<Range>("50");

  const filtered = useMemo(() => {
    if (!benchmarks) return [];
    const sorted = [...benchmarks].sort((a, b) => a.iteration - b.iteration);
    if (range === "all") return sorted;
    return sorted.slice(-Number(range));
  }, [benchmarks, range]);

  const metricKeys = useMemo(() => {
    if (!filtered.length) return [];
    const keys = new Set<string>();
    filtered.forEach((b) => Object.keys(b.results).forEach((k) => keys.add(k)));
    return Array.from(keys);
  }, [filtered]);

  const chartData = useMemo(() => {
    return filtered.map((b) => ({
      iteration: b.iteration,
      ...b.results,
    }));
  }, [filtered]);

  const latest = filtered.at(-1);
  const first = filtered.at(0);

  const latestValue =
    latest && metricKeys[0] ? latest.results[metricKeys[0]] : null;
  const bestValue =
    metricKeys[0] != null
      ? Math.max(...filtered.map((b) => b.results[metricKeys[0]!] ?? 0))
      : null;
  const avgValue =
    metricKeys[0] != null && filtered.length > 0
      ? filtered.reduce(
          (sum, b) => sum + (b.results[metricKeys[0]!] ?? 0),
          0,
        ) / filtered.length
      : null;
  const improvementPct =
    first && latest && metricKeys[0] != null
      ? (() => {
          const start = first.results[metricKeys[0]!];
          const end = latest.results[metricKeys[0]!];
          if (start != null && end != null && start !== 0) {
            return ((end - start) / Math.abs(start)) * 100;
          }
          return null;
        })()
      : null;

  const colors = [
    "#3b82f6",
    "#10b981",
    "#f59e0b",
    "#ef4444",
    "#8b5cf6",
    "#ec4899",
  ];

  if (loading && !benchmarks) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
      </div>
    );
  }

  if (!benchmarks || benchmarks.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Benchmarks</h1>
        <div className="rounded-xl border border-slate-200 bg-white/90 py-16 text-center dark:border-slate-700/50 dark:bg-slate-800/30">
          <BarChart3 className="mx-auto h-12 w-12 text-slate-400 dark:text-slate-600" />
          <h2 className="mt-4 text-lg font-semibold text-slate-900 dark:text-white">
            No benchmark data yet
          </h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-600 dark:text-slate-400">
            Configure benchmarks in Settings to track performance over time.
            Vigil will run your benchmark command periodically and record the
            results.
          </p>
          <div className="mx-auto mt-6 max-w-sm rounded-lg border border-slate-200 bg-slate-50 p-4 text-left dark:border-slate-700/50 dark:bg-slate-900">
            <p className="mb-2 text-xs font-medium text-slate-600 dark:text-slate-400">
              Example configuration:
            </p>
            <pre className="font-mono text-xs text-slate-800 dark:text-slate-300">
              {`benchmarks:
  enabled: true
  command: "pytest --benchmark-json=out.json"
  regression_threshold: 5.0`}
            </pre>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Benchmarks</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            {filtered.length} data points •{" "}
            {metricKeys.length} metric{metricKeys.length !== 1 && "s"}
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-100 p-1 dark:border-slate-700/50 dark:bg-slate-800/50">
          {(["50", "100", "all"] as const).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={clsx(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-all duration-200",
                range === r
                  ? "bg-blue-600 text-white"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white",
              )}
            >
              {r === "all" ? "All" : `Last ${r}`}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Latest"
          value={latestValue != null ? latestValue.toFixed(2) : "—"}
          subtitle={metricKeys[0] ?? ""}
          icon={Activity}
        />
        <StatCard
          title="Best"
          value={bestValue != null ? bestValue.toFixed(2) : "—"}
          icon={Award}
        />
        <StatCard
          title="Average"
          value={avgValue != null ? avgValue.toFixed(2) : "—"}
          icon={BarChart3}
        />
        <StatCard
          title="Improvement"
          value={
            improvementPct != null
              ? `${improvementPct > 0 ? "+" : ""}${improvementPct.toFixed(1)}%`
              : "—"
          }
          icon={TrendingUp}
          trend={
            improvementPct != null
              ? improvementPct > 0
                ? "up"
                : improvementPct < 0
                  ? "down"
                  : "neutral"
              : undefined
          }
        />
      </div>

      <div className="rounded-xl border border-slate-200 bg-white/90 p-6 dark:border-slate-700/50 dark:bg-slate-800/50">
        <h2 className="mb-4 text-base font-semibold text-slate-900 dark:text-white">
          Performance Over Time
        </h2>
        <ResponsiveContainer width="100%" height={400}>
          <LineChart data={chartData}>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke={theme === "dark" ? "#1e293b" : "#e2e8f0"}
            />
            <XAxis
              dataKey="iteration"
              stroke={theme === "dark" ? "#64748b" : "#64748b"}
              fontSize={12}
              tickLine={false}
            />
            <YAxis stroke={theme === "dark" ? "#64748b" : "#64748b"} fontSize={12} tickLine={false} />
            <Tooltip
              contentStyle={{
                backgroundColor: theme === "dark" ? "#1e293b" : "#f8fafc",
                border: theme === "dark" ? "1px solid #334155" : "1px solid #e2e8f0",
                borderRadius: "8px",
                fontSize: "12px",
                color: theme === "dark" ? "#e2e8f0" : "#0f172a",
              }}
              labelStyle={{ color: theme === "dark" ? "#94a3b8" : "#64748b" }}
            />
            {metricKeys.map((key, i) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={colors[i % colors.length]}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white/90 dark:border-slate-700/50 dark:bg-slate-800/50">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-700/50">
          <h2 className="text-base font-semibold text-slate-900 dark:text-white">
            Benchmark History
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700/50">
                <th className="px-6 py-3 text-xs font-medium tracking-wide text-slate-500 uppercase dark:text-slate-400">
                  Iteration
                </th>
                <th className="px-6 py-3 text-xs font-medium tracking-wide text-slate-500 uppercase dark:text-slate-400">
                  Timestamp
                </th>
                {metricKeys.map((k) => (
                  <th
                    key={k}
                    className="px-6 py-3 text-xs font-medium tracking-wide text-slate-500 uppercase dark:text-slate-400"
                  >
                    {k}
                  </th>
                ))}
                <th className="px-6 py-3 text-xs font-medium tracking-wide text-slate-500 uppercase dark:text-slate-400">
                  Delta
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {[...filtered].reverse().map((b) => (
                <tr
                  key={b.iteration}
                  className="transition-colors hover:bg-slate-100 dark:hover:bg-slate-800/50"
                >
                  <td className="px-6 py-3 font-mono text-slate-900 dark:text-white">
                    #{b.iteration}
                  </td>
                  <td className="px-6 py-3 text-slate-600 dark:text-slate-400">
                    {new Date(b.timestamp).toLocaleString()}
                  </td>
                  {metricKeys.map((k) => (
                    <td key={k} className="px-6 py-3 font-mono text-slate-800 dark:text-slate-300">
                      {b.results[k]?.toFixed(2) ?? "—"}
                    </td>
                  ))}
                  <td className="px-6 py-3">
                    {b.delta_pct != null ? (
                      <span
                        className={clsx(
                          "font-mono text-xs font-medium",
                          b.delta_pct > 0
                            ? "text-green-400"
                            : b.delta_pct < 0
                              ? "text-red-400"
                              : "text-slate-400",
                        )}
                      >
                        {b.delta_pct > 0 ? "+" : ""}
                        {b.delta_pct.toFixed(2)}%
                      </span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
