import type { CaseDetailRead, CaseListResponse, CaseSearchParams, CaseSourceRead } from "./types";

// No secrets belong here or in any VITE_-prefixed variable -- everything bundled by
// Vite is publicly readable in the shipped JS. This is a plain, non-sensitive base URL.
const DEFAULT_BASE_URL = "http://localhost:8000/api/v1";

const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? DEFAULT_BASE_URL;

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function buildQueryString(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

async function request<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`);
  } catch {
    throw new ApiError(0, "Could not reach the API. Check your connection and try again.");
  }

  if (!response.ok) {
    if (response.status === 404) {
      throw new ApiError(404, "Not found.");
    }
    throw new ApiError(response.status, `The API returned an unexpected error (${response.status}).`);
  }

  return (await response.json()) as T;
}

export function searchCases(params: CaseSearchParams): Promise<CaseListResponse> {
  const query = buildQueryString({ ...params });
  return request<CaseListResponse>(`/cases${query}`);
}

export function getCase(caseId: string): Promise<CaseDetailRead> {
  return request<CaseDetailRead>(`/cases/${encodeURIComponent(caseId)}`);
}

export function getCaseSources(caseId: string): Promise<CaseSourceRead[]> {
  return request<CaseSourceRead[]>(`/cases/${encodeURIComponent(caseId)}/sources`);
}
