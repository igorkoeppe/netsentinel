import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  offset: number;
  limit: number;
  count: number;
  onPageChange: (newOffset: number) => void;
  onLimitChange?: (newLimit: number) => void;
  isLoading?: boolean;
}

export const Pagination: React.FC<PaginationProps> = ({
  offset,
  limit,
  count,
  onPageChange,
  onLimitChange,
  isLoading = false,
}) => {
  const currentPage = Math.floor(offset / limit) + 1;
  const canGoPrevious = offset > 0;
  // If count equals limit, there is likely a next page
  const canGoNext = count === limit;

  const handlePrevious = () => {
    if (canGoPrevious) {
      onPageChange(Math.max(0, offset - limit));
    }
  };

  const handleNext = () => {
    if (canGoNext) {
      onPageChange(offset + limit);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0.75rem 0",
        flexWrap: "wrap",
        gap: "0.75rem",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.875rem", color: "var(--color-text-muted)" }}>
        <span>Showing {count} items</span>
        {onLimitChange && (
          <div style={{ display: "flex", alignItems: "center", gap: "0.25rem", marginLeft: "0.5rem" }}>
            <span>per page:</span>
            <select
              value={limit}
              onChange={(e) => onLimitChange(Number(e.target.value))}
              style={{ width: "auto", padding: "0.2rem 0.5rem" }}
              aria-label="Items per page"
              disabled={isLoading}
            >
              <option value={20}>20</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </div>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <button
          className="btn btn-sm"
          onClick={handlePrevious}
          disabled={!canGoPrevious || isLoading}
          aria-label="Previous page"
        >
          <ChevronLeft size={16} />
          <span>Previous</span>
        </button>

        <span style={{ fontSize: "0.875rem", fontWeight: 600, padding: "0 0.5rem", color: "var(--color-text)" }}>
          Page {currentPage}
        </span>

        <button
          className="btn btn-sm"
          onClick={handleNext}
          disabled={!canGoNext || isLoading}
          aria-label="Next page"
        >
          <span>Next</span>
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
};
