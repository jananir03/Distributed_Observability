export type UnknownRecord = Record<string, unknown>

export interface Trace {
  trace_id: string
  root_service?: string | null
  start_time?: string | null
  end_time?: string | null
  duration_ms?: number | null
  status?: string | null
  completed_at?: string | null
  spans?: Span[]
}

export interface Span {
  span_id: string
  parent_span_id?: string | null
  parent_missing?: boolean
  service_name?: string | null
  operation_name?: string | null
  start_time?: string | null
  end_time?: string | null
  duration_ms?: number | null
  status?: string | null
  error_message?: string | null
}

export interface LogRecord {
  event_id: string
  service_name?: string | null
  level?: string | null
  message?: string | null
  trace_id?: string | null
  span_id?: string | null
  timestamp?: string | null
  attributes?: Record<string, unknown> | null
}

export interface MetricRecord {
  event_id: string
  service_name?: string | null
  metric_name?: string | null
  metric_type?: string | null
  value?: number | null
  unit?: string | null
  timestamp?: string | null
  event_timestamp?: string | null
  trace_id?: string | null
  [key: string]: unknown
}

export interface Dependency {
  source: string
  target: string
  call_count: number
  error_count: number
  average_duration_ms?: number | null
  error_rate?: number | null
}

export interface DiagnosticReport {
  id: number | string
  trace_id: string
  root_service?: string | null
  severity?: string | null
  probable_cause?: string | null
  summary?: string | null
  findings?: Array<Record<string, unknown>>
  evidence?: Record<string, unknown>
  created_at?: string | null
}

export interface Alert {
  id: number | string
  service_name?: string | null
  metric_name?: string | null
  severity?: string | null
  status?: string | null
  summary?: string | null
  current_value?: number | null
  threshold_value?: number | null
  occurrence_count?: number | null
  first_seen_at?: string | null
  last_seen_at?: string | null
  resolved_at?: string | null
  rule_id?: number | null
}

export interface AlertRule {
  id: number
  name: string
  service_name?: string | null
  metric_name: string
  operator?: string
  threshold: number
  severity?: string
  enabled: boolean
  created_at?: string
  updated_at?: string
}

export interface PageResult<T> {
  items: T[]
  total?: number
  limit?: number
  offset?: number
}

export function asArray<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[]
  if (value && typeof value === 'object' && 'items' in value && Array.isArray((value as { items: unknown }).items)) {
    return (value as { items: T[] }).items
  }
  return []
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

export function displayError(error: unknown): string {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = (error as { response?: { data?: unknown; status?: number } }).response
    const data = response?.data
    if (typeof data === 'string') return data
    if (data && typeof data === 'object' && 'detail' in data) {
      const detail = (data as { detail: unknown }).detail
      return typeof detail === 'string' ? detail : JSON.stringify(detail)
    }
    return `API request failed${response?.status ? ` (${response.status})` : ''}.`
  }
  if (error instanceof Error) return error.message
  return 'An unexpected error occurred.'
}
