/**
 * SearchFilter component - Search, sort, and filter releases
 */
import { useState, useRef, useEffect } from 'react'
import { Search, SlidersHorizontal, X, ChevronDown } from 'lucide-react'
import { useReleaseStore, SortOption, FilterOptions } from '../stores/releaseStore'
import type { ReleaseListItem } from '../types/api'

const STATUS_OPTIONS: { value: ReleaseListItem['status']; label: string; color: string }[] = [
  { value: 'in_progress', label: 'In Progress', color: 'bg-blue-100 text-blue-800' },
  { value: 'completed', label: 'Completed', color: 'bg-green-100 text-green-800' },
  { value: 'error', label: 'Error', color: 'bg-red-100 text-red-800' },
  { value: 'not_started', label: 'Not Started', color: 'bg-gray-100 text-gray-800' },
]

const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: 'newest', label: 'Newest First' },
  { value: 'oldest', label: 'Oldest First' },
  { value: 'version', label: 'Version (High to Low)' },
]

export default function SearchFilter() {
  const {
    searchQuery,
    filters,
    sortBy,
    setSearchQuery,
    setFilters,
    setSortBy,
  } = useReleaseStore()

  const [showFilters, setShowFilters] = useState(false)
  const [showSortMenu, setShowSortMenu] = useState(false)
  const filterRef = useRef<HTMLDivElement>(null)
  const sortRef = useRef<HTMLDivElement>(null)

  // Close menus on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) {
        setShowFilters(false)
      }
      if (sortRef.current && !sortRef.current.contains(e.target as Node)) {
        setShowSortMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const toggleStatus = (status: ReleaseListItem['status']) => {
    const newStatuses = filters.status.includes(status)
      ? filters.status.filter((s) => s !== status)
      : [...filters.status, status]
    setFilters({ ...filters, status: newStatuses })
  }

  const clearFilters = () => {
    setFilters({ status: [], dryRun: null })
    setSearchQuery('')
  }

  const hasActiveFilters = filters.status.length > 0 || searchQuery.trim() !== ''

  return (
    <div className="flex flex-wrap gap-3 items-center mb-4">
      {/* Search Input */}
      <div className="relative flex-1 min-w-[200px] max-w-md">
        <Search
          size={18}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]"
        />
        <input
          type="text"
          className="form-input pl-10 pr-10 h-10"
          placeholder="Search version, ticket key..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        {searchQuery && (
          <button
            className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            onClick={() => setSearchQuery('')}
          >
            <X size={16} />
          </button>
        )}
      </div>

      {/* Sort Dropdown */}
      <div className="relative" ref={sortRef}>
        <button
          className="btn btn-outline btn-sm flex items-center gap-2"
          onClick={() => setShowSortMenu(!showSortMenu)}
        >
          {SORT_OPTIONS.find((o) => o.value === sortBy)?.label || 'Sort'}
          <ChevronDown size={16} />
        </button>
        {showSortMenu && (
          <div className="absolute right-0 mt-1 w-48 bg-[var(--color-bg-card)] rounded-lg shadow-lg border border-[var(--color-border)] z-10">
            {SORT_OPTIONS.map((option) => (
              <button
                key={option.value}
                className={`w-full text-left px-4 py-2 text-sm hover:bg-[var(--color-bg-hover)] first:rounded-t-lg last:rounded-b-lg ${
                  sortBy === option.value ? 'text-[var(--color-accent)] font-medium' : ''
                }`}
                onClick={() => {
                  setSortBy(option.value)
                  setShowSortMenu(false)
                }}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Filter Button & Panel */}
      <div className="relative" ref={filterRef}>
        <button
          className={`btn btn-sm flex items-center gap-2 ${
            filters.status.length > 0 ? 'btn-primary' : 'btn-outline'
          }`}
          onClick={() => setShowFilters(!showFilters)}
        >
          <SlidersHorizontal size={16} />
          Filters
          {filters.status.length > 0 && (
            <span className="ml-1 bg-white/20 rounded-full px-2 py-0.5 text-xs">
              {filters.status.length}
            </span>
          )}
        </button>

        {showFilters && (
          <div className="absolute right-0 mt-1 w-64 bg-[var(--color-bg-card)] rounded-lg shadow-lg border border-[var(--color-border)] z-10 p-4">
            <div className="flex items-center justify-between mb-3">
              <h4 className="font-medium text-sm">Filter by Status</h4>
              {filters.status.length > 0 && (
                <button
                  className="text-xs text-[var(--color-accent)] hover:underline"
                  onClick={() => setFilters({ ...filters, status: [] })}
                >
                  Clear
                </button>
              )}
            </div>

            <div className="space-y-2">
              {STATUS_OPTIONS.map((option) => (
                <label
                  key={option.value}
                  className="flex items-center gap-2 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    className="w-4 h-4 rounded border-[var(--color-border)]"
                    checked={filters.status.includes(option.value)}
                    onChange={() => toggleStatus(option.value)}
                  />
                  <span
                    className={`text-xs px-2 py-0.5 rounded ${option.color}`}
                  >
                    {option.label}
                  </span>
                </label>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Clear All Filters */}
      {hasActiveFilters && (
        <button
          className="btn btn-outline btn-sm text-[var(--color-error)]"
          onClick={clearFilters}
        >
          <X size={16} />
          Clear All
        </button>
      )}
    </div>
  )
}
