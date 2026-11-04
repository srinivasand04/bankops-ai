import { useCallback, useEffect, useRef, useState } from "react";

import { errorMessage } from "../services/api";

interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Fetch on mount and when deps change. `pollMs` re-fetches on an interval while `keepPolling(data)`
 * is true - used to watch a RUNNING AI analysis until it finishes.
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  options: { pollMs?: number; keepPolling?: (data: T | null) => boolean } = {},
): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetcherRef
      .current()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      })
      .catch((err) => !cancelled && setError(errorMessage(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  const { pollMs, keepPolling } = options;
  const shouldPoll = !!pollMs && !!keepPolling && keepPolling(data);
  useEffect(() => {
    if (!shouldPoll) return;
    const timer = window.setInterval(() => setTick((t) => t + 1), pollMs);
    return () => window.clearInterval(timer);
  }, [shouldPoll, pollMs]);

  return { data, error, loading, reload: useCallback(() => setTick((t) => t + 1), []) };
}
