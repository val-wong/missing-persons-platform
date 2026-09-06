import { useEffect, useState, type FormEvent } from "react";
import type { SortField, SortOrder } from "../api/types";

export interface FilterFormValues {
  q: string;
  sex: string;
  missing_state: string;
  missing_city: string;
  missing_country: string;
  hair_color: string;
  eye_color: string;
  source: string;
  missing_date_from: string;
  missing_date_to: string;
}

export const EMPTY_FILTERS: FilterFormValues = {
  q: "",
  sex: "",
  missing_state: "",
  missing_city: "",
  missing_country: "",
  hair_color: "",
  eye_color: "",
  source: "",
  missing_date_from: "",
  missing_date_to: "",
};

interface SearchFiltersProps {
  values: FilterFormValues;
  sortBy: SortField;
  sortOrder: SortOrder;
  onSubmit: (values: FilterFormValues, sortBy: SortField, sortOrder: SortOrder) => void;
  onClear: () => void;
}

/** A single form, applied all at once on submit -- not a request per keystroke.
 * `first_name`/`last_name` are deliberately not surfaced here: FBI (the only source
 * persisted today) never populates those name-component fields, so the controls would
 * always silently match nothing. See README. */
export function SearchFilters({ values, sortBy, sortOrder, onSubmit, onClear }: SearchFiltersProps) {
  const [draft, setDraft] = useState<FilterFormValues>(values);
  const [draftSortBy, setDraftSortBy] = useState<SortField>(sortBy);
  const [draftSortOrder, setDraftSortOrder] = useState<SortOrder>(sortOrder);

  // Re-sync the draft when the URL changes from elsewhere (e.g. browser back/forward).
  useEffect(() => setDraft(values), [values]);
  useEffect(() => setDraftSortBy(sortBy), [sortBy]);
  useEffect(() => setDraftSortOrder(sortOrder), [sortOrder]);

  function handleChange<K extends keyof FilterFormValues>(key: K, value: string) {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(draft, draftSortBy, draftSortOrder);
  }

  function handleClear() {
    setDraft(EMPTY_FILTERS);
    setDraftSortBy("created_at");
    setDraftSortOrder("desc");
    onClear();
  }

  return (
    <form className="search-filters" onSubmit={handleSubmit} role="search" aria-label="Case search filters">
      <div className="filter-field filter-field-wide">
        <label htmlFor="filter-q">Search by name</label>
        <input
          id="filter-q"
          type="text"
          value={draft.q}
          onChange={(e) => handleChange("q", e.target.value)}
          placeholder="e.g. Jordan Sample"
        />
      </div>

      <div className="filter-field">
        <label htmlFor="filter-sex">Sex</label>
        <input id="filter-sex" type="text" value={draft.sex} onChange={(e) => handleChange("sex", e.target.value)} />
      </div>

      <div className="filter-field">
        <label htmlFor="filter-state">Missing from state</label>
        <input
          id="filter-state"
          type="text"
          value={draft.missing_state}
          onChange={(e) => handleChange("missing_state", e.target.value)}
        />
      </div>

      <div className="filter-field">
        <label htmlFor="filter-city">Missing from city</label>
        <input
          id="filter-city"
          type="text"
          value={draft.missing_city}
          onChange={(e) => handleChange("missing_city", e.target.value)}
        />
      </div>

      <div className="filter-field">
        <label htmlFor="filter-country">Missing from country</label>
        <input
          id="filter-country"
          type="text"
          value={draft.missing_country}
          onChange={(e) => handleChange("missing_country", e.target.value)}
        />
      </div>

      <div className="filter-field">
        <label htmlFor="filter-hair">Hair color</label>
        <input
          id="filter-hair"
          type="text"
          value={draft.hair_color}
          onChange={(e) => handleChange("hair_color", e.target.value)}
        />
      </div>

      <div className="filter-field">
        <label htmlFor="filter-eye">Eye color</label>
        <input
          id="filter-eye"
          type="text"
          value={draft.eye_color}
          onChange={(e) => handleChange("eye_color", e.target.value)}
        />
      </div>

      <div className="filter-field">
        <label htmlFor="filter-source">Source</label>
        <input
          id="filter-source"
          type="text"
          value={draft.source}
          onChange={(e) => handleChange("source", e.target.value)}
          placeholder="e.g. fbi"
        />
      </div>

      <div className="filter-field">
        <label htmlFor="filter-date-from">Missing on/after</label>
        <input
          id="filter-date-from"
          type="date"
          value={draft.missing_date_from}
          onChange={(e) => handleChange("missing_date_from", e.target.value)}
        />
      </div>

      <div className="filter-field">
        <label htmlFor="filter-date-to">Missing on/before</label>
        <input
          id="filter-date-to"
          type="date"
          value={draft.missing_date_to}
          onChange={(e) => handleChange("missing_date_to", e.target.value)}
        />
      </div>

      <div className="filter-field">
        <label htmlFor="sort-by">Sort by</label>
        <select id="sort-by" value={draftSortBy} onChange={(e) => setDraftSortBy(e.target.value as SortField)}>
          <option value="created_at">Date added</option>
          <option value="updated_at">Last updated</option>
          <option value="name">Name</option>
          <option value="missing_date">Missing date</option>
        </select>
      </div>

      <div className="filter-field">
        <label htmlFor="sort-order">Sort direction</label>
        <select id="sort-order" value={draftSortOrder} onChange={(e) => setDraftSortOrder(e.target.value as SortOrder)}>
          <option value="desc">Descending</option>
          <option value="asc">Ascending</option>
        </select>
      </div>

      <div className="filter-actions">
        <button type="submit">Search</button>
        <button type="button" onClick={handleClear}>
          Clear filters
        </button>
      </div>
    </form>
  );
}
