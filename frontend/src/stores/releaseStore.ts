/**
 * Zustand store for release state management
 */
import { create } from 'zustand'
import type { ReleaseListItem, ReleaseResponse, StepInfo, WSMessage } from '../types/api'
import { releasesApi } from '../lib/api'

interface ReleaseStore {
  // State
  releases: ReleaseListItem[]
  currentRelease: ReleaseResponse | null
  loading: boolean
  error: string | null

  // State sync tracking
  lastUpdateTimestamp: string | null
  stepProgress: Record<number, string> // Step number -> progress message

  // Toast notifications
  toast: { message: string; type: 'success' | 'error' | 'info' } | null

  // Selection state (for batch operations)
  selectedIds: Set<string>
  selectionMode: boolean

  // Search and filter state
  searchQuery: string
  filters: FilterOptions
  sortBy: SortOption

  // Actions
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void
  clearToast: () => void

  // Release list actions
  fetchReleases: () => Promise<void>

  // Current release actions
  fetchRelease: (id: string) => Promise<void>
  setCurrentRelease: (release: ReleaseResponse | null) => void
  setCurrentReleaseIfNewer: (release: ReleaseResponse) => void
  updateCurrentRelease: (updates: Partial<ReleaseResponse>) => void
  updateStep: (stepNumber: number, updates: Partial<StepInfo>) => void
  setStepProgress: (stepNumber: number, progress: string) => void
  clearStepProgress: () => void

  // Selection actions
  toggleSelection: (id: string) => void
  selectAll: () => void
  clearSelection: () => void
  setSelectionMode: (mode: boolean) => void
  deleteSelected: () => Promise<void>
  cleanupSelected: () => Promise<void>

  // Search and filter actions
  setSearchQuery: (query: string) => void
  setFilters: (filters: FilterOptions) => void
  setSortBy: (sort: SortOption) => void
  getFilteredReleases: () => ReleaseListItem[]

  // Handle WebSocket messages
  handleWSMessage: (message: WSMessage) => void
}

export type SortOption = 'newest' | 'oldest' | 'version'

export interface FilterOptions {
  status: ReleaseListItem['status'][]
  dryRun: boolean | null // null = show all
}

const DEFAULT_FILTERS: FilterOptions = {
  status: [],
  dryRun: null,
}

