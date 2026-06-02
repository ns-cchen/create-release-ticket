/**
 * API Types for Create Release Ticket
 */

export interface StepInfo {
  number: number
  name: string
  key: string
  status: 'pending' | 'in_progress' | 'completed' | 'error'
  started_at?: string
  completed_at?: string
  result?: Record<string, unknown>
  error?: string
}

export interface ReleaseListItem {
  id: string
  build_version: string
  rollback_version: string
  status: 'not_started' | 'in_progress' | 'completed' | 'error'
  current_step: string
  current_step_number: number
  started_at?: string
  completed_at?: string
  promote_ticket_key?: string
  deployment_ticket_key?: string
  error_message?: string
}

export interface ReleaseResponse {
  id: string
  build_version: string
  rollback_version: string
  ref: string
  status: 'not_started' | 'in_progress' | 'completed' | 'error'
  current_step: string
  current_step_number: number

  // Derived values
  current_branch?: string
  previous_branch?: string
  jira_ids: string[]

  // Created resources
  promote_ticket_key?: string
  promote_ticket_id?: string
  deployment_ticket_key?: string
  deployment_ticket_id?: string
  github_workflow_run_id?: number
  jenkins_build_number?: number
  jenkins_job_url?: string
  previous_deployment_ticket_key?: string

  // Timestamps
  started_at?: string
  completed_at?: string
  updated_at?: string

  // Error info
  error_message?: string
  error_step?: string

  // Step details
  steps: StepInfo[]

  // Options
  dry_run: boolean
  start_from_step: number
}

export interface ReleaseCreateInput {
  build_version: string
  rollback_version: string
  ref?: string
  previous_branch?: string
  jira_ids?: string[]
  previous_deployment_ticket?: string
  dry_run?: boolean

  // Start From Step (replaces stop_after)
  start_from_step?: number // 1-7, default 1

  // Pre-existing artifacts
  promote_ticket_key?: string
  github_workflow_run_id?: number
  jenkins_build_number?: number
  jenkins_job_url?: string
  deployment_ticket_key?: string
  max_consecutive_poll_failures?: number
}

export interface ReleaseResumeInput {
  github_workflow_run_id?: number
  jenkins_build_number?: number
  jenkins_job_url?: string
}

export interface CleanupResponse {
  success: boolean
  message: string
  cleaned_resources: string[]
}

export interface PurgeResponse {
  deleted_count: number
  deleted_ids: string[]
}

// WebSocket message types
export type WSMessageType =
  | 'step_start'
  | 'step_progress'
  | 'step_complete'
  | 'workflow_complete'
  | 'workflow_error'

export interface WSMessage {
  type: WSMessageType
  release_id: string
  step?: Partial<StepInfo>
  progress?: string
  error?: string
  data?: Record<string, unknown>
}
