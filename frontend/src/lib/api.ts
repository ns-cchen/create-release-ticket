/**
 * API Client for Create Release Ticket
 */
import type {
  ReleaseListItem,
  ReleaseResponse,
  ReleaseCreateInput,
  ReleaseResumeInput,
  CleanupResponse,
  PurgeResponse,
} from '../types/api'

export const API_BASE = import.meta.env.VITE_API_URL || ''

interface ApiError extends Error {
  status: number
  data: unknown
}

interface FetchOptions extends RequestInit {
  headers?: Record<string, string>
}

/**
 * Base fetch wrapper with error handling
 */
async function fetchApi<T>(endpoint: string, options: FetchOptions = {}): Promise<T> {
  const url = `${API_BASE}${endpoint}`

  const config: RequestInit = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  }

  const response = await fetch(url, config)

  if (!response.ok) {
    const error = new Error(`API Error: ${response.status}`) as ApiError
    error.status = response.status
    try {
      error.data = await response.json()
    } catch {
      error.data = null
    }
    throw error
  }

  return response.json()
}

// ============ Releases API ============

export const releasesApi = {
  /**
   * List all releases, sorted by most recent first
   */
  list: () => fetchApi<ReleaseListItem[]>('/api/releases'),

  /**
   * Get detailed information about a specific release
   */
  get: (releaseId: string) =>
    fetchApi<ReleaseResponse>(`/api/releases/${releaseId}`),

  /**
   * Start a new release workflow
   */
  create: (data: ReleaseCreateInput) =>
    fetchApi<ReleaseResponse>('/api/releases', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Resume a release workflow
   */
  resume: (releaseId: string, data: ReleaseResumeInput = {}) =>
    fetchApi<ReleaseResponse>(`/api/releases/${releaseId}/resume`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Skip Jenkins build polling and proceed to next step
   */
  skipJenkins: (releaseId: string) =>
    fetchApi<{ success: boolean; message: string }>(`/api/releases/${releaseId}/skip-jenkins`, {
      method: 'POST',
    }),

  /**
   * Clean up resources from a failed release
   */
  cleanup: (releaseId: string) =>
    fetchApi<CleanupResponse>(`/api/releases/${releaseId}/cleanup`, {
      method: 'POST',
    }),

  /**
   * Delete a release record
   */
  delete: (releaseId: string) =>
    fetchApi<{ success: boolean; message: string }>(`/api/releases/${releaseId}`, {
      method: 'DELETE',
    }),

  /**
   * Purge completed release records
   */
  purge: (options?: { dryRunOnly?: boolean; olderThanDays?: number }) => {
    const params = new URLSearchParams()
    if (options?.dryRunOnly) params.set('dry_run_only', 'true')
    if (options?.olderThanDays) params.set('older_than_days', String(options.olderThanDays))
    const qs = params.toString()
    return fetchApi<PurgeResponse>(`/api/releases/purge${qs ? `?${qs}` : ''}`, {
      method: 'DELETE',
    })
  },
}

// ============ Health API ============

export const healthApi = {
  check: () => fetchApi<{ status: string; service: string }>('/api/health'),
}
