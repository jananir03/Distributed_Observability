import axios from 'axios'
import type { Alert, AlertRule, Dependency, DiagnosticReport, LogRecord, MetricRecord, PageResult, Trace } from '../types/observability'

const baseURL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001').replace(/\/+$/, '')
const timeout = Number(import.meta.env.VITE_REQUEST_TIMEOUT_MS || 12000)

export const api = axios.create({
  baseURL,
  timeout: Number.isFinite(timeout) ? timeout : 12000,
  headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
})

export const apiBaseUrl = baseURL

export const observabilityApi = {
  health: async () => (await api.get('/health')).data as Record<string, unknown>,
  readiness: async () => (await api.get('/ready')).data as Record<string, unknown>,
  traces: async (params: Record<string, string | number | undefined> = {}) =>
    (await api.get<PageResult<Trace>>('/api/v1/traces', { params: cleanParams({ limit: 50, offset: 0, ...params }) })).data,
  trace: async (traceId: string) => (await api.get<Trace>(`/api/v1/traces/${encodeURIComponent(traceId)}`)).data,
  logs: async (params: Record<string, string | number | undefined> = {}) =>
    (await api.get<PageResult<LogRecord>>('/api/v1/logs', { params: cleanParams({ limit: 100, offset: 0, ...params }) })).data,
  traceLogs: async (traceId: string) =>
    (await api.get<PageResult<LogRecord>>(`/api/v1/traces/${encodeURIComponent(traceId)}/logs`, { params: { limit: 200, offset: 0 } })).data,
  metrics: async (params: Record<string, string | number | undefined> = {}) =>
    (await api.get<PageResult<MetricRecord>>('/api/v1/metrics', { params: cleanParams({ limit: 200, offset: 0, ...params }) })).data,
  metricSummary: async () => (await api.get('/api/v1/metrics/summary')).data as Record<string, unknown>,
  metricServices: async () => (await api.get('/api/v1/metrics/services')).data as unknown,
  metricTimeseries: async (params: Record<string, string | number | undefined> = {}) =>
    (await api.get('/api/v1/metrics/timeseries', { params: cleanParams(params) })).data as unknown,
  metricLatency: async (params: Record<string, string | number | undefined> = {}) =>
    (await api.get('/api/v1/metrics/latency', { params: cleanParams(params) })).data as unknown,
  dependencies: async () => (await api.get('/api/v1/dependencies')).data as { services?: string[]; dependencies?: Dependency[] },
  serviceDependencies: async (service: string) =>
    (await api.get(`/api/v1/dependencies/${encodeURIComponent(service)}`)).data as { service_name: string; incoming: Dependency[]; outgoing: Dependency[] },
  diagnostics: async (params: Record<string, string | number | undefined> = {}) =>
    (await api.get<PageResult<DiagnosticReport>>('/api/v1/diagnostics', { params: cleanParams({ limit: 100, offset: 0, ...params }) })).data,
  diagnostic: async (id: string | number) =>
    (await api.get<DiagnosticReport>(`/api/v1/diagnostics/${encodeURIComponent(String(id))}`)).data,
  analyzeTrace: async (traceId: string) =>
    (await api.post<DiagnosticReport>(`/api/v1/diagnostics/analyze/${encodeURIComponent(traceId)}`)).data,
  alerts: async (params: Record<string, string | number | undefined> = {}) =>
    (await api.get<PageResult<Alert> | Alert[]>('/api/v1/alerts', { params: cleanParams(params) })).data,
  alertRules: async () => (await api.get<AlertRule[]>('/api/v1/alerts/rules')).data,
  updateAlert: async (id: string | number, status: string) =>
    (await api.patch<Alert>(`/api/v1/alerts/${encodeURIComponent(String(id))}`, { status })).data,
  updateRule: async (id: number, payload: Partial<AlertRule>) =>
    (await api.patch<AlertRule>(`/api/v1/alerts/rules/${id}`, payload)).data,
  evaluateAlerts: async () => (await api.post('/api/v1/alerts/evaluate')).data as unknown,
  unifiedSearch: async (params: Record<string, string | number | undefined> = {}) =>
    (await api.get('/api/v1/search', { params: cleanParams(params) })).data as Record<string, unknown>,
}

function cleanParams(params: Record<string, string | number | undefined>): Record<string, string | number> {
  return Object.fromEntries(Object.entries(params).filter((entry): entry is [string, string | number] => entry[1] !== undefined && entry[1] !== ''))
}
