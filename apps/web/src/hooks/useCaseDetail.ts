import { useEffect, useState } from "react";
import { ApiError, getCase } from "../api/client";
import type { CaseDetailRead } from "../api/types";

interface UseCaseDetailResult {
  data: CaseDetailRead | null;
  loading: boolean;
  error: string | null;
  notFound: boolean;
}

export function useCaseDetail(caseId: string | undefined): UseCaseDetailResult {
  const [data, setData] = useState<CaseDetailRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!caseId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setNotFound(false);

    getCase(caseId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setError(err instanceof ApiError ? err.message : "Something went wrong loading this case.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [caseId]);

  return { data, loading, error, notFound };
}
