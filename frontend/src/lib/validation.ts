/**
 * Validation utilities for release form inputs
 */

export interface ValidationResult {
  valid: boolean
  error?: string
}

/**
 * Version format: queryservice-release-YYYY.MM.W.P.DRONE
 * - YYYY: 4-digit year
 * - MM: Month (1-12)
 * - W: Week (1-6, months can span up to 6 calendar weeks)
 * - P: Patch (0-9+)
 * - DRONE: Build number (positive integer)
 */
const VERSION_REGEX = /^queryservice-release-(\d{4})\.(\d{1,2})\.(\d)\.(\d+)\.(\d+)$/

export interface ParsedVersion {
  year: number
  month: number
  week: number
  patch: number
  drone: number
}

/**
 * Parse a version string into its components
 */
export function parseVersion(version: string): ParsedVersion | null {
  const match = version.match(VERSION_REGEX)
  if (!match) return null

  return {
    year: parseInt(match[1], 10),
    month: parseInt(match[2], 10),
    week: parseInt(match[3], 10),
    patch: parseInt(match[4], 10),
    drone: parseInt(match[5], 10),
  }
}

/**
 * Validate version format with semantic constraints
 * - Month must be 1-12
 * - Week must be 1-6 (months can span up to 6 calendar weeks)
 */
export function validateVersionFormat(version: string): ValidationResult {
  if (!version) {
    return { valid: false, error: 'Version is required' }
  }

  const parsed = parseVersion(version)
  if (!parsed) {
    return {
      valid: false,
      error: 'Invalid format. Expected: queryservice-release-YYYY.MM.W.P.DRONE',
    }
  }

  if (parsed.month < 1 || parsed.month > 12) {
    return { valid: false, error: `Invalid month: ${parsed.month}. Must be 1-12` }
  }

  if (parsed.week < 1 || parsed.week > 6) {
    return { valid: false, error: `Invalid week: ${parsed.week}. Must be 1-6` }
  }

  if (parsed.year < 2020 || parsed.year > 2100) {
    return { valid: false, error: `Invalid year: ${parsed.year}` }
  }

  return { valid: true }
}

/**
 * Compare two versions to ensure rollback < build
 * Returns negative if a < b, positive if a > b, 0 if equal
 */
export function compareVersions(a: ParsedVersion, b: ParsedVersion): number {
  // Compare year
  if (a.year !== b.year) return a.year - b.year
  // Compare month
  if (a.month !== b.month) return a.month - b.month
  // Compare week
  if (a.week !== b.week) return a.week - b.week
  // Compare patch
  if (a.patch !== b.patch) return a.patch - b.patch
  // Compare drone build number
  return a.drone - b.drone
}

/**
 * Validate that rollback version is older than build version
 */
export function validateVersionOrder(
  buildVersion: string,
  rollbackVersion: string
): ValidationResult {
  const build = parseVersion(buildVersion)
  const rollback = parseVersion(rollbackVersion)

  if (!build || !rollback) {
    // Let individual validation handle format errors
    return { valid: true }
  }

  const comparison = compareVersions(rollback, build)

  if (comparison >= 0) {
    return {
      valid: false,
      error: 'Rollback version must be older than build version',
    }
  }

  return { valid: true }
}

/**
 * Jira ID format: PROJECT-NUMBER (e.g., DINT-1234, EP-5678)
 */
const JIRA_ID_REGEX = /^[A-Z][A-Z0-9]+-\d+$/

/**
 * Validate a single Jira ID format
 */
export function validateJiraId(jiraId: string): ValidationResult {
  const trimmed = jiraId.trim()
  if (!trimmed) {
    return { valid: false, error: 'Empty Jira ID' }
  }

  if (!JIRA_ID_REGEX.test(trimmed)) {
    return {
      valid: false,
      error: `Invalid Jira ID format: ${trimmed}. Expected format: PROJECT-NUMBER`,
    }
  }

  return { valid: true }
}

/**
 * Validate a comma-separated list of Jira IDs
 * - Check format of each ID
 * - Check for duplicates
 */
export function validateJiraIds(input: string): ValidationResult {
  if (!input.trim()) {
    // Empty is valid (optional field)
    return { valid: true }
  }

  const ids = input.split(',').map((s) => s.trim()).filter(Boolean)
  const seen = new Set<string>()
  const errors: string[] = []

  for (const id of ids) {
    const result = validateJiraId(id)
    if (!result.valid) {
      errors.push(result.error!)
    }

    const normalized = id.toUpperCase()
    if (seen.has(normalized)) {
      errors.push(`Duplicate Jira ID: ${id}`)
    }
    seen.add(normalized)
  }

  if (errors.length > 0) {
    return { valid: false, error: errors.join('; ') }
  }

  return { valid: true }
}

/**
 * Combined form validation state
 */
export interface FormValidation {
  buildVersion: ValidationResult
  rollbackVersion: ValidationResult
  versionOrder: ValidationResult
  jiraIds: ValidationResult
  isValid: boolean
}

/**
 * Validate the entire form
 */
export function validateReleaseForm(
  buildVersion: string,
  rollbackVersion: string,
  jiraIdsInput: string
): FormValidation {
  const buildVersionResult = validateVersionFormat(buildVersion)
  const rollbackVersionResult = validateVersionFormat(rollbackVersion)
  const versionOrderResult = validateVersionOrder(buildVersion, rollbackVersion)
  const jiraIdsResult = validateJiraIds(jiraIdsInput)

  const isValid =
    buildVersionResult.valid &&
    rollbackVersionResult.valid &&
    versionOrderResult.valid &&
    jiraIdsResult.valid

  return {
    buildVersion: buildVersionResult,
    rollbackVersion: rollbackVersionResult,
    versionOrder: versionOrderResult,
    jiraIds: jiraIdsResult,
    isValid,
  }
}
