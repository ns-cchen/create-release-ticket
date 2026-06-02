/**
 * ReleaseCard component - Summary card for a release
 */
import { useNavigate } from 'react-router-dom'
import { Clock, CheckCircle, AlertCircle, PlayCircle, Square, CheckSquare } from 'lucide-react'
import type { ReleaseListItem } from '../types/api'
import { useReleaseStore } from '../stores/releaseStore'

interface ReleaseCardProps {
  release: ReleaseListItem
  selectionMode?: boolean
}

const statusIcons = {
  not_started: PlayCircle,
  in_progress: Clock,
  completed: CheckCircle,
  error: AlertCircle,
}

const statusBadges = {
  not_started: 'badge-neutral',
  in_progress: 'badge-info',
  completed: 'badge-success',
  error: 'badge-error',
}

const statusLabels = {
  not_started: 'Not Started',
  in_progress: 'In Progress',
  completed: 'Completed',
  error: 'Error',
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function extractVersionShort(version: string): string {
  // queryservice-release-2025.12.2.0.18496 -> 2025.12.2.0.18496
  return version.replace('queryservice-release-', '')
}

export default function ReleaseCard({ release, selectionMode = false }: ReleaseCardProps) {
  const navigate = useNavigate()
  const { selectedIds, toggleSelection } = useReleaseStore()
  const StatusIcon = statusIcons[release.status]
  const isSelected = selectedIds.has(release.id)

  const handleClick = () => {
    if (selectionMode) {
      toggleSelection(release.id)
    } else {
      navigate(`/release/${release.id}`)
    }
  }

  const handleCheckboxClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    toggleSelection(release.id)
  }

  return (
    <div
      className={`release-card ${isSelected ? 'ring-2 ring-[var(--color-accent)]' : ''}`}
      onClick={handleClick}
    >
      {selectionMode ? (
        <button
          className="flex-shrink-0 p-1 hover:bg-[var(--color-bg-hover)] rounded"
          onClick={handleCheckboxClick}
        >
          {isSelected ? (
            <CheckSquare size={24} className="text-[var(--color-accent)]" />
          ) : (
            <Square size={24} className="text-[var(--color-text-muted)]" />
          )}
        </button>
      ) : (
        <StatusIcon
          size={24}
          className={
            release.status === 'completed'
              ? 'text-[var(--color-success)]'
              : release.status === 'error'
              ? 'text-[var(--color-error)]'
              : release.status === 'in_progress'
              ? 'text-[var(--color-accent)]'
              : 'text-[var(--color-text-muted)]'
          }
        />
      )}

      <div className="release-version">
        {extractVersionShort(release.build_version)}
      </div>

      <div className="release-info">
        <span className={`badge ${statusBadges[release.status]}`}>
          {statusLabels[release.status]}
        </span>

        {release.started_at && (
          <span className="text-sm text-[var(--color-text-secondary)]">
            {formatDate(release.started_at)}
          </span>
        )}
      </div>

      <div className="release-tickets">
        {release.promote_ticket_key && (
          <a
            href={`https://netskope.atlassian.net/browse/${release.promote_ticket_key}`}
            target="_blank"
            rel="noopener noreferrer"
            className="ticket-link"
            onClick={(e) => e.stopPropagation()}
          >
            {release.promote_ticket_key}
          </a>
        )}
        {release.deployment_ticket_key && (
          <a
            href={`https://netskope.atlassian.net/browse/${release.deployment_ticket_key}`}
            target="_blank"
            rel="noopener noreferrer"
            className="ticket-link"
            onClick={(e) => e.stopPropagation()}
          >
            {release.deployment_ticket_key}
          </a>
        )}
      </div>
    </div>
  )
}
