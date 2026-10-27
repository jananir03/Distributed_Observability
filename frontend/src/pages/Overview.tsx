import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Alert, Box, Button, Card, CardContent, Chip, Grid, Stack, Typography } from '@mui/material'
import { Activity, AlertTriangle, Clock3, GitBranch, RefreshCw, ScrollText, Waypoints } from 'lucide-react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { observabilityApi } from '../services/api'
import type { Alert as AlertRecord, Dependency, LogRecord, MetricRecord, Trace } from '../types/observability'
import { asArray, asRecord, displayError } from '../types/observability'
import { EmptyState, ErrorState, formatDate, formatDuration, formatNumber, LoadingState, SectionHeading, StatusPill } from '../components/Shared'

type DashboardData = { traces: Trace[]; logs: LogRecord[]; metrics: MetricRecord[]; alerts: AlertRecord[]; deps: Dependency[]; summary: Record<string, unknown> }

function StatCard({ label, value, note, icon, tint }: { label: string; value: string; note: string; icon: ReactNode; tint: string }) {
  return <Card sx={{ height: '100%' }}><CardContent sx={{ p: 2.3 }}>
    <Stack direction="row" justifyContent="space-between" alignItems="flex-start"><Typography color="text.secondary" variant="body2" fontWeight={600}>{label}</Typography><Box className="stat-icon" sx={{ bgcolor: tint }}>{icon}</Box></Stack>
    <Typography variant="h4" sx={{ mt: 2, mb: .6 }}>{value}</Typography><Typography variant="caption" color="text.secondary">{note}</Typography>
  </CardContent></Card>
}

