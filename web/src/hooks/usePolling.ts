import { useState, useEffect, useCallback, useRef } from "react";

/**
 * Polls a fetcher on an interval. Re-fetches immediately when `deps` change
 * (after initial mount — mount is covered by the interval effect’s first tick).
 * `refetch(override?)` can run a one-off fetch (e.g. explicit offset after project switch).
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs = 3000,
  deps: unknown[] = [],
): {
  data: T | null;
  loading: boolean;
  error: Error | null;
  refetch: (overrideFetcher?: () => Promise<T>) => Promise<void>;
} {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const fetchData = useCallback(async (overrideFetcher?: () => Promise<T>) => {
    try {
      const fn = overrideFetcher ?? fetcherRef.current;
      const result = await fn();
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
    const id = setInterval(() => void fetchData(), intervalMs);
    return () => clearInterval(id);
  }, [fetchData, intervalMs]);

  const skipDepsRef = useRef(true);
  useEffect(() => {
    if (deps.length === 0) return;
    if (skipDepsRef.current) {
      skipDepsRef.current = false;
      return;
    }
    void fetchData();
  }, [fetchData, ...deps]);

  return { data, loading, error, refetch: fetchData };
}
