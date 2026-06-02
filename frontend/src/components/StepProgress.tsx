/**
 * StepProgress component - Shows the 7-step workflow progress
 */
import { Check, X, Loader2 } from 'lucide-react'
import type { StepInfo } from '../types/api'
import { useReleaseStore } from '../stores/releaseStore'

interface StepProgressProps {
  steps: StepInfo[]
  currentStepNumber: number
}

export default function StepProgress({ steps }: StepProgressProps) {
  const stepProgress = useReleaseStore((state) => state.stepProgress)
  const renderStepLinks = (result: Record<string, unknown>) => {
    const links = []

    if (result.promote_ticket_key) {
      links.push(
        <a
          key="promote"
          data-testid="promote-ticket-link"
          href={`https://netskope.atlassian.net/browse/${result.promote_ticket_key}`}
          target="_blank"
          rel="noopener noreferrer"
          className="ticket-link"
        >
          {String(result.promote_ticket_key)}
        </a>
      )
    }

    if (result.deployment_ticket_key) {
      links.push(
        <a
          key="deploy"
          data-testid="deployment-ticket-link"
          href={`https://netskope.atlassian.net/browse/${result.deployment_ticket_key}`}
          target="_blank"
          rel="noopener noreferrer"
          className="ticket-link"
        >
          {String(result.deployment_ticket_key)}
        </a>
      )
    }

    if (result.github_workflow_run_id) {
      // Use URL from result if available, otherwise construct it
      const workflowUrl = result.url || `https://github.com/netSkope/query-engine/actions/runs/${result.github_workflow_run_id}`
      links.push(
        <a
          key="github"
          data-testid="github-run-link"
          href={workflowUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="ticket-link"
        >
          Workflow #{String(result.github_workflow_run_id)}
        </a>
      )
    }

    if (result.jenkins_build_number) {
      links.push(
        <span key="jenkins" className="inline-flex items-center gap-1">
          <a
            data-testid="jenkins-build-link"
            href={String(result.jenkins_job_url)}
            target="_blank"
            rel="noopener noreferrer"
            className="ticket-link"
          >
            Build #{String(result.jenkins_build_number)}
          </a>
          {result.skipped && (
            <span className="text-amber-600 text-xs font-medium">(Skipped)</span>
          )}
        </span>
      )
    }

    return links.length > 0 ? links : null
  }

  return (
    <div className="step-progress">
      {steps.map((step) => (
        <div
          key={step.number}
          data-testid={`step-${step.number}`}
          data-status={step.status}
          className={`step-item ${
            step.status === 'in_progress'
              ? 'active'
              : step.status === 'completed'
              ? 'completed'
              : step.status === 'error'
              ? 'error'
              : ''
          }`}
        >
          <div className="step-number">
            {step.status === 'completed' ? (
              <Check size={16} />
            ) : step.status === 'error' ? (
              <X size={16} />
            ) : step.status === 'in_progress' ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              step.number
            )}
          </div>
          <div className="step-content">
            <div className="step-name">{step.name}</div>
            <div className="step-status">
              {step.status === 'in_progress'
                ? stepProgress[step.number] || 'In progress...'
                : step.status === 'completed'
                ? 'Completed'
                : step.status === 'error'
                ? step.error || 'Failed'
                : 'Pending'}
            </div>
          </div>
          {step.result && step.status === 'completed' && (
            <div className="step-result text-sm text-[var(--color-text-muted)] flex gap-2">
              {renderStepLinks(step.result)}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
