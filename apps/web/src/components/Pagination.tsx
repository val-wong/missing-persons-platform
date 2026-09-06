interface PaginationProps {
  total: number;
  limit: number;
  offset: number;
  onPrevious: () => void;
  onNext: () => void;
}

export function Pagination({ total, limit, offset, onPrevious, onNext }: PaginationProps) {
  if (total === 0) return null;

  const start = offset + 1;
  const end = Math.min(offset + limit, total);
  const hasPrevious = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <nav className="pagination" aria-label="Search result pages">
      <p aria-live="polite">
        Showing {start}–{end} of {total}
      </p>
      <div className="pagination-controls">
        <button type="button" onClick={onPrevious} disabled={!hasPrevious}>
          Previous
        </button>
        <button type="button" onClick={onNext} disabled={!hasNext}>
          Next
        </button>
      </div>
    </nav>
  );
}
