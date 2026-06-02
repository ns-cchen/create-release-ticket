/**
 * NewRelease page - Create a new release workflow
 */
import { useState, useMemo, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Rocket, Info, AlertCircle, RotateCcw } from 'lucide-react'
import { releasesApi } from '../lib/api'
import { useReleaseStore } from '../stores/releaseStore'
import { validateReleaseForm } from '../lib/validation'
import type { ReleaseCreateInput } from '../types/api'

const START_FROM_OPTIONS = [
  { value: 1, label: 'Full Workflow (default)' },
  { value: 4, label: 'Step 4: GitHub Workflow' },
  { value: 5, label: 'Step 5: Jenkins Build' },
  { value: 6, label: 'Step 6: Deployment Ticket' },
]

/**
 * Parse a GitHub workflow run ID from either a numeric string or a full URL.
 * Examples:
 *   "21885316894" → 21885316894
 *   "https://github.com/netSkope/query-engine/actions/runs/21885316894" → 21885316894
 */
function parseGitHubRunId(input: string): number | undefined {
  const trimmed = input.trim()
  if (!trimmed) return undefined

  // Try numeric first
  const num = Number(trimmed)
  if (!isNaN(num) && num > 0) return num

  // Try extracting from URL: .../actions/runs/<id>
  const match = trimmed.match(/\/actions\/runs\/(\d+)/)
  if (match) return Number(match[1])

  return undefined
}

