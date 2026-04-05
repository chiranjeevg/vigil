import type {
  VigilStatus,
  VigilStats,
  Iteration,
  IterationsPageResponse,
  BenchmarkEntry,
  VigilConfig,
  Task,
  SuggestedTask,
} from "@/types";

const API_BASE = "/api";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  // Normalize headers so method/body from `options` are never dropped; plain object spread
  // mishandles `Headers` instances in some environments.
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: new Headers(options?.headers),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, text);
  }

  const contentType = res.headers.get("content-type");
  if (contentType?.includes("application/json")) {
    return res.json() as Promise<T>;
  }

  return {} as T;
}

export interface DeepSuggestEvent {
  type: string;
  data: Record<string, unknown>;
}

export function streamDeepSuggest(
  path: string,
  onEvent: (evt: DeepSuggestEvent) => void,
  onError: (err: Error) => void,
  onDone: () => void,
): AbortController {
  const controller = new AbortController();

  fetch(`${API_BASE}/setup/deep-suggest-stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        const text = await res.text().catch(() => "Unknown error");
        throw new Error(text);
      }
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith("data: ")) {
            try {
              const parsed = JSON.parse(trimmed.slice(6)) as DeepSuggestEvent;
              onEvent(parsed);
            } catch {
              // skip malformed SSE lines
            }
          }
        }
      }
      onDone();
    })
    .catch((err: unknown) => {
      if (err instanceof DOMException && err.name === "AbortError") return;
      onError(err instanceof Error ? err : new Error(String(err)));
    });

  return controller;
}

export const api = {
  getStatus: () => fetchApi<VigilStatus>("/status"),
  getStats: (projectPath?: string) => {
    const q = projectPath
      ? `?project_path=${encodeURIComponent(projectPath)}`
      : "";
    return fetchApi<VigilStats>(`/stats${q}`);
  },
  getLiveIteration: () =>
    fetchApi<{ live: Iteration | null }>("/iterations/live").then((r) => r.live),

  /** Paginated iteration summaries (newest first). Default page size 25. */
  getIterationsPage: (opts?: {
    limit?: number;
    offset?: number;
    status?: "success" | "failed";
    projectPath?: string;
    /** Sort by iteration timestamp: desc = newest first (default), asc = oldest first */
    order?: "asc" | "desc";
  }) => {
    const limit = opts?.limit ?? 25;
    const offset = opts?.offset ?? 0;
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (opts?.status) params.set("status", opts.status);
    if (opts?.projectPath) params.set("project_path", opts.projectPath);
    if (opts?.order && opts.order !== "desc") params.set("order", opts.order);
    return fetchApi<IterationsPageResponse>(`/iterations?${params.toString()}`);
  },

  getIterationDetail: (iterNum: number, projectPath?: string) => {
    const params = projectPath
      ? `?project_path=${encodeURIComponent(projectPath)}`
      : "";
    return fetchApi<Iteration>(`/iterations/${iterNum}${params}`);
  },
  getBenchmarks: () =>
    fetchApi<{ benchmarks: BenchmarkEntry[] }>("/benchmarks").then(
      (r) => r.benchmarks,
    ),
  getConfig: () => fetchApi<VigilConfig>("/config"),
  getConfigByProject: (path: string) =>
    fetchApi<VigilConfig>("/config/by-project", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  updateConfigByProject: (projectPath: string, config: Partial<VigilConfig>) =>
    fetchApi<{ message: string; active: boolean }>(
      `/config/by-project?project_path=${encodeURIComponent(projectPath)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      },
    ),
  getTasks: () =>
    fetchApi<{ tasks: Task[] }>("/tasks").then((r) => r.tasks),
  getGitLog: () =>
    fetchApi<{ commits: Record<string, unknown>[] }>("/git/log").then(
      (r) => r.commits,
    ),

  start: () => fetchApi<void>("/start", { method: "POST" }),
  stop: () => fetchApi<void>("/stop", { method: "POST" }),
  pause: () => fetchApi<void>("/pause", { method: "POST" }),
  resume: () => fetchApi<void>("/resume", { method: "POST" }),

  updateConfig: (config: Partial<VigilConfig>) =>
    fetchApi<void>("/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }),

  addTask: (task: Partial<Task> & { id?: string; priority?: number }) =>
    fetchApi<void>("/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(task),
    }),

  deleteTask: (id: string) =>
    fetchApi<void>(`/tasks/${id}`, { method: "DELETE" }),

  // Setup / Wizard endpoints
  browseDirectories: (path?: string) =>
    fetchApi<{
      current: string;
      parent: string | null;
      items: { name: string; path: string; is_git_repo: boolean }[];
    }>("/setup/browse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),

  getRecentProjects: () =>
    fetchApi<{
      projects: { path: string; name: string; is_git_repo: boolean }[];
    }>("/setup/recent"),

  analyzeProject: (path: string) =>
    fetchApi<{
      config: Record<string, unknown>;
      analysis: {
        detected_languages: string[];
        is_git_repo: boolean;
        has_tests: boolean;
        has_benchmarks: boolean;
        file_count: number;
        config_files: string[];
      };
    }>("/setup/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),

  analyzeWithLLM: (path: string) =>
    fetchApi<{
      defaults: Record<string, unknown>;
      suggestions: Record<string, unknown> | null;
      analysis: Record<string, unknown>;
    }>("/setup/analyze-with-llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),

  suggestTasks: (path: string) =>
    fetchApi<{
      suggested: SuggestedTask[];
      available: SuggestedTask[];
      analysis: {
        languages: string[];
        file_count: number;
        has_tests: boolean;
        has_benchmarks: boolean;
        config_files: string[];
        is_git_repo: boolean;
      };
      llm_enhanced: boolean;
    }>("/setup/suggest-tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),

  applySetup: (config: Record<string, unknown>, saveToProject = true) =>
    fetchApi<{ message: string; path: string }>("/setup/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config, save_to_project: saveToProject }),
    }),

  getDefaults: () => fetchApi<Record<string, unknown>>("/setup/defaults"),

  switchProject: (path: string) =>
    fetchApi<{ message: string; project_name: string; project_path: string }>(
      "/projects/switch",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      },
    ),

  getVigilProjects: () =>
    fetchApi<{
      projects: {
        name: string;
        path: string;
        has_config: boolean;
        has_state: boolean;
        iteration_count: number;
      }[];
    }>("/projects"),

  removeProject: (path: string) =>
    fetchApi<{ message: string; path: string; switched_to: string | null }>(
      "/projects/remove",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      },
    ),

  getModels: () =>
    fetchApi<{
      models: {
        name: string;
        provider: string;
        size_gb: number | null;
        family: string;
        parameter_size: string;
      }[];
      ollama_available: boolean;
    }>("/models"),

  analyzeProjectStream: (
    path: string,
    onEvent: (event: AnalysisStreamEvent) => void,
  ): Promise<void> => {
    return new Promise((resolve, reject) => {
      fetch(`${API_BASE}/setup/analyze-stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      })
        .then((res) => {
          if (!res.ok) {
            reject(new ApiError(res.status, "Stream failed"));
            return;
          }
          const reader = res.body?.getReader();
          if (!reader) {
            reject(new Error("No reader"));
            return;
          }
          const decoder = new TextDecoder();
          let buffer = "";

          function pump(): Promise<void> {
            return reader!.read().then(({ done, value }) => {
              if (done) {
                resolve();
                return;
              }
              buffer += decoder.decode(value, { stream: true });
              const lines = buffer.split("\n");
              buffer = lines.pop() || "";
              for (const line of lines) {
                if (line.startsWith("data: ")) {
                  try {
                    const evt = JSON.parse(line.slice(6));
                    onEvent(evt as AnalysisStreamEvent);
                  } catch {
                    // skip malformed
                  }
                }
              }
              return pump();
            });
          }

          pump().catch(reject);
        })
        .catch(reject);
    });
  },
};

export interface AnalysisStreamEvent {
  type:
    | "log"
    | "scan_complete"
    | "config_ready"
    | "tasks_ready"
    | "llm_prompt"
    | "llm_chunk"
    | "done"
    | "error";
  data: Record<string, unknown>;
}
