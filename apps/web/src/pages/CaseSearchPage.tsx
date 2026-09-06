import { useSearchParams } from "react-router-dom";
import { useCaseSearch } from "../hooks/useCaseSearch";
import { CaseCard } from "../components/CaseCard";
import { Pagination } from "../components/Pagination";
import { SearchFilters, type FilterFormValues } from "../components/SearchFilters";
import type { CaseSearchParams, SortField, SortOrder } from "../api/types";

const DEFAULT_LIMIT = 25;
const SORT_FIELDS: SortField[] = ["name", "missing_date", "created_at", "updated_at"];
const SORT_ORDERS: SortOrder[] = ["asc", "desc"];

interface ParsedParams {
  filters: FilterFormValues;
  sortBy: SortField;
  sortOrder: SortOrder;
  offset: number;
}

function parseParams(searchParams: URLSearchParams): ParsedParams {
  const sortByRaw = searchParams.get("sort_by");
  const sortOrderRaw = searchParams.get("sort_order");
  const offsetRaw = Number(searchParams.get("offset") ?? 0);

  return {
    filters: {
      q: searchParams.get("q") ?? "",
      sex: searchParams.get("sex") ?? "",
      missing_state: searchParams.get("missing_state") ?? "",
      missing_city: searchParams.get("missing_city") ?? "",
      missing_country: searchParams.get("missing_country") ?? "",
      hair_color: searchParams.get("hair_color") ?? "",
      eye_color: searchParams.get("eye_color") ?? "",
      source: searchParams.get("source") ?? "",
      missing_date_from: searchParams.get("missing_date_from") ?? "",
      missing_date_to: searchParams.get("missing_date_to") ?? "",
    },
    sortBy: SORT_FIELDS.includes(sortByRaw as SortField) ? (sortByRaw as SortField) : "created_at",
    sortOrder: SORT_ORDERS.includes(sortOrderRaw as SortOrder) ? (sortOrderRaw as SortOrder) : "desc",
    offset: Number.isFinite(offsetRaw) && offsetRaw > 0 ? offsetRaw : 0,
  };
}

function toApiParams(parsed: ParsedParams): CaseSearchParams {
  const { filters, sortBy, sortOrder, offset } = parsed;
  return {
    q: filters.q || undefined,
    sex: filters.sex || undefined,
    missing_state: filters.missing_state || undefined,
    missing_city: filters.missing_city || undefined,
    missing_country: filters.missing_country || undefined,
    hair_color: filters.hair_color || undefined,
    eye_color: filters.eye_color || undefined,
    source: filters.source || undefined,
    missing_date_from: filters.missing_date_from || undefined,
    missing_date_to: filters.missing_date_to || undefined,
    sort_by: sortBy,
    sort_order: sortOrder,
    limit: DEFAULT_LIMIT,
    offset,
  };
}

export function CaseSearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const parsed = parseParams(searchParams);
  const { filters, sortBy, sortOrder, offset } = parsed;
  const apiParams = toApiParams(parsed);
  const { data, loading, error } = useCaseSearch(apiParams);

  function applySearch(nextFilters: FilterFormValues, nextSortBy: SortField, nextSortOrder: SortOrder) {
    const next = new URLSearchParams();
    for (const [key, value] of Object.entries(nextFilters)) {
      if (value) next.set(key, value);
    }
    next.set("sort_by", nextSortBy);
    next.set("sort_order", nextSortOrder);
    // A new search always starts back at the first page.
    setSearchParams(next);
  }

  function clearSearch() {
    setSearchParams(new URLSearchParams());
  }

  function goToOffset(nextOffset: number) {
    const next = new URLSearchParams(searchParams);
    next.set("offset", String(nextOffset));
    setSearchParams(next);
  }

  return (
    <section aria-labelledby="search-heading">
      <h2 id="search-heading">Search cases</h2>
      <SearchFilters values={filters} sortBy={sortBy} sortOrder={sortOrder} onSubmit={applySearch} onClear={clearSearch} />

      {loading && <p role="status">Loading cases…</p>}
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}

      {!loading && !error && data && data.items.length === 0 && <p role="status">No cases match your search.</p>}

      {!loading && !error && data && data.items.length > 0 && (
        <>
          <ul className="case-list">
            {data.items.map((item) => (
              <CaseCard key={item.case_id} item={item} />
            ))}
          </ul>
          <Pagination
            total={data.total}
            limit={data.limit}
            offset={data.offset}
            onPrevious={() => goToOffset(Math.max(0, offset - DEFAULT_LIMIT))}
            onNext={() => goToOffset(offset + DEFAULT_LIMIT)}
          />
        </>
      )}
    </section>
  );
}
