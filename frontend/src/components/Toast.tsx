/**
 * Toast notification component
 */
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react'
import { useReleaseStore } from '../stores/releaseStore'

export default function Toast() {
  const { toast, clearToast } = useReleaseStore()

  if (!toast) return null

  const icons = {
    success: <CheckCircle className="text-[var(--color-success)]" size={20} />,
    error: <AlertCircle className="text-[var(--color-error)]" size={20} />,
    info: <Info className="text-[var(--color-accent)]" size={20} />,
  }

  return (
    <div className={`toast ${toast.type}`}>
      {icons[toast.type]}
      <span>{toast.message}</span>
      <button
        onClick={clearToast}
        className="ml-4 text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
      >
        <X size={16} />
      </button>
    </div>
  )
}
