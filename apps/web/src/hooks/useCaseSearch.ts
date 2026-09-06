import { useEffect, useState } from "react";
import { ApiError, searchCases } from "../api/client";
import type { CaseListResponse, CaseSearchParams } from "../api/types";

interface UseCaseSearchResult {
  data: CaseListResponse | null;
  loading: boolean;
  error: string | null;
}

/** Refetches whenever the search params change (by value, not by object identity --
 * callers construct a new params object on every render). */
export function useCaseSearch(params: CaseSearchParams): UseCaseSearchResult {
  const [data, setData] = useState<CaseListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const paramsKey = JSON.stringify(params);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    searchCases(params)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Something went wrong loading results.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // paramsKey is the real dependency -- params itself is a fresh object every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsKey]);

  return { data, loading, error };
}
