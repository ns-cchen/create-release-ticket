/**
 * ReleaseDetail page - Shows live progress and controls for a release
 */
import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Play,
  Trash2,
  ExternalLink,
  RefreshCw,
  AlertTriangle,
  RotateCcw,
  SkipForward,
} from 'lucide-react'
import { useReleaseStore } from '../stores/releaseStore'
import { releasesApi } from '../lib/api'
import { createReleaseWebSocket, ReleaseWebSocket } from '../lib/websocket'
import StepProgress from '../components/StepProgress'
import type { ReleaseResumeInput } from '../types/api'

export default function ReleaseDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const {
    currentRelease,
    loading,
    error,
    fetchRelease,
    handleWSMessage,
    showToast,
    setCurrentRelease,
  } = useReleaseStore()

  const [ws, setWs] = useState<ReleaseWebSocket | null>(null)
  const [resumeOptions, setResumeOptions] = useState<ReleaseResumeInput>({})
  const [showResumeForm, setShowResumeForm] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)

  // Load release and connect WebSocket
  useEffect(() => {
    if (!id) return

    fetchRelease(id)

    const socket = createReleaseWebSocket(id)
    socket.onMessage(handleWSMessage)
    setWs(socket)

    return () => {
      socket.disconnect()
      setWs(null)
    }
  }, [id, fetchRelease, handleWSMessage])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      setCurrentRelease(null)
    }
  }, [setCurrentRelease])

  const handleResume = async () => {
    if (!id) return
    setActionLoading(true)
    try {
      await releasesApi.resume(id, resumeOptions)
      showToast('Release resumed!', 'success')
      setShowResumeForm(false)
      fetchRelease(id)
    } catch (error) {
      showToast((error as Error).message, 'error')
    } finally {
      setActionLoading(false)
    }
  }

  const handleCleanup = async () => {
    if (!id) return
    if (!confirm('This will close the promote ticket and cancel any running builds. Continue?')) {
      return
    }
    setActionLoading(true)
    try {
      const result = await releasesApi.cleanup(id)
      showToast(result.message, result.success ? 'success' : 'error')
      fetchRelease(id)
    } catch (error) {
      showToast((error as Error).message, 'error')
    } finally {
      setActionLoading(false)
    }
  }

  const handleDelete = async () => {
    if (!id) return
    if (!confirm('Delete this release record? This cannot be undone.')) {
      return
    }
    setActionLoading(true)
    try {
      await releasesApi.delete(id)
      showToast('Release deleted', 'success')
      navigate('/')
    } catch (error) {
      showToast((error as Error).message, 'error')
    } finally {
      setActionLoading(false)
    }
  }

  const handleSkipJenkins = async () => {
    if (!id) return
    setActionLoading(true)
    try {
      const result = await releasesApi.skipJenkins(id)
      showToast(result.message, 'success')
    } catch (error) {
      showToast((error as Error).message, 'error')
    } finally {
      setActionLoading(false)
    }
  }

  if (loading && !currentRelease) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="spinner" />
        <span className="ml-3 text-[var(--color-text-secondary)]">
          Loading release...
        </span>
      </div>
    )
  }

  if (error || !currentRelease) {
    return (
      <div className="fade-in">
        <div className="page-header">
          <button
            className="btn btn-outline btn-sm mb-4"
            onClick={() => navigate('/')}
          >
            <ArrowLeft size={16} />
            Back to Dashboard
          </button>
        </div>
        <div className="card">
          <div className="text-center py-12">
            <AlertTriangle size={48} className="mx-auto mb-4 text-[var(--color-error)]" />
            <h2 className="text-xl font-semibold mb-2">Release Not Found</h2>
            <p className="text-[var(--color-text-secondary)]">
              {error || 'This release may have been deleted.'}
            </p>
          </div>
        </div>
      </div>
    )
  }

  const canResume = currentRelease.status === 'error'
  const isActive = currentRelease.status === 'in_progress'

  return (
    <div className="fade-in">
      <div className="page-header">
        <button
          className="btn btn-outline btn-sm mb-4"
          onClick={() => navigate('/')}
        >
          <ArrowLeft size={16} />
          Back to Dashboard
        </button>
        <h1 className="page-title">
          {currentRelease.build_version.replace('queryservice-release-', '')}
        </h1>
        <div className="flex items-center gap-4 mt-2">
          <span
            data-testid="status-badge"
            className={`badge ${
              currentRelease.status === 'completed'
                ? 'badge-success'
                : currentRelease.status === 'error'
                ? 'badge-error'
                : currentRelease.status === 'in_progress'
                ? 'badge-info'
                : 'badge-neutral'
            }`}
          >
            {currentRelease.status.replace('_', ' ')}
          </span>
          {currentRelease.dry_run && (
            <span className="badge badge-warning">Dry Run</span>
          )}
          {isActive && ws?.isConnected() && (
            <span className="text-sm text-[var(--color-success)] flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-[var(--color-success)] animate-pulse" />
              Live
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Progress */}
        <div className="lg:col-span-2">
          <div className="card">
            <h2 className="card-title mb-4">Workflow Progress</h2>
            <StepProgress
              steps={currentRelease.steps}
              currentStepNumber={currentRelease.current_step_number}
            />

            {/* Skip Jenkins button — shown when step 5 is actively polling */}
            {isActive &&
              currentRelease.current_step_number === 5 &&
              currentRelease.jenkins_build_number && (
                <div className="mt-4 p-4 rounded-lg bg-amber-50 border border-amber-200 flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-amber-800">
                      Jenkins build is running (~42 min)
                    </p>
                    <p className="text-xs text-amber-600 mt-0.5">
                      The build will continue on Jenkins — you can skip the wait and proceed.
                    </p>
                  </div>
                  <button
                    className="btn btn-warning btn-sm"
                    onClick={handleSkipJenkins}
                    disabled={actionLoading}
                  >
                    {actionLoading ? (
                      <div className="spinner w-4 h-4" />
                    ) : (
                      <SkipForward size={16} />
                    )}
                    Skip Jenkins
                  </button>
                </div>
              )}

            {currentRelease.error_message && (
              <div className="mt-4 p-4 rounded-lg bg-red-50 border border-red-200">
                <h3 className="font-medium text-red-800 mb-1">Error</h3>
                <p className="text-sm text-red-700">{currentRelease.error_message}</p>
              </div>
            )}

            {canResume && (
              <div className="mt-6 pt-6 border-t border-[var(--color-border)]">
                {showResumeForm ? (
                  <div className="space-y-4">
                    <h3 className="font-medium">Resume Options</h3>
                    <p className="text-sm text-[var(--color-text-secondary)]">
                      Will retry from Step {currentRelease.current_step_number}:{' '}
                      {currentRelease.steps.find(
                        (s) => s.number === currentRelease.current_step_number
                      )?.name || currentRelease.current_step}
                    </p>

                    {/* GitHub override: show when error at step ≤ 4 */}
                    {currentRelease.current_step_number <= 4 && (
                      <div className="form-group">
                        <label className="form-label">GitHub Workflow Run ID (optional)</label>
                        <input
                          type="text"
                          className="form-input font-mono"
                          placeholder="21885316894 or https://github.com/.../actions/runs/..."
                          value={resumeOptions.github_workflow_run_id || ''}
                          onChange={(e) => {
                            const val = e.target.value.trim()
                            let parsed: number | undefined
                            if (val) {
                              const num = Number(val)
                              if (!isNaN(num) && num > 0) {
                                parsed = num
                              } else {
                                const match = val.match(/\/actions\/runs\/(\d+)/)
                                if (match) parsed = Number(match[1])
                              }
                            }
                            setResumeOptions({
                              ...resumeOptions,
                              github_workflow_run_id: parsed,
                            })
                          }}
                        />
                        <p className="text-sm text-[var(--color-text-muted)] mt-1">
                          Provide to monitor an existing run instead of triggering new
                        </p>
                      </div>
                    )}

                    {/* Jenkins override: show when error at step ≤ 5 */}
                    {currentRelease.current_step_number <= 5 && (
                      <>
                        <div className="grid grid-cols-2 gap-4">
                          <div className="form-group">
                            <label className="form-label">Jenkins Build Number (optional)</label>
                            <input
                              type="number"
                              className="form-input"
                              placeholder="12345"
                              value={resumeOptions.jenkins_build_number || ''}
                              onChange={(e) =>
                                setResumeOptions({
                                  ...resumeOptions,
                                  jenkins_build_number: e.target.value
                                    ? parseInt(e.target.value)
                                    : undefined,
                                })
                              }
                            />
                          </div>
                          <div className="form-group">
                            <label className="form-label">Jenkins Job URL</label>
                            <input
                              type="text"
                              className="form-input font-mono"
                              placeholder="https://jenkins.example.com/job/..."
                              value={resumeOptions.jenkins_job_url || ''}
                              onChange={(e) =>
                                setResumeOptions({
                                  ...resumeOptions,
                                  jenkins_job_url: e.target.value || undefined,
                                })
                              }
                            />
                          </div>
                        </div>
                      </>
                    )}

                    <div className="flex gap-2">
                      <button
                        className="btn btn-primary"
                        onClick={handleResume}
                        disabled={actionLoading}
                      >
                        {actionLoading ? (
                          <div className="spinner w-4 h-4" />
                        ) : (
                          <Play size={16} />
                        )}
                        Resume Workflow
                      </button>
                      <button
                        className="btn btn-outline"
                        onClick={() => setShowResumeForm(false)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    className="btn btn-primary"
                    onClick={() => setShowResumeForm(true)}
                  >
                    <Play size={16} />
                    Resume Workflow
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Details Sidebar */}
        <div className="space-y-6">
          <div className="card">
            <h2 className="card-title mb-4">Details</h2>
            <dl className="space-y-3 text-sm">
              <div>
                <dt className="text-[var(--color-text-muted)]">Build Version</dt>
                <dd className="font-mono">{currentRelease.build_version}</dd>
              </div>
              <div>
                <dt className="text-[var(--color-text-muted)]">Rollback Version</dt>
                <dd className="font-mono">{currentRelease.rollback_version}</dd>
              </div>
              {currentRelease.current_branch && (
                <div>
                  <dt className="text-[var(--color-text-muted)]">Current Branch</dt>
                  <dd className="font-mono">{currentRelease.current_branch}</dd>
                </div>
              )}
              {currentRelease.previous_branch && (
                <div>
                  <dt className="text-[var(--color-text-muted)]">Previous Branch</dt>
                  <dd className="font-mono">{currentRelease.previous_branch}</dd>
                </div>
              )}
              {currentRelease.jira_ids.length > 0 && (
                <div>
                  <dt className="text-[var(--color-text-muted)]">Jira IDs</dt>
                  <dd className="flex flex-wrap gap-1">
                    {currentRelease.jira_ids.map((id) => (
                      <a
                        key={id}
                        href={`https://netskope.atlassian.net/browse/${id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="ticket-link"
                      >
                        {id}
                      </a>
                    ))}
                  </dd>
                </div>
              )}
            </dl>
          </div>

          <div className="card">
            <h2 className="card-title mb-4">Resources</h2>
            <div className="space-y-2">
              {currentRelease.promote_ticket_key && (
                <a
                  data-testid="sidebar-promote-ticket"
                  href={`https://netskope.atlassian.net/browse/${currentRelease.promote_ticket_key}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 p-2 rounded hover:bg-[var(--color-bg-hover)] transition-colors"
                >
                  <ExternalLink size={16} className="text-[var(--color-accent)]" />
                  <span>Promote: {currentRelease.promote_ticket_key}</span>
                </a>
              )}
              {currentRelease.deployment_ticket_key && (
                <a
                  data-testid="sidebar-deployment-ticket"
                  href={`https://netskope.atlassian.net/browse/${currentRelease.deployment_ticket_key}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 p-2 rounded hover:bg-[var(--color-bg-hover)] transition-colors"
                >
                  <ExternalLink size={16} className="text-[var(--color-accent)]" />
                  <span>Deploy: {currentRelease.deployment_ticket_key}</span>
                </a>
              )}
              {currentRelease.jenkins_job_url && (
                <a
                  data-testid="jenkins-build-link"
                  href={currentRelease.jenkins_job_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 p-2 rounded hover:bg-[var(--color-bg-hover)] transition-colors"
                >
                  <ExternalLink size={16} className="text-[var(--color-accent)]" />
                  <span>Jenkins Build #{currentRelease.jenkins_build_number}</span>
                </a>
              )}
              {!currentRelease.promote_ticket_key &&
                !currentRelease.deployment_ticket_key &&
                !currentRelease.jenkins_job_url && (
                  <p className="text-sm text-[var(--color-text-muted)]">
                    No resources created yet
                  </p>
                )}
            </div>
          </div>

          <div className="card">
            <h2 className="card-title mb-4">Actions</h2>
            <div className="space-y-2">
              <button
                className="btn btn-outline w-full"
                onClick={() => fetchRelease(id!)}
                disabled={loading}
              >
                <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
                Refresh
              </button>

              {/* Rollback button - only for completed releases */}
              {currentRelease.status === 'completed' && (
                <button
                  className="btn btn-primary w-full"
                  onClick={() => navigate(`/new?rollback_from=${id}`)}
                >
                  <RotateCcw size={16} />
                  Create Rollback
                </button>
              )}

              {currentRelease.status === 'error' && (
                <button
                  className="btn btn-warning w-full"
                  onClick={handleCleanup}
                  disabled={actionLoading}
                >
                  <AlertTriangle size={16} />
                  Cleanup Resources
                </button>
              )}
              <button
                className="btn btn-danger w-full"
                onClick={handleDelete}
                disabled={actionLoading}
              >
                <Trash2 size={16} />
                Delete Record
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