export const useReleaseStore = create<ReleaseStore>((set, get) => ({
  // Initial state
  releases: [],
  currentRelease: null,
  loading: false,
  error: null,
  toast: null,

  // State sync
  lastUpdateTimestamp: null,
  stepProgress: {},

  // Selection state
  selectedIds: new Set(),
  selectionMode: false,

  // Search and filter state
  searchQuery: '',
  filters: DEFAULT_FILTERS,
  sortBy: 'newest',

  // Basic setters
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),

  showToast: (message, type = 'info') => {
    set({ toast: { message, type } })
    setTimeout(() => set({ toast: null }), 5000)
  },

  clearToast: () => set({ toast: null }),

  // Fetch all releases
  fetchReleases: async () => {
    set({ loading: true, error: null })
    try {
      const releases = await releasesApi.list()
      set({ releases, loading: false })
    } catch (error) {
      set({ error: (error as Error).message, loading: false })
    }
  },

  // Fetch single release
  fetchRelease: async (id) => {
    set({ loading: true, error: null })
    try {
      const release = await releasesApi.get(id)
      // Use setCurrentReleaseIfNewer to prevent overwriting newer WS updates
      get().setCurrentReleaseIfNewer(release)
      set({ loading: false })
    } catch (error) {
      set({ error: (error as Error).message, loading: false })
    }
  },

  setCurrentRelease: (release) => set({
    currentRelease: release,
    lastUpdateTimestamp: release?.updated_at || null,
    stepProgress: {},
  }),

  setCurrentReleaseIfNewer: (release) => {
    const { lastUpdateTimestamp } = get()

    // If no timestamp tracking or new release has a newer timestamp, update
    if (!lastUpdateTimestamp || !release.updated_at) {
      set({
        currentRelease: release,
        lastUpdateTimestamp: release.updated_at || new Date().toISOString(),
      })
      return
    }

    const lastTime = new Date(lastUpdateTimestamp).getTime()
    const newTime = new Date(release.updated_at).getTime()

    if (newTime >= lastTime) {
      set({
        currentRelease: release,
        lastUpdateTimestamp: release.updated_at,
      })
    }
    // Otherwise, ignore stale data
  },

  updateCurrentRelease: (updates) => {
    const current = get().currentRelease
    if (current) {
      const now = new Date().toISOString()
      set({
        currentRelease: { ...current, ...updates, updated_at: now },
        lastUpdateTimestamp: now,
      })
    }
  },

  updateStep: (stepNumber, updates) => {
    const current = get().currentRelease
    if (!current) return

    const steps = current.steps.map((step) =>
      step.number === stepNumber ? { ...step, ...updates } : step
    )
    const now = new Date().toISOString()
    set({
      currentRelease: { ...current, steps, updated_at: now },
      lastUpdateTimestamp: now,
    })
  },

  setStepProgress: (stepNumber, progress) => {
    set((state) => ({
      stepProgress: { ...state.stepProgress, [stepNumber]: progress },
    }))
  },

  clearStepProgress: () => set({ stepProgress: {} }),

  // Selection actions
  toggleSelection: (id) => {
    set((state) => {
      const newSet = new Set(state.selectedIds)
      if (newSet.has(id)) {
        newSet.delete(id)
      } else {
        newSet.add(id)
      }
      return { selectedIds: newSet }
    })
  },

  selectAll: () => {
    const { getFilteredReleases } = get()
    const ids = getFilteredReleases().map((r) => r.id)
    set({ selectedIds: new Set(ids) })
  },

  clearSelection: () => set({ selectedIds: new Set(), selectionMode: false }),

  setSelectionMode: (mode) => set({
    selectionMode: mode,
    selectedIds: mode ? get().selectedIds : new Set(),
  }),

  deleteSelected: async () => {
    const { selectedIds, showToast, fetchReleases, clearSelection } = get()
    const ids = Array.from(selectedIds)

    if (ids.length === 0) return

    try {
      await Promise.all(ids.map((id) => releasesApi.delete(id)))
      showToast(`Deleted ${ids.length} release(s)`, 'success')
      clearSelection()
      await fetchReleases()
    } catch (error) {
      showToast(`Error deleting releases: ${(error as Error).message}`, 'error')
    }
  },

  cleanupSelected: async () => {
    const { selectedIds, showToast, fetchReleases, clearSelection } = get()
    const ids = Array.from(selectedIds)

    if (ids.length === 0) return

    try {
      const results = await Promise.all(ids.map((id) => releasesApi.cleanup(id)))
      const successCount = results.filter((r) => r.success).length
      showToast(`Cleaned up ${successCount}/${ids.length} release(s)`, 'success')
      clearSelection()
      await fetchReleases()
    } catch (error) {
      showToast(`Error cleaning up releases: ${(error as Error).message}`, 'error')
    }
  },

  // Search and filter actions
  setSearchQuery: (query) => set({ searchQuery: query }),

  setFilters: (filters) => set({ filters }),

  setSortBy: (sort) => set({ sortBy: sort }),

  getFilteredReleases: () => {
    const { releases, searchQuery, filters, sortBy } = get()
    let filtered = [...releases]

    // Apply search
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase().trim()
      filtered = filtered.filter(
        (r) =>
          r.build_version.toLowerCase().includes(query) ||
          r.rollback_version.toLowerCase().includes(query) ||
          r.promote_ticket_key?.toLowerCase().includes(query) ||
          r.deployment_ticket_key?.toLowerCase().includes(query)
      )
    }

    // Apply status filter
    if (filters.status.length > 0) {
      filtered = filtered.filter((r) => filters.status.includes(r.status))
    }

    // Apply dry_run filter (would need dry_run in ReleaseListItem)
    // Note: This requires backend to include dry_run in list response

    // Apply sorting
    filtered.sort((a, b) => {
      if (sortBy === 'newest') {
        return new Date(b.started_at || 0).getTime() - new Date(a.started_at || 0).getTime()
      }
      if (sortBy === 'oldest') {
        return new Date(a.started_at || 0).getTime() - new Date(b.started_at || 0).getTime()
      }
      // version sort - compare version strings
      return b.build_version.localeCompare(a.build_version)
    })

    return filtered
  },

  // Handle WebSocket messages
  handleWSMessage: (message) => {
    const { type, step, progress, error, data } = message
    const { updateCurrentRelease, updateStep, showToast, fetchReleases, setStepProgress, clearStepProgress } = get()

    switch (type) {
      case 'step_start':
        if (step?.number) {
          updateStep(step.number, { status: 'in_progress' })
          updateCurrentRelease({ current_step_number: step.number })
          // Clear previous step progress when new step starts
          setStepProgress(step.number, 'Starting...')
        }
        break

      case 'step_progress':
        // Display progress in UI via stepProgress state
        if (step?.number && progress) {
          setStepProgress(step.number, progress)
        }
        break

      case 'step_complete':
        if (step?.number) {
          updateStep(step.number, {
            status: 'completed',
            result: step.result,
          })
          // Update any resource keys from result
          if (step.result) {
            const updates: Partial<ReleaseResponse> = {}
            if (step.result.promote_ticket_key) {
              updates.promote_ticket_key = step.result.promote_ticket_key as string
            }
            if (step.result.deployment_ticket_key) {
              updates.deployment_ticket_key = step.result.deployment_ticket_key as string
            }
            if (step.result.jenkins_job_url) {
              updates.jenkins_job_url = step.result.jenkins_job_url as string
              updates.jenkins_build_number = step.result.jenkins_build_number as number
            }
            if (step.result.jira_ids) {
              updates.jira_ids = step.result.jira_ids as string[]
            }
            if (Object.keys(updates).length > 0) {
              updateCurrentRelease(updates)
            }
          }
        }
        break

      case 'workflow_complete':
        updateCurrentRelease({ status: 'completed' })
        clearStepProgress()
        showToast('Workflow completed successfully!', 'success')
        // Update with final data
        if (data) {
          updateCurrentRelease({
            promote_ticket_key: data.promote_ticket_key as string,
            deployment_ticket_key: data.deployment_ticket_key as string,
            jenkins_job_url: data.jenkins_job_url as string,
          })
        }
        fetchReleases() // Refresh list
        break

      case 'workflow_error':
        updateCurrentRelease({ status: 'error', error_message: error })
        clearStepProgress()
        if (step?.number) {
          updateStep(step.number, { status: 'error', error })
        }
        showToast(`Workflow error: ${error}`, 'error')
        fetchReleases() // Refresh list
        break
    }
  },
}))
