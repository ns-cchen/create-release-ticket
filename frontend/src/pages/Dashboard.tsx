/**
 * Dashboard page - Lists all releases
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, RefreshCw, Rocket, CheckSquare, Square, Trash2, AlertTriangle, Eraser } from 'lucide-react'
import { useReleaseStore } from '../stores/releaseStore'
import { releasesApi } from '../lib/api'
import ReleaseCard from '../components/ReleaseCard'
import SearchFilter from '../components/SearchFilter'

type TabType = 'active' | 'completed' | 'all'

export default function Dashboard() {
  const navigate = useNavigate()
  const {
    releases,
    loading,
    error,
    fetchReleases,
    getFilteredReleases,
    selectedIds,
    selectionMode,
    setSelectionMode,
    selectAll,
    clearSelection,
    deleteSelected,
    cleanupSelected,
    showToast,
  } = useReleaseStore()
  const [activeTab, setActiveTab] = useState<TabType>('active')
  const [batchLoading, setBatchLoading] = useState(false)

  useEffect(() => {
    fetchReleases()
  }, [fetchReleases])

  // Get filtered releases from store (handles search and sort)
  const allFilteredReleases = getFilteredReleases()

  // Further filter by tab
  const filteredReleases = allFilteredReleases.filter((release) => {
    if (activeTab === 'active') {
      return ['in_progress', 'error'].includes(release.status)
    }
    if (activeTab === 'completed') {
      return release.status === 'completed'
    }
    return true
  })

  const activeCount = releases.filter((r) =>
    ['in_progress', 'error'].includes(r.status)
  ).length

  const handleBatchDelete = async () => {
    if (!confirm(`Delete ${selectedIds.size} selected release(s)? This cannot be undone.`)) {
      return
    }
    setBatchLoading(true)
    await deleteSelected()
    setBatchLoading(false)
  }

  const handleBatchCleanup = async () => {
    if (!confirm(`Cleanup ${selectedIds.size} selected release(s)? This will close tickets and cancel builds.`)) {
      return
    }
    setBatchLoading(true)
    await cleanupSelected()
    setBatchLoading(false)
  }

  const completedCount = releases.filter((r) => r.status === 'completed').length

  const handlePurgeCompleted = async () => {
    if (!confirm(`Purge all ${completedCount} completed release(s)? This removes local state files only.`)) {
      return
    }
    try {
      const result = await releasesApi.purge()
      showToast(`Purged ${result.deleted_count} completed release(s)`, 'success')
      await fetchReleases()
    } catch (err) {
      showToast(`Purge failed: ${(err as Error).message}`, 'error')
    }
  }

  return (
    <div className="fade-in">
      <div className="page-header">
        <h1 className="page-title">Release Dashboard</h1>
        <p className="page-subtitle">
          Manage QueryService deployment workflows
        </p>
      </div>

      <div className="card">
        <div className="card-header">
          <div className="flex gap-4">
            <button
              className={`btn ${activeTab === 'active' ? 'btn-primary' : 'btn-outline'} btn-sm`}
              onClick={() => setActiveTab('active')}
            >
              Active {activeCount > 0 && `(${activeCount})`}
            </button>
            <button
              className={`btn ${activeTab === 'completed' ? 'btn-primary' : 'btn-outline'} btn-sm`}
              onClick={() => setActiveTab('completed')}
            >
              Completed
            </button>
            <button
              className={`btn ${activeTab === 'all' ? 'btn-primary' : 'btn-outline'} btn-sm`}
              onClick={() => setActiveTab('all')}
            >
              All
            </button>
          </div>

          <div className="flex gap-2">
            {selectionMode ? (
              <>
                <button
                  className="btn btn-outline btn-sm"
                  onClick={selectAll}
                >
                  <CheckSquare size={16} />
                  Select All
                </button>
                <button
                  className="btn btn-outline btn-sm"
                  onClick={clearSelection}
                >
                  Cancel
                </button>
              </>
            ) : (
              <>
                <button
                  className="btn btn-outline btn-sm"
                  onClick={() => setSelectionMode(true)}
                >
                  <Square size={16} />
                  Select
                </button>
                <button
                  className="btn btn-outline btn-sm"
                  onClick={() => fetchReleases()}
                  disabled={loading}
                >
                  <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
                  Refresh
                </button>
                {completedCount > 0 && (
                  <button
                    className="btn btn-outline btn-sm"
                    onClick={handlePurgeCompleted}
                  >
                    <Eraser size={16} />
                    Purge Completed ({completedCount})
                  </button>
                )}
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => navigate('/new')}
                >
                  <Plus size={16} />
                  New Release
                </button>
              </>
            )}
          </div>
        </div>

        {/* Search and Filter */}
        <SearchFilter />

        {error && (
          <div className="mb-4 p-4 rounded-lg bg-red-50 text-red-700 border border-red-200">
            {error}
          </div>
        )}

        {loading && releases.length === 0 ? (
          <div className="flex items-center justify-center py-12">
            <div className="spinner" />
            <span className="ml-3 text-[var(--color-text-secondary)]">
              Loading releases...
            </span>
          </div>
        ) : filteredReleases.length === 0 ? (
          <div className="empty-state">
            <Rocket size={64} className="mx-auto mb-4 opacity-50" />
            <h3 className="text-lg font-medium mb-2">No releases found</h3>
            <p className="text-[var(--color-text-secondary)] mb-4">
              {activeTab === 'active'
                ? 'No active releases. Start a new one to get going!'
                : activeTab === 'completed'
                ? 'No completed releases yet.'
                : 'No releases have been created yet.'}
            </p>
            <button
              className="btn btn-primary"
              onClick={() => navigate('/new')}
            >
              <Plus size={16} />
              Create Release
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {filteredReleases.map((release) => (
              <ReleaseCard
                key={release.id}
                release={release}
                selectionMode={selectionMode}
              />
            ))}
          </div>
        )}
      </div>

      {/* Batch Action Bar */}
      {selectionMode && selectedIds.size > 0 && (
        <div className="fixed bottom-0 left-0 right-0 bg-[var(--color-bg-card)] border-t border-[var(--color-border)] shadow-lg p-4 z-50">
          <div className="max-w-4xl mx-auto flex items-center justify-between">
            <span className="font-medium">
              {selectedIds.size} release{selectedIds.size !== 1 ? 's' : ''} selected
            </span>
            <div className="flex gap-3">
              <button
                className="btn btn-warning btn-sm"
                onClick={handleBatchCleanup}
                disabled={batchLoading}
              >
                <AlertTriangle size={16} />
                Cleanup Selected
              </button>
              <button
                className="btn btn-danger btn-sm"
                onClick={handleBatchDelete}
                disabled={batchLoading}
              >
                <Trash2 size={16} />
                Delete Selected
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