export default function NewRelease() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { showToast, fetchRelease, currentRelease } = useReleaseStore()
  const [submitting, setSubmitting] = useState(false)
  const [touched, setTouched] = useState<Record<string, boolean>>({})

  const [formData, setFormData] = useState<ReleaseCreateInput>({
    build_version: '',
    rollback_version: '',
    ref: 'develop',
    previous_branch: '',
    jira_ids: [],
    previous_deployment_ticket: '',
    start_from_step: 1,
    dry_run: false,
  })

  // Raw input for GitHub workflow run ID (accepts URL or numeric)
  const [githubRunInput, setGithubRunInput] = useState('')
  const [jiraIdsInput, setJiraIdsInput] = useState('')

  // Rollback mode: pre-fill from existing release
  const rollbackFromId = searchParams.get('rollback_from')
  const [isRollbackMode, setIsRollbackMode] = useState(false)

  useEffect(() => {
    if (rollbackFromId) {
      fetchRelease(rollbackFromId)
      setIsRollbackMode(true)
    }
  }, [rollbackFromId, fetchRelease])

  useEffect(() => {
    if (isRollbackMode && currentRelease && rollbackFromId === currentRelease.id) {
      // Swap versions for rollback
      setFormData((prev) => ({
        ...prev,
        build_version: currentRelease.rollback_version,
        rollback_version: currentRelease.build_version,
        previous_deployment_ticket: currentRelease.deployment_ticket_key || '',
      }))
    }
  }, [isRollbackMode, currentRelease, rollbackFromId])

  // Real-time validation
  const validation = useMemo(
    () => validateReleaseForm(formData.build_version, formData.rollback_version, jiraIdsInput),
    [formData.build_version, formData.rollback_version, jiraIdsInput]
  )

  const startStep = formData.start_from_step || 1

  // Artifact validation for start_from_step
  const artifactErrors = useMemo(() => {
    const errors: string[] = []
    if (startStep >= 4 && !formData.promote_ticket_key?.trim()) {
      errors.push('Promote Ticket Key is required when starting from step 4+')
    }
    if (startStep === 5 && !parseGitHubRunId(githubRunInput)) {
      errors.push('GitHub Workflow Run ID is required when starting from step 5')
    }
    if (startStep === 6) {
      if (!formData.jenkins_build_number) {
        errors.push('Jenkins Build Number is required when starting from step 6')
      }
      if (!formData.jenkins_job_url?.trim()) {
        errors.push('Jenkins Job URL is required when starting from step 6')
      }
    }
    return errors
  }, [startStep, formData, githubRunInput])

  const handleBlur = (field: string) => {
    setTouched((prev) => ({ ...prev, [field]: true }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)

    try {
      const parsedRunId = parseGitHubRunId(githubRunInput)

      const input: ReleaseCreateInput = {
        ...formData,
        previous_branch: formData.previous_branch || undefined,
        jira_ids: jiraIdsInput
          ? jiraIdsInput.split(',').map((s) => s.trim()).filter(Boolean)
          : undefined,
        previous_deployment_ticket: formData.previous_deployment_ticket || undefined,
        start_from_step: startStep > 1 ? startStep : undefined,
        promote_ticket_key: formData.promote_ticket_key || undefined,
        github_workflow_run_id: parsedRunId,
        jenkins_build_number: formData.jenkins_build_number || undefined,
        jenkins_job_url: formData.jenkins_job_url || undefined,
        max_consecutive_poll_failures: formData.max_consecutive_poll_failures || undefined,
      }

      const release = await releasesApi.create(input)
      showToast('Release started successfully!', 'success')
      navigate(`/release/${release.id}`)
    } catch (error) {
      showToast((error as Error).message, 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const isValid = validation.isValid && artifactErrors.length === 0

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
          {isRollbackMode ? (
            <>
              <RotateCcw size={28} className="inline mr-2" />
              Create Rollback Release
            </>
          ) : (
            'New Release'
          )}
        </h1>
        <p className="page-subtitle">
          {isRollbackMode
            ? 'Create a release to rollback to the previous version'
            : 'Start a new QueryService deployment workflow'}
        </p>
      </div>

      {isRollbackMode && currentRelease && (
        <div className="mb-6 p-4 rounded-lg bg-blue-50 border border-blue-200 flex items-start gap-3">
          <RotateCcw className="text-blue-600 flex-shrink-0 mt-0.5" size={20} />
          <div>
            <p className="font-medium text-blue-800">Rollback Mode</p>
            <p className="text-sm text-blue-700">
              Creating rollback from <strong>{currentRelease.build_version.replace('queryservice-release-', '')}</strong>.
              The versions have been swapped and the deployment ticket link is pre-filled.
            </p>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="card mb-6">
          <h2 className="card-title mb-4">Required</h2>

          <div className="form-group">
            <label className="form-label">
              Build Version
              <span className="text-[var(--color-error)] ml-1">*</span>
            </label>
            <input
              type="text"
              className={`form-input font-mono ${
                touched.build_version && !validation.buildVersion.valid
                  ? 'border-[var(--color-error)] focus:ring-[var(--color-error)]'
                  : ''
              }`}
              placeholder="queryservice-release-2025.12.2.0.18496"
              value={formData.build_version}
              onChange={(e) =>
                setFormData({ ...formData, build_version: e.target.value })
              }
              onBlur={() => handleBlur('build_version')}
              required
            />
            {touched.build_version && !validation.buildVersion.valid ? (
              <p className="text-sm text-[var(--color-error)] mt-1 flex items-center gap-1">
                <AlertCircle size={14} />
                {validation.buildVersion.error}
              </p>
            ) : (
              <p className="text-sm text-[var(--color-text-muted)] mt-1">
                Format: queryservice-release-YYYY.MM.W.P.DRONE
              </p>
            )}
          </div>

          <div className="form-group">
            <label className="form-label">
              Rollback Version
              <span className="text-[var(--color-error)] ml-1">*</span>
            </label>
            <input
              type="text"
              className={`form-input font-mono ${
                touched.rollback_version && !validation.rollbackVersion.valid
                  ? 'border-[var(--color-error)] focus:ring-[var(--color-error)]'
                  : ''
              }`}
              placeholder="queryservice-release-2025.12.1.0.18438"
              value={formData.rollback_version}
              onChange={(e) =>
                setFormData({ ...formData, rollback_version: e.target.value })
              }
              onBlur={() => handleBlur('rollback_version')}
              required
            />
            {touched.rollback_version && !validation.rollbackVersion.valid ? (
              <p className="text-sm text-[var(--color-error)] mt-1 flex items-center gap-1">
                <AlertCircle size={14} />
                {validation.rollbackVersion.error}
              </p>
            ) : !validation.versionOrder.valid &&
              validation.buildVersion.valid &&
              validation.rollbackVersion.valid ? (
              <p className="text-sm text-[var(--color-error)] mt-1 flex items-center gap-1">
                <AlertCircle size={14} />
                {validation.versionOrder.error}
              </p>
            ) : (
              <p className="text-sm text-[var(--color-text-muted)] mt-1">
                The version to roll back to if needed
              </p>
            )}
          </div>
        </div>

        <div className="card mb-6">
          <h2 className="card-title mb-4">Optional</h2>

          <div className="form-group">
            <label className="form-label">Git Ref</label>
            <input
              type="text"
              className="form-input font-mono"
              placeholder="develop"
              value={formData.ref}
              onChange={(e) =>
                setFormData({ ...formData, ref: e.target.value })
              }
            />
            <p className="text-sm text-[var(--color-text-muted)] mt-1">
              Branch or ref for GitHub workflow (default: develop)
            </p>
          </div>

          <div className="form-group">
            <label className="form-label">Previous Branch Override</label>
            <input
              type="text"
              className="form-input font-mono"
              placeholder="queryservice-release-2025.12.1"
              value={formData.previous_branch}
              onChange={(e) =>
                setFormData({ ...formData, previous_branch: e.target.value })
              }
            />
            <p className="text-sm text-[var(--color-text-muted)] mt-1">
              Override the auto-derived previous branch for commit comparison
            </p>
          </div>

          <div className="form-group">
            <label className="form-label">Jira IDs Override</label>
            <input
              type="text"
              className={`form-input font-mono ${
                touched.jira_ids && !validation.jiraIds.valid
                  ? 'border-[var(--color-error)] focus:ring-[var(--color-error)]'
                  : ''
              }`}
              placeholder="DINT-1234, EP-5678"
              value={jiraIdsInput}
              onChange={(e) => setJiraIdsInput(e.target.value)}
              onBlur={() => handleBlur('jira_ids')}
            />
            {touched.jira_ids && !validation.jiraIds.valid ? (
              <p className="text-sm text-[var(--color-error)] mt-1 flex items-center gap-1">
                <AlertCircle size={14} />
                {validation.jiraIds.error}
              </p>
            ) : (
              <p className="text-sm text-[var(--color-text-muted)] mt-1">
                Comma-separated Jira IDs (overrides auto-detection from commits)
              </p>
            )}
          </div>

          <div className="form-group">
            <label className="form-label">Previous Deployment Ticket</label>
            <input
              type="text"
              className="form-input font-mono"
              placeholder="ENG-857076"
              value={formData.previous_deployment_ticket}
              onChange={(e) =>
                setFormData({ ...formData, previous_deployment_ticket: e.target.value })
              }
            />
            <p className="text-sm text-[var(--color-text-muted)] mt-1">
              Link new deployment ticket to a previous one (Relates link)
            </p>
          </div>
        </div>

        <div className="card mb-6">
          <h2 className="card-title mb-4">Execution Options</h2>

          <div className="form-group">
            <label className="form-label">Start From Step</label>
            <select
              className="form-input"
              value={startStep}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  start_from_step: parseInt(e.target.value),
                })
              }
            >
              {START_FROM_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <p className="text-sm text-[var(--color-text-muted)] mt-1">
              Skip earlier steps by providing pre-existing artifacts. Workflow always runs to completion.
            </p>
          </div>

          {/* Dynamic artifact fields based on start_from_step */}
          {startStep >= 4 && (
            <div className="mt-4 p-4 rounded-lg bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
              <h3 className="font-medium mb-3">Pre-existing Artifacts</h3>

              {/* Promote Ticket Key: required at step 4+ */}
              <div className="form-group">
                <label className="form-label">
                  Promote Ticket Key
                  <span className="text-[var(--color-error)] ml-1">*</span>
                </label>
                <input
                  type="text"
                  className="form-input font-mono"
                  placeholder="DINT-2057"
                  value={formData.promote_ticket_key || ''}
                  onChange={(e) =>
                    setFormData({ ...formData, promote_ticket_key: e.target.value })
                  }
                />
                <p className="text-sm text-[var(--color-text-muted)] mt-1">
                  Existing promote ticket from a previous run
                </p>
              </div>

              {/* GitHub Workflow Run ID: required at step 5 only */}
              {startStep === 5 && (
                <div className="form-group">
                  <label className="form-label">
                    GitHub Workflow Run ID
                    <span className="text-[var(--color-error)] ml-1">*</span>
                  </label>
                  <input
                    type="text"
                    className="form-input font-mono"
                    placeholder="21885316894 or https://github.com/.../actions/runs/21885316894"
                    value={githubRunInput}
                    onChange={(e) => setGithubRunInput(e.target.value)}
                  />
                  <p className="text-sm text-[var(--color-text-muted)] mt-1">
                    Numeric ID or full GitHub Actions URL
                  </p>
                </div>
              )}

              {/* Jenkins fields: required at step 6 only */}
              {startStep === 6 && (
                <div className="grid grid-cols-2 gap-4">
                  <div className="form-group">
                    <label className="form-label">
                      Jenkins Build Number
                      <span className="text-[var(--color-error)] ml-1">*</span>
                    </label>
                    <input
                      type="number"
                      className="form-input"
                      placeholder="1788"
                      value={formData.jenkins_build_number || ''}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          jenkins_build_number: e.target.value
                            ? parseInt(e.target.value)
                            : undefined,
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">
                      Jenkins Job URL
                      <span className="text-[var(--color-error)] ml-1">*</span>
                    </label>
                    <input
                      type="text"
                      className="form-input font-mono"
                      placeholder="https://jenkins.example.com/job/..."
                      value={formData.jenkins_job_url || ''}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          jenkins_job_url: e.target.value || undefined,
                        })
                      }
                    />
                  </div>
                </div>
              )}

              {/* Artifact validation errors */}
              {artifactErrors.length > 0 && (
                <div className="mt-3 p-3 rounded bg-red-50 border border-red-200">
                  {artifactErrors.map((err, i) => (
                    <p key={i} className="text-sm text-red-700 flex items-center gap-1">
                      <AlertCircle size={14} />
                      {err}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="form-group mt-4">
            <label className="form-label">Max Poll Retries</label>
            <input
              type="number"
              className="form-input w-32"
              placeholder="5"
              min={1}
              value={formData.max_consecutive_poll_failures ?? ''}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  max_consecutive_poll_failures: e.target.value
                    ? parseInt(e.target.value)
                    : undefined,
                })
              }
            />
            <p className="text-sm text-[var(--color-text-muted)] mt-1">
              Max consecutive Jenkins poll failures before aborting (default: 5 from config.yaml, ~2.5 min tolerance at 30s intervals)
            </p>
          </div>

          <div className="form-group mt-4">
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                className="w-5 h-5 rounded border-[var(--color-border)] text-[var(--color-accent)] focus:ring-[var(--color-accent)]"
                checked={formData.dry_run}
                onChange={(e) =>
                  setFormData({ ...formData, dry_run: e.target.checked })
                }
              />
              <span className="font-medium">Dry Run</span>
            </label>
            <p className="text-sm text-[var(--color-text-muted)] mt-1 ml-8">
              Preview actions without executing (no tickets created, no builds triggered)
            </p>
          </div>
        </div>

        {formData.dry_run && (
          <div className="mb-6 p-4 rounded-lg bg-amber-50 border border-amber-200 flex items-start gap-3">
            <Info className="text-amber-600 flex-shrink-0 mt-0.5" size={20} />
            <div>
              <p className="font-medium text-amber-800">Dry Run Mode</p>
              <p className="text-sm text-amber-700">
                No actual Jira tickets will be created, no GitHub workflows will be
                triggered, and no Jenkins builds will run. This is for testing the
                workflow configuration.
              </p>
            </div>
          </div>
        )}

        <div className="actions-bar">
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => navigate('/')}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!isValid || submitting}
          >
            {submitting ? (
              <>
                <div className="spinner w-4 h-4" />
                Starting...
              </>
            ) : (
              <>
                <Rocket size={16} />
                Start Release
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  )
}