export default function Overview({ onOpenTrace }: { onOpenTrace: (id: string) => void }) {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    const results = await Promise.allSettled([
      observabilityApi.traces({ limit: 100 }),
      observabilityApi.logs({ limit: 100 }),
      observabilityApi.metrics({ limit: 200 }),
      observabilityApi.alerts({ limit: 100 }),
      observabilityApi.dependencies(),
      observabilityApi.metricSummary(),
    ])
    const failures = results.filter((r) => r.status === 'rejected')
    if (failures.length === results.length) {
      setError(displayError((results[0] as PromiseRejectedResult).reason)); setData(null); setLoading(false); return
    }
    const val = (i: number) => results[i].status === 'fulfilled' ? results[i].value : undefined
    const alertPayload = val(3)
    setData({
      traces: asArray<Trace>(val(0)),
      logs: asArray<LogRecord>(val(1)),
      metrics: asArray<MetricRecord>(val(2)),
      alerts: asArray<AlertRecord>(alertPayload),
      deps: asArray<Dependency>(asRecord(val(4)).dependencies),
      summary: asRecord(val(5)),
    })
    if (failures.length) setError('Some panels could not load. Available panels show live API results; use Refresh to retry.')
    setLoading(false)
  }, [])

  useEffect(() => { void load() }, [load])

  const stats = useMemo(() => {
    const traces = data?.traces ?? []
    const logs = data?.logs ?? []
    const metrics = data?.metrics ?? []
    const alerts = (data?.alerts ?? []).filter((a) => (a.status || 'active').toLowerCase() === 'active')
    const errorTraces = traces.filter((t) => ['error', 'failed', 'failure'].includes((t.status || '').toLowerCase())).length
    const errorLogs = logs.filter((l) => ['ERROR', 'CRITICAL', 'FATAL'].includes((l.level || '').toUpperCase())).length
    const latency = traces.map((t) => t.duration_ms).filter((v): v is number => typeof v === 'number')
    const average = latency.length ? latency.reduce((a, b) => a + b, 0) / latency.length : null
    const summary = data?.summary ?? {}
    return { traces: traces.length, logs: logs.length, metrics: metrics.length, alerts: alerts.length, errorTraces, errorLogs, average, services: new Set(traces.map((t) => t.root_service).filter(Boolean)).size, summary }
  }, [data])

  const chartData = useMemo(() => {
    const buckets = new Map<string, { time: string; requests: number; errors: number; latency: number[] }>()
    for (const trace of data?.traces ?? []) {
      const date = trace.start_time ? new Date(trace.start_time) : null
      if (!date || Number.isNaN(date.getTime())) continue
      const key = `${date.getHours().toString().padStart(2, '0')}:${Math.floor(date.getMinutes() / 10) * 10}` 
      const current = buckets.get(key) ?? { time: key, requests: 0, errors: 0, latency: [] }
      current.requests += 1
      if (['error', 'failed', 'failure'].includes((trace.status || '').toLowerCase())) current.errors += 1
      if (typeof trace.duration_ms === 'number') current.latency.push(trace.duration_ms)
      buckets.set(key, current)
    }
    return [...buckets.values()].sort((a, b) => a.time.localeCompare(b.time)).map((v) => ({ time: v.time, requests: v.requests, errors: v.errors, latency: v.latency.length ? Math.round(v.latency.reduce((a, b) => a + b, 0) / v.latency.length) : 0 }))
  }, [data])

  if (loading && !data) return <LoadingState />
  return <Box>
    <SectionHeading title="Overview" subtitle="A live operational view of traces, logs, metrics and service health." action={<Button onClick={() => void load()} variant="outlined" startIcon={<RefreshCw size={16} />}>Refresh data</Button>} />
    {error && <Box sx={{ mb: 2 }}><Alert severity="warning">{error}</Alert></Box>}
    {data === null && error && <ErrorState message={error} onRetry={() => void load()} />}
    {data && <>
      <Grid container spacing={2} sx={{ mb: 2.5 }}>
        <Grid item xs={12} sm={6} xl={3}><StatCard label="Traces observed" value={formatNumber(stats.traces, 0)} note="Latest 100 trace records" icon={<Waypoints size={20} color="#5b5bd6" />} tint="#f0efff" /></Grid>
        <Grid item xs={12} sm={6} xl={3}><StatCard label="Error traces" value={formatNumber(stats.errorTraces, 0)} note={`${stats.traces ? ((stats.errorTraces / stats.traces) * 100).toFixed(1) : '0.0'}% of loaded traces` } icon={<AlertTriangle size={20} color="#d44955" />} tint="#fff0f1" /></Grid>
        <Grid item xs={12} sm={6} xl={3}><StatCard label="Average trace duration" value={formatDuration(stats.average)} note="Calculated from loaded trace durations" icon={<Clock3 size={20} color="#bd7a1e" />} tint="#fff7e8" /></Grid>
        <Grid item xs={12} sm={6} xl={3}><StatCard label="Active alerts" value={formatNumber(stats.alerts, 0)} note="Alerts with active status" icon={<Activity size={20} color="#148c78" />} tint="#e9fbf5" /></Grid>
      </Grid>
      <Grid container spacing={2}>
        <Grid item xs={12} lg={8}>
          <Card sx={{ height: '100%' }}><CardContent sx={{ p: 2.5 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}><Box><Typography variant="h6">Trace activity</Typography><Typography variant="body2" color="text.secondary">Grouped from the latest trace start times</Typography></Box><ChipLabel text="API data" /></Stack>
            {chartData.length ? <Box sx={{ width: '100%', height: 270 }}><ResponsiveContainer><LineChart data={chartData} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}><CartesianGrid strokeDasharray="3 3" stroke="#edf0f5" /><XAxis dataKey="time" tickLine={false} axisLine={false} tick={{ fill: '#8993a4', fontSize: 11 }} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: '#8993a4', fontSize: 11 }} /><Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #e8ecf3' }} /><Line type="monotone" dataKey="requests" name="Traces" stroke="#5b5bd6" strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} /><Line type="monotone" dataKey="errors" name="Errors" stroke="#d44955" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></Box> : <EmptyState title="Not enough timestamped traces" detail="The chart appears when trace records include valid start_time values." />}
          </CardContent></Card>
        </Grid>
        <Grid item xs={12} lg={4}>
          <Card sx={{ height: '100%' }}><CardContent sx={{ p: 2.5 }}>
            <Typography variant="h6">Signal inventory</Typography><Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Latest records returned by the gateway</Typography>
            <Stack gap={2}>
              {[['Logs loaded', stats.logs, <ScrollText size={18} />], ['Metric samples loaded', stats.metrics, <Activity size={18} />], ['Services in trace set', stats.services, <GitBranch size={18} />], ['Dependency edges', data.deps.length, <Waypoints size={18} />]].map(([label, value, icon]) => <Stack key={String(label)} direction="row" alignItems="center" gap={1.5}><Box className="mini-icon">{icon as ReactNode}</Box><Box sx={{ flex: 1 }}><Typography variant="body2" fontWeight={650}>{label as string}</Typography></Box><Typography fontWeight={750}>{String(value)}</Typography></Stack>)}
            </Stack>
            <Alert severity="info" sx={{ mt: 2.5 }}>Dashboard values are based on records returned by the backend; they are not synthetic monitoring data.</Alert>
          </CardContent></Card>
        </Grid>
        <Grid item xs={12} lg={7}>
          <Card><CardContent sx={{ p: 2.5 }}><Typography variant="h6">Recent traces</Typography><Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>Select a trace to inspect its spans and correlated logs.</Typography>
            {data.traces.length ? <Stack divider={<Box sx={{ borderBottom: '1px solid #edf0f5' }} />} gap={0}>{data.traces.slice(0, 6).map((trace) => <Stack key={trace.trace_id} direction={{ xs: 'column', sm: 'row' }} alignItems={{ sm: 'center' }} gap={1} sx={{ py: 1.3 }}><Box sx={{ flex: 1, minWidth: 0 }}><Typography className="mono" fontSize={13} fontWeight={650} noWrap>{trace.trace_id}</Typography><Typography variant="caption" color="text.secondary">{trace.root_service || 'Unknown service'} · {formatDate(trace.start_time)}</Typography></Box><Typography variant="body2" sx={{ minWidth: 70 }}>{formatDuration(trace.duration_ms)}</Typography><StatusPill value={trace.status} /><Button size="small" onClick={() => onOpenTrace(trace.trace_id)}>Inspect</Button></Stack>)}</Stack> : <EmptyState />}
          </CardContent></Card>
        </Grid>
        <Grid item xs={12} lg={5}>
          <Card><CardContent sx={{ p: 2.5 }}><Typography variant="h6">Recent alerts</Typography><Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>Current alert records from the alert service.</Typography>
            {data.alerts.length ? <Stack gap={1.5}>{data.alerts.slice(0, 5).map((alert) => <Box key={String(alert.id)} className="alert-row"><Stack direction="row" justifyContent="space-between" alignItems="center" gap={1}><Typography fontWeight={700} variant="body2">{alert.summary || `${alert.metric_name || 'Alert'} threshold exceeded`}</Typography><StatusPill value={alert.severity} /></Stack><Typography variant="caption" color="text.secondary">{alert.service_name || 'All services'} · {formatDate(alert.last_seen_at)}</Typography></Box>)}</Stack> : <EmptyState title="No alert records" detail="The alert API returned no records." />}
          </CardContent></Card>
        </Grid>
      </Grid>
    </>}
  </Box>
}

function ChipLabel({ text }: { text: string }) {
  return <Box sx={{ px: 1.1, py: .5, borderRadius: 2, bgcolor: '#f2f2ff', color: '#5b5bd6', fontSize: 11, fontWeight: 800 }}>{text}</Box>
}
