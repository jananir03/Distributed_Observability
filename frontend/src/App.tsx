import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, AppBar, Avatar, Box, Button, Card, CardContent, Chip, CircularProgress, Divider, Drawer, FormControl, Grid, IconButton, InputAdornment, InputLabel, MenuItem, Select, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Toolbar, Tooltip, Typography } from '@mui/material'
import { Activity, BellRing, Boxes, ChevronRight, CircleHelp, Clock3, Command, FileSearch, Gauge, GitBranch, LayoutDashboard, Logs, Menu, RefreshCw, Search, Settings2, ShieldAlert, Waypoints, X } from 'lucide-react'
import Overview from './pages/Overview'
import { ConnectionBadge, EmptyState, ErrorState, formatDate, formatDuration, formatNumber, LoadingState, SectionHeading, StatusPill } from './components/Shared'
import { apiBaseUrl, observabilityApi } from './services/api'
import type { Alert as AlertRecord, AlertRule, Dependency, DiagnosticReport, LogRecord, MetricRecord, Span, Trace } from './types/observability'
import { asArray, asRecord, displayError } from './types/observability'

const drawerWidth = 246
type Page = 'Overview' | 'Traces' | 'Logs' | 'Metrics' | 'Dependencies' | 'Diagnostics' | 'Alerts'
const navItems: { label: Page; icon: typeof LayoutDashboard; hint: string }[] = [
  { label: 'Overview', icon: LayoutDashboard, hint: 'Operational summary' },
  { label: 'Traces', icon: Waypoints, hint: 'Trace explorer' },
  { label: 'Logs', icon: Logs, hint: 'Searchable events' },
  { label: 'Metrics', icon: Gauge, hint: 'Measurements' },
  { label: 'Dependencies', icon: GitBranch, hint: 'Service map' },
  { label: 'Diagnostics', icon: ShieldAlert, hint: 'Root-cause evidence' },
  { label: 'Alerts', icon: BellRing, hint: 'Alert center' },
]

export default function App() {
  const [page, setPage] = useState<Page>('Overview')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [gatewayOnline, setGatewayOnline] = useState<boolean | null>(null)
  const [gatewayMessage, setGatewayMessage] = useState('')
  const [selectedTrace, setSelectedTrace] = useState('')
  const [globalSearch, setGlobalSearch] = useState('')

  const checkGateway = useCallback(async () => {
    try {
      await observabilityApi.health()
      setGatewayOnline(true); setGatewayMessage('')
    } catch (error) {
      setGatewayOnline(false); setGatewayMessage(displayError(error))
    }
  }, [])

  useEffect(() => { void checkGateway() }, [checkGateway])

  const openTrace = (id: string) => {
    setSelectedTrace(id); setPage('Traces')
  }

  const handleNav = (next: Page) => { setPage(next); setMobileOpen(false) }

  const drawer = <Box className="sidebar-content">
    <Box className="brand"><Box className="brand-mark"><Activity size={22} /></Box><Box><Typography fontWeight={800} fontSize={17} lineHeight={1.2}>pulse<span className="brand-dot">.</span></Typography><Typography fontSize={10} color="#9aa5b8" letterSpacing="1.4px">OBSERVABILITY</Typography></Box></Box>
    <Box className="workspace"><Box className="workspace-badge">DO</Box><Box sx={{ flex: 1, minWidth: 0 }}><Typography fontSize={12} fontWeight={750}>Distributed systems</Typography><Typography fontSize={10} color="#9aa5b8">Local environment</Typography></Box><ChevronRight size={15} color="#9aa5b8" /></Box>
    <Typography className="nav-label">WORKSPACE</Typography>
    <Stack gap={.45}>{navItems.map((item) => { const Icon = item.icon; return <Box key={item.label} component="button" className={`nav-item ${page === item.label ? 'active' : ''}`} onClick={() => handleNav(item.label)} title={item.hint}><Icon size={18} strokeWidth={1.9} /><span>{item.label}</span>{item.label === 'Alerts' && <span className="nav-count">●</span>}</Box> })}</Stack>
    <Box sx={{ flex: 1 }} />
    <Box className="sidebar-status"><Box className={`status-dot ${gatewayOnline ? 'online' : gatewayOnline === false ? 'offline' : ''}`} /><Box sx={{ flex: 1 }}><Typography fontSize={12} fontWeight={700}>API Gateway</Typography><Typography fontSize={10} color="#9aa5b8">{gatewayOnline ? 'Connected · :8001' : gatewayOnline === false ? 'Connection issue' : 'Checking connection'}</Typography></Box><Tooltip title="Check gateway"><IconButton size="small" onClick={() => void checkGateway()} sx={{ color: '#b8c3d6' }}><RefreshCw size={14} /></IconButton></Tooltip></Box>
    <Box className="sidebar-footer"><CircleHelp size={15} /><span>Observability console</span><span className="version">v1.0</span></Box>
  </Box>

  return <Box className="app-shell">
    <Drawer variant="permanent" sx={{ display: { xs: 'none', md: 'block' }, '& .MuiDrawer-paper': { width: drawerWidth, boxSizing: 'border-box', bgcolor: '#111a2b', color: '#e8edf7', border: 0 } }}>{drawer}</Drawer>
    <Drawer variant="temporary" open={mobileOpen} onClose={() => setMobileOpen(false)} sx={{ display: { xs: 'block', md: 'none' }, '& .MuiDrawer-paper': { width: drawerWidth, boxSizing: 'border-box', bgcolor: '#111a2b', color: '#e8edf7', border: 0 } }}>{drawer}</Drawer>
    <Box component="main" className="main-shell" sx={{ ml: { xs: 0, md: `${drawerWidth}px` } }}>
      <AppBar position="sticky" elevation={0} color="inherit" className="topbar"><Toolbar sx={{ minHeight: '72px !important', px: { xs: 2, md: 3.5 }, gap: 1.5 }}>
        <IconButton onClick={() => setMobileOpen(true)} sx={{ display: { md: 'none' } }}><Menu size={20} /></IconButton>
        <Box sx={{ flex: 1 }}><Typography variant="caption" color="text.secondary">Workspace / {page}</Typography><Typography fontWeight={750} fontSize={17}>{page === 'Overview' ? 'Observability overview' : page}</Typography></Box>
        <TextField size="small" placeholder="Search trace ID…" value={globalSearch} onChange={(e) => setGlobalSearch(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && globalSearch.trim()) openTrace(globalSearch.trim()) }} sx={{ width: { xs: 145, sm: 240 }, '& .MuiOutlinedInput-root': { bgcolor: '#f8f9fc', borderRadius: 2.5, fontSize: 13 } }} InputProps={{ startAdornment: <InputAdornment position="start"><Search size={16} color="#8993a4" /></InputAdornment> }} />
        <ConnectionBadge online={gatewayOnline} />
        <Avatar sx={{ width: 34, height: 34, bgcolor: '#e8e8ff', color: '#5555c8', fontSize: 12, fontWeight: 800 }}>DO</Avatar>
      </Toolbar></AppBar>
      <Box className="page-content">
        {gatewayOnline === false && <Alert severity="warning" sx={{ mb: 2 }} action={<Button size="small" onClick={() => void checkGateway()}>Retry</Button>}>Cannot reach the API Gateway at <code>{apiBaseUrl}</code>. Check that your backend containers are running and the gateway is reachable. {gatewayMessage}</Alert>}
        {page === 'Overview' && <Overview onOpenTrace={openTrace} />}
        {page === 'Traces' && <TracesPage initialTrace={selectedTrace} onOpenTrace={openTrace} />}
        {page === 'Logs' && <LogsPage onOpenTrace={openTrace} />}
        {page === 'Metrics' && <MetricsPage />}
        {page === 'Dependencies' && <DependenciesPage />}
        {page === 'Diagnostics' && <DiagnosticsPage onOpenTrace={openTrace} />}
        {page === 'Alerts' && <AlertsPage />}
        <Box className="page-footer"><span>Pulse Observability</span><span>Live backend data · Gateway {apiBaseUrl}</span></Box>
      </Box>
    </Box>
  </Box>
}

function TracesPage({ initialTrace, onOpenTrace }: { initialTrace: string; onOpenTrace: (id: string) => void }) {
  const [traces, setTraces] = useState<Trace[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState(initialTrace)
  const [status, setStatus] = useState('all')
  const [detail, setDetail] = useState<Trace | null>(null)
  const [logs, setLogs] = useState<LogRecord[]>([])
  const [detailError, setDetailError] = useState('')
  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      if (search.trim() && search.trim().length > 8) {
        const trace = await observabilityApi.trace(search.trim()); setTraces([trace])
      } else {
        const result = await observabilityApi.traces({ limit: 100, trace_status: status === 'all' ? undefined : status })
        setTraces(asArray<Trace>(result).filter((t) => !search.trim() || t.trace_id.toLowerCase().includes(search.trim().toLowerCase()) || (t.root_service || '').toLowerCase().includes(search.trim().toLowerCase())))
      }
    } catch (e) { setError(displayError(e)); setTraces([]) } finally { setLoading(false) }
  }, [search, status, initialTrace])
  useEffect(() => { void load() }, [load])
  const inspect = async (id: string) => {
    setDetailError(''); setDetail(null); setLogs([])
    try {
      const [trace, relatedLogs] = await Promise.all([observabilityApi.trace(id), observabilityApi.traceLogs(id)])
      setDetail(trace); setLogs(asArray<LogRecord>(relatedLogs))
    } catch (e) { setDetailError(displayError(e)) }
  }
  return <Box><SectionHeading title="Trace explorer" subtitle="Search distributed requests, inspect spans, and correlate logs." action={<Button variant="outlined" startIcon={<RefreshCw size={15} />} onClick={() => void load()}>Refresh</Button>} />
    <Card sx={{ mb: 2 }}><CardContent><Stack direction={{ xs: 'column', sm: 'row' }} gap={1.5}><TextField fullWidth size="small" label="Trace ID or service" value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void load() }} /><FormControl size="small" sx={{ minWidth: 150 }}><InputLabel>Status</InputLabel><Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)}><MenuItem value="all">All statuses</MenuItem><MenuItem value="ok">OK</MenuItem><MenuItem value="error">Error</MenuItem><MenuItem value="slow">Slow</MenuItem></Select></FormControl><Button variant="contained" onClick={() => void load()} startIcon={<Search size={16} />}>Search</Button></Stack></CardContent></Card>
    {error && <Box sx={{ mb: 2 }}><ErrorState message={error} onRetry={() => void load()} /></Box>}
    <Card><CardContent sx={{ p: 0 }}><TableContainer><Table size="small"><TableHead><TableRow>{['Trace ID', 'Root service', 'Started', 'Duration', 'Status', ''].map((v) => <TableCell key={v}>{v}</TableCell>)}</TableRow></TableHead><TableBody>{loading ? <TableRow><TableCell colSpan={6}><LoadingState /></TableCell></TableRow> : traces.map((t) => <TableRow hover key={t.trace_id}><TableCell><Typography className="mono" fontSize={12} fontWeight={650}>{t.trace_id}</Typography></TableCell><TableCell>{t.root_service || '—'}</TableCell><TableCell>{formatDate(t.start_time)}</TableCell><TableCell>{formatDuration(t.duration_ms)}</TableCell><TableCell><StatusPill value={t.status} /></TableCell><TableCell><Button size="small" onClick={() => void inspect(t.trace_id)}>Inspect</Button></TableCell></TableRow>)}</TableBody></Table></TableContainer>{!loading && traces.length === 0 && <EmptyState title="No matching traces" detail="Try a different trace ID, service, or status." />}</CardContent></Card>
    {detailError && <Alert severity="error" sx={{ mt: 2 }}>{detailError}</Alert>}
    {detail && <Box sx={{ mt: 2.5 }}><SectionHeading title="Trace detail" subtitle={detail.trace_id} action={<Button onClick={() => onOpenTrace(detail.trace_id)} variant="outlined">Keep selected</Button>} /><Grid container spacing={2}><Grid item xs={12} md={4}><Card><CardContent><Typography color="text.secondary" variant="body2">Root service</Typography><Typography variant="h6">{detail.root_service || 'Unknown'}</Typography><Typography color="text.secondary" variant="body2" sx={{ mt: 2 }}>Total duration</Typography><Typography variant="h5">{formatDuration(detail.duration_ms)}</Typography><Typography color="text.secondary" variant="body2" sx={{ mt: 2 }}>Trace status</Typography><StatusPill value={detail.status} /></CardContent></Card></Grid><Grid item xs={12} md={8}><Card><CardContent><Typography variant="h6" sx={{ mb: 1.5 }}>Span timeline</Typography>{detail.spans?.length ? <Stack gap={1.2}>{detail.spans.map((span: Span) => <Box key={span.span_id} className={`span-row ${['error','failed','failure'].includes((span.status || '').toLowerCase()) ? 'span-error' : ''}`}><Stack direction="row" alignItems="center" justifyContent="space-between" gap={1}><Typography fontWeight={700} fontSize={13}>{span.operation_name || 'Operation'}</Typography><StatusPill value={span.status} /></Stack><Typography variant="caption" color="text.secondary">{span.service_name || 'Unknown service'} · {span.span_id}{span.parent_missing ? ' · Parent span missing' : ''}</Typography><Stack direction="row" gap={2} sx={{ mt: .7 }}><Typography variant="caption">Duration: <b>{formatDuration(span.duration_ms)}</b></Typography><Typography variant="caption">Start: {formatDate(span.start_time)}</Typography></Stack>{span.error_message && <Typography variant="body2" color="error" sx={{ mt: .7 }}>{span.error_message}</Typography>}</Box>)}</Stack> : <EmptyState title="No spans in this trace" />}</CardContent></Card></Grid><Grid item xs={12}><Card><CardContent><Typography variant="h6">Correlated logs</Typography>{logs.length ? <TableContainer><Table size="small"><TableHead><TableRow><TableCell>Time</TableCell><TableCell>Level</TableCell><TableCell>Service</TableCell><TableCell>Message</TableCell></TableRow></TableHead><TableBody>{logs.map((l) => <TableRow key={l.event_id}><TableCell>{formatDate(l.timestamp)}</TableCell><TableCell><StatusPill value={l.level} /></TableCell><TableCell>{l.service_name}</TableCell><TableCell>{l.message}</TableCell></TableRow>)}</TableBody></Table></TableContainer> : <EmptyState title="No correlated logs" detail="The log API returned no records for this trace." />}</CardContent></Card></Grid></Grid></Box>}
  </Box>
}

function LogsPage({ onOpenTrace }: { onOpenTrace: (id: string) => void }) {
  const [logs, setLogs] = useState<LogRecord[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState('')
  const [search, setSearch] = useState(''); const [level, setLevel] = useState('all'); const [service, setService] = useState('')
  const load = useCallback(async () => { setLoading(true); setError(''); try { const result = await observabilityApi.logs({ limit: 200, level: level === 'all' ? undefined : level, service_name: service || undefined }); setLogs(asArray<LogRecord>(result).filter((l) => !search || [l.message, l.trace_id, l.service_name, l.event_id].some((v) => String(v || '').toLowerCase().includes(search.toLowerCase())))) } catch (e) { setError(displayError(e)); setLogs([]) } finally { setLoading(false) } }, [level, service, search])
  useEffect(() => { void load() }, [load])
  const services = useMemo(() => [...new Set(logs.map((l) => l.service_name).filter((s): s is string => Boolean(s)))].sort(), [logs])
  return <Box><SectionHeading title="Log explorer" subtitle="Search messages and move from a log line to its distributed trace." action={<Button variant="outlined" startIcon={<RefreshCw size={15} />} onClick={() => void load()}>Refresh</Button>} />
    <Card sx={{ mb: 2 }}><CardContent><Grid container spacing={1.5}><Grid item xs={12} md={5}><TextField fullWidth size="small" label="Search message, trace ID, or event ID" value={search} onChange={(e) => setSearch(e.target.value)} /></Grid><Grid item xs={12} sm={6} md={3}><FormControl fullWidth size="small"><InputLabel>Severity</InputLabel><Select label="Severity" value={level} onChange={(e) => setLevel(e.target.value)}>{['all','INFO','WARNING','ERROR','CRITICAL'].map((v) => <MenuItem key={v} value={v}>{v === 'all' ? 'All severities' : v}</MenuItem>)}</Select></FormControl></Grid><Grid item xs={12} sm={6} md={4}><FormControl fullWidth size="small"><InputLabel>Service</InputLabel><Select label="Service" value={service} onChange={(e) => setService(e.target.value)}><MenuItem value="">All services</MenuItem>{services.map((v) => <MenuItem key={v} value={v}>{v}</MenuItem>)}</Select></FormControl></Grid></Grid></CardContent></Card>
    {error && <Box sx={{ mb: 2 }}><ErrorState message={error} onRetry={() => void load()} /></Box>}
    <Card><CardContent sx={{ p: 0 }}><TableContainer><Table size="small"><TableHead><TableRow>{['Timestamp','Severity','Service','Message','Trace ID'].map((h) => <TableCell key={h}>{h}</TableCell>)}</TableRow></TableHead><TableBody>{loading ? <TableRow><TableCell colSpan={5}><LoadingState /></TableCell></TableRow> : logs.map((l) => <TableRow hover key={l.event_id}><TableCell sx={{ whiteSpace: 'nowrap' }}>{formatDate(l.timestamp)}</TableCell><TableCell><StatusPill value={l.level} /></TableCell><TableCell>{l.service_name || '—'}</TableCell><TableCell sx={{ minWidth: 230, maxWidth: 460, overflowWrap: 'anywhere' }}>{l.message || '—'}</TableCell><TableCell>{l.trace_id ? <Button size="small" onClick={() => onOpenTrace(l.trace_id!)}>{l.trace_id}</Button> : '—'}</TableCell></TableRow>)}</TableBody></Table></TableContainer>{!loading && !logs.length && <EmptyState title="No matching logs" detail="Adjust the severity or search text and try again." />}</CardContent></Card>
  </Box>
}

function MetricsPage() {
  const [metrics, setMetrics] = useState<MetricRecord[]>([]); const [summary, setSummary] = useState<Record<string, unknown>>({}); const [servicesPayload, setServicesPayload] = useState<unknown>([]); const [series, setSeries] = useState<unknown>([]); const [latency, setLatency] = useState<unknown>([]); const [error, setError] = useState(''); const [loading, setLoading] = useState(true)
  const load = useCallback(async () => { setLoading(true); setError(''); const results = await Promise.allSettled([observabilityApi.metrics({ limit: 200 }), observabilityApi.metricSummary(), observabilityApi.metricServices(), observabilityApi.metricTimeseries(), observabilityApi.metricLatency()]); const failed = results.filter((r) => r.status === 'rejected'); const val = (i: number) => results[i].status === 'fulfilled' ? results[i].value : undefined; setMetrics(asArray<MetricRecord>(val(0))); setSummary(asRecord(val(1))); setServicesPayload(val(2) ?? []); setSeries(val(3) ?? []); setLatency(val(4) ?? []); if (failed.length === results.length) setError(displayError((results[0] as PromiseRejectedResult).reason)); else if (failed.length) setError('Some metric endpoints are unavailable. Showing data from the endpoints that responded.'); setLoading(false) }, [])
  useEffect(() => { void load() }, [load])
  const serviceNames = useMemo(() => { const val = servicesPayload; if (Array.isArray(val)) return val.map((v) => typeof v === 'string' ? v : String(asRecord(v).service_name || asRecord(v).name || 'Unknown')); return asArray<Record<string, unknown>>(val).map((v) => String(v.service_name || v.name || 'Unknown')) }, [servicesPayload])
  const summaryEntries = Object.entries(summary).filter(([, v]) => ['string','number','boolean'].includes(typeof v))
  const seriesRows = asArray<Record<string, unknown>>(series); const latencyRows = asArray<Record<string, unknown>>(latency)
  return <Box><SectionHeading title="Metrics" subtitle="Inspect metric samples, service coverage and backend-provided summaries." action={<Button variant="outlined" startIcon={<RefreshCw size={15} />} onClick={() => void load()}>Refresh</Button>} />
    {error && <Alert severity="warning" sx={{ mb: 2 }}>{error}</Alert>}
    {loading && !metrics.length ? <LoadingState /> : <>
      <Grid container spacing={2} sx={{ mb: 2 }}>{(summaryEntries.length ? summaryEntries.slice(0, 4) : [['Metric samples', metrics.length], ['Services reporting metrics', serviceNames.length]] as [string, unknown][]).map(([label, value]) => <Grid item xs={12} sm={6} md={3} key={label}><Card><CardContent><Typography variant="body2" color="text.secondary">{label.replaceAll('_',' ')}</Typography><Typography variant="h5" sx={{ mt: 1 }}>{typeof value === 'number' ? formatNumber(value, 3) : String(value)}</Typography></CardContent></Card></Grid>)}</Grid>
      <Grid container spacing={2}><Grid item xs={12} md={5}><Card><CardContent><Typography variant="h6">Services reporting metrics</Typography><Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Returned by /api/v1/metrics/services</Typography>{serviceNames.length ? <Stack direction="row" flexWrap="wrap" gap={1}>{serviceNames.map((s) => <Chip key={s} label={s} variant="outlined" />)}</Stack> : <EmptyState title="No service list returned" />}</CardContent></Card></Grid><Grid item xs={12} md={7}><Card><CardContent><Typography variant="h6">Latency endpoint response</Typography><Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Raw structured response from the backend latency API</Typography><pre className="json-view">{JSON.stringify(latency, null, 2)}</pre></CardContent></Card></Grid>
      <Grid item xs={12}><Card><CardContent><Typography variant="h6">Time-series endpoint response</Typography><Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Raw structured response from the backend time-series API</Typography>{seriesRows.length ? <pre className="json-view">{JSON.stringify(seriesRows, null, 2)}</pre> : <pre className="json-view">{JSON.stringify(series, null, 2)}</pre>}</CardContent></Card></Grid>
      <Grid item xs={12}><Card><CardContent><Typography variant="h6">Recent metric samples</Typography><TableContainer><Table size="small"><TableHead><TableRow>{['Timestamp','Service','Metric','Value','Unit','Trace ID'].map((v) => <TableCell key={v}>{v}</TableCell>)}</TableRow></TableHead><TableBody>{metrics.slice(0, 100).map((m) => <TableRow key={m.event_id}><TableCell>{formatDate(String(m.event_timestamp || m.timestamp || ''))}</TableCell><TableCell>{m.service_name || '—'}</TableCell><TableCell>{m.metric_name || '—'}</TableCell><TableCell>{formatNumber(m.value, 4)}</TableCell><TableCell>{m.unit || '—'}</TableCell><TableCell className="mono">{m.trace_id || '—'}</TableCell></TableRow>)}</TableBody></Table></TableContainer>{!metrics.length && <EmptyState title="No metric samples" detail="No records were returned by the metrics API." />}</CardContent></Card></Grid></Grid>
    </>}
  </Box>
}

function DependenciesPage() {
  const [data, setData] = useState<{ services?: string[]; dependencies?: Dependency[] }>({}); const [selected, setSelected] = useState(''); const [detail, setDetail] = useState<{ service_name: string; incoming: Dependency[]; outgoing: Dependency[] } | null>(null); const [error, setError] = useState(''); const [loading, setLoading] = useState(true)
  const load = useCallback(async () => { setLoading(true); setError(''); try { const result = await observabilityApi.dependencies(); setData(result); if (selected) setDetail(await observabilityApi.serviceDependencies(selected)); else setDetail(null) } catch (e) { setError(displayError(e)) } finally { setLoading(false) } }, [selected])
  useEffect(() => { void load() }, [load])
  const choose = async (service: string) => { setSelected(service); setError(''); try { setDetail(await observabilityApi.serviceDependencies(service)) } catch (e) { setDetail(null); setError(displayError(e)) } }
  const edges = data.dependencies || []
  return <Box><SectionHeading title="Service dependencies" subtitle="Caller-to-callee edges inferred from parent and child spans stored by the trace processor." action={<Button variant="outlined" startIcon={<RefreshCw size={15} />} onClick={() => void load()}>Refresh</Button>} />
    {error && <Box sx={{ mb: 2 }}><ErrorState message={error} onRetry={() => void load()} /></Box>}
    {loading ? <LoadingState /> : <>
      <Card sx={{ mb: 2 }}><CardContent><Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 2 }}><Box><Typography variant="h6">Observed topology</Typography><Typography variant="body2" color="text.secondary">Select a service to inspect incoming and outgoing calls.</Typography></Box><Chip label={`${edges.length} observed edges`} /></Stack>
        {(data.services || []).length ? <Grid container spacing={1.5}>{(data.services || []).map((service) => { const outgoing = edges.filter((e) => e.source === service); const incoming = edges.filter((e) => e.target === service); return <Grid item xs={12} sm={6} lg={4} key={service}><Box component="button" className={`service-node ${selected === service ? 'selected' : ''}`} onClick={() => void choose(service)}><Stack direction="row" alignItems="center" gap={1.2}><Box className="node-icon"><Boxes size={18} /></Box><Box sx={{ textAlign: 'left', flex: 1 }}><Typography fontWeight={750}>{service}</Typography><Typography variant="caption" color="text.secondary">{incoming.length} incoming · {outgoing.length} outgoing</Typography></Box><ChevronRight size={16} /></Stack><Stack direction="row" gap={2} sx={{ mt: 1.5 }}><Box><Typography variant="caption" color="text.secondary">Calls out</Typography><Typography fontWeight={750}>{outgoing.reduce((n,e) => n + e.call_count,0)}</Typography></Box><Box><Typography variant="caption" color="text.secondary">Errors out</Typography><Typography fontWeight={750} color={outgoing.some((e) => e.error_count) ? 'error.main' : 'text.primary'}>{outgoing.reduce((n,e) => n + e.error_count,0)}</Typography></Box></Stack></Box></Grid> })}</Grid> : <EmptyState title="No dependency evidence yet" detail="The backend derives edges from spans with parent-child relationships. Generate traces across services, then refresh." />}
      </CardContent></Card>
      {edges.length > 0 && <Card sx={{ mb: 2 }}><CardContent><Typography variant="h6" sx={{ mb: 1.5 }}>Observed communication paths</Typography><TableContainer><Table size="small"><TableHead><TableRow>{['Source service','Target service','Calls','Errors','Error rate','Average duration'].map((v) => <TableCell key={v}>{v}</TableCell>)}</TableRow></TableHead><TableBody>{edges.map((e) => <TableRow key={`${e.source}-${e.target}`} hover><TableCell>{e.source}</TableCell><TableCell><Stack direction="row" alignItems="center" gap={.7}>{e.target}<ChevronRight size={14} color="#98a2b3" /></Stack></TableCell><TableCell>{formatNumber(e.call_count,0)}</TableCell><TableCell>{formatNumber(e.error_count,0)}</TableCell><TableCell>{typeof e.error_rate === 'number' ? `${(e.error_rate * 100).toFixed(1)}%` : '—'}</TableCell><TableCell>{formatDuration(e.average_duration_ms)}</TableCell></TableRow>)}</TableBody></Table></TableContainer></CardContent></Card>}
      {detail && <Card><CardContent><Typography variant="h6" sx={{ mb: 2 }}>{detail.service_name} dependencies</Typography><Grid container spacing={2}><Grid item xs={12} md={6}><Typography fontWeight={700} sx={{ mb: 1 }}>Incoming</Typography>{detail.incoming.length ? detail.incoming.map((e) => <Box key={`${e.source}-${e.target}`} className="dependency-row"><Typography>{e.source} <ChevronRight size={14} /> {e.target}</Typography><Typography variant="caption" color="text.secondary">{e.call_count} calls · {formatDuration(e.average_duration_ms)}</Typography></Box>) : <Typography variant="body2" color="text.secondary">No incoming edges returned.</Typography>}</Grid><Grid item xs={12} md={6}><Typography fontWeight={700} sx={{ mb: 1 }}>Outgoing</Typography>{detail.outgoing.length ? detail.outgoing.map((e) => <Box key={`${e.source}-${e.target}`} className="dependency-row"><Typography>{e.source} <ChevronRight size={14} /> {e.target}</Typography><Typography variant="caption" color="text.secondary">{e.call_count} calls · {formatDuration(e.average_duration_ms)}</Typography></Box>) : <Typography variant="body2" color="text.secondary">No outgoing edges returned.</Typography>}</Grid></Grid></CardContent></Card>}
    </>}
  </Box>
}

function DiagnosticsPage({ onOpenTrace }: { onOpenTrace: (id: string) => void }) {
  const [reports, setReports] = useState<DiagnosticReport[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [traceId, setTraceId] = useState(''); const [busy, setBusy] = useState(false); const [selected, setSelected] = useState<DiagnosticReport | null>(null)
  const load = useCallback(async () => { setLoading(true); setError(''); try { const result = await observabilityApi.diagnostics({ limit: 100 }); setReports(asArray<DiagnosticReport>(result)) } catch (e) { setError(displayError(e)); setReports([]) } finally { setLoading(false) } }, [])
  useEffect(() => { void load() }, [load])
  const analyze = async () => { if (!traceId.trim()) return; setBusy(true); setError(''); try { const report = await observabilityApi.analyzeTrace(traceId.trim()); setSelected(report); await load() } catch (e) { setError(displayError(e)) } finally { setBusy(false) } }
  return <Box><SectionHeading title="Root-cause diagnostics" subtitle="Review backend-generated reports and run deterministic analysis for a trace." action={<Button variant="outlined" startIcon={<RefreshCw size={15} />} onClick={() => void load()}>Refresh</Button>} />
    <Card sx={{ mb: 2 }}><CardContent><Typography variant="h6" sx={{ mb: .5 }}>Analyze a trace</Typography><Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Analysis retrieves the trace, correlated logs and metric context through the backend service.</Typography><Stack direction={{ xs: 'column', sm: 'row' }} gap={1.5}><TextField fullWidth size="small" label="Trace ID" placeholder="e.g. trace-demo-001" value={traceId} onChange={(e) => setTraceId(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void analyze() }} /><Button variant="contained" disabled={!traceId.trim() || busy} onClick={() => void analyze()}>{busy ? <CircularProgress size={18} color="inherit" /> : 'Run analysis'}</Button></Stack></CardContent></Card>
    {error && <Box sx={{ mb: 2 }}><ErrorState message={error} onRetry={() => void load()} /></Box>}
    {selected && <Card sx={{ mb: 2, borderColor: '#d9d9ff' }}><CardContent><Stack direction="row" justifyContent="space-between" alignItems="flex-start" gap={1}><Box><Typography variant="h6">Latest analysis</Typography><Typography variant="body2" color="text.secondary" className="mono">{selected.trace_id}</Typography></Box><StatusPill value={selected.severity} /></Stack><Typography fontWeight={750} sx={{ mt: 2 }}>{selected.probable_cause}</Typography><Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>{selected.summary}</Typography><Button sx={{ mt: 1 }} onClick={() => onOpenTrace(selected.trace_id)}>Open trace</Button><Divider sx={{ my: 1.5 }} /><pre className="json-view">{JSON.stringify({ findings: selected.findings, evidence: selected.evidence }, null, 2)}</pre></CardContent></Card>}
    <Card><CardContent sx={{ p: 0 }}><Box sx={{ p: 2.5, pb: 1 }}><Typography variant="h6">Diagnostic reports</Typography><Typography variant="body2" color="text.secondary">Stored reports returned by the root-cause service.</Typography></Box><TableContainer><Table size="small"><TableHead><TableRow>{['Created','Trace ID','Service','Severity','Probable cause',''].map((v) => <TableCell key={v}>{v}</TableCell>)}</TableRow></TableHead><TableBody>{loading ? <TableRow><TableCell colSpan={6}><LoadingState /></TableCell></TableRow> : reports.map((r) => <TableRow key={r.id} hover><TableCell>{formatDate(r.created_at)}</TableCell><TableCell className="mono">{r.trace_id}</TableCell><TableCell>{r.root_service || '—'}</TableCell><TableCell><StatusPill value={r.severity} /></TableCell><TableCell sx={{ minWidth: 230 }}>{r.probable_cause || r.summary || '—'}</TableCell><TableCell><Button size="small" onClick={() => setSelected(r)}>Evidence</Button><Button size="small" onClick={() => onOpenTrace(r.trace_id)}>Trace</Button></TableCell></TableRow>)}</TableBody></Table></TableContainer>{!loading && !reports.length && <EmptyState title="No diagnostic reports" detail="Run an analysis for a trace to generate a report, if trace data is available." />}</CardContent></Card>
  </Box>
}

function AlertsPage() {
  const [alerts, setAlerts] = useState<AlertRecord[]>([]); const [rules, setRules] = useState<AlertRule[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [busyId, setBusyId] = useState<string | number | null>(null); const [notice, setNotice] = useState('')
  const load = useCallback(async () => { setLoading(true); setError(''); const results = await Promise.allSettled([observabilityApi.alerts({ limit: 200 }), observabilityApi.alertRules()]); const val = (i: number) => results[i].status === 'fulfilled' ? results[i].value : undefined; setAlerts(asArray<AlertRecord>(val(0))); setRules(asArray<AlertRule>(val(1))); const failed = results.filter((r) => r.status === 'rejected'); if (failed.length === 2) setError(displayError((results[0] as PromiseRejectedResult).reason)); else if (failed.length) setError('One alert endpoint is unavailable.'); setLoading(false) }, [])
  useEffect(() => { void load() }, [load])
  const updateStatus = async (alert: AlertRecord) => { const next = (alert.status || 'active').toLowerCase() === 'resolved' ? 'active' : 'resolved'; setBusyId(alert.id); setNotice(''); setError(''); try { await observabilityApi.updateAlert(alert.id, next); setNotice(`Alert ${alert.id} updated to ${next}.`); await load() } catch (e) { setError(displayError(e)) } finally { setBusyId(null) } }
  const toggleRule = async (rule: AlertRule) => { setBusyId(rule.id); setNotice(''); setError(''); try { await observabilityApi.updateRule(rule.id, { enabled: !rule.enabled }); setNotice(`Rule “${rule.name}” ${rule.enabled ? 'disabled' : 'enabled'}.`); await load() } catch (e) { setError(displayError(e)) } finally { setBusyId(null) } }
  const evaluate = async () => { setBusyId('evaluate'); setError(''); setNotice(''); try { await observabilityApi.evaluateAlerts(); setNotice('Alert evaluation request completed.'); await load() } catch (e) { setError(displayError(e)) } finally { setBusyId(null) } }
  return <Box><SectionHeading title="Alert center" subtitle="Inspect active alerts, threshold values, and configurable rules." action={<Stack direction="row" gap={1}><Button variant="outlined" onClick={() => void load()} startIcon={<RefreshCw size={15} />}>Refresh</Button><Button variant="contained" onClick={() => void evaluate()} disabled={busyId === 'evaluate'}>{busyId === 'evaluate' ? 'Evaluating…' : 'Evaluate rules'}</Button></Stack>} />
    {error && <Box sx={{ mb: 2 }}><ErrorState message={error} onRetry={() => void load()} /></Box>}{notice && <Alert severity="success" sx={{ mb: 2 }}>{notice}</Alert>}
    <Card sx={{ mb: 2 }}><CardContent sx={{ p: 0 }}><Box sx={{ p: 2.5, pb: 1 }}><Typography variant="h6">Alerts</Typography><Typography variant="body2" color="text.secondary">Status updates are sent to the backend; unsupported operations will surface as API errors.</Typography></Box><TableContainer><Table size="small"><TableHead><TableRow>{['Status','Severity','Service','Signal','Current / threshold','Occurrences','Last seen','Action'].map((v) => <TableCell key={v}>{v}</TableCell>)}</TableRow></TableHead><TableBody>{loading ? <TableRow><TableCell colSpan={8}><LoadingState /></TableCell></TableRow> : alerts.map((a) => <TableRow key={a.id} hover><TableCell><StatusPill value={a.status} /></TableCell><TableCell><StatusPill value={a.severity} /></TableCell><TableCell>{a.service_name || '—'}</TableCell><TableCell><Typography fontWeight={700} variant="body2">{a.metric_name || 'Alert'}</Typography><Typography variant="caption" color="text.secondary">{a.summary}</Typography></TableCell><TableCell>{formatNumber(a.current_value,3)} / {formatNumber(a.threshold_value,3)}</TableCell><TableCell>{formatNumber(a.occurrence_count,0)}</TableCell><TableCell>{formatDate(a.last_seen_at)}</TableCell><TableCell><Button size="small" disabled={busyId === a.id} onClick={() => void updateStatus(a)}>{(a.status || 'active').toLowerCase() === 'resolved' ? 'Reopen' : 'Resolve'}</Button></TableCell></TableRow>)}</TableBody></Table></TableContainer>{!loading && !alerts.length && <EmptyState title="No alert records" detail="The alert endpoint returned no alerts." />}</CardContent></Card>
    <Card><CardContent sx={{ p: 0 }}><Box sx={{ p: 2.5, pb: 1 }}><Typography variant="h6">Alert rules</Typography><Typography variant="body2" color="text.secondary">Toggle a rule only if the backend supports updating its enabled state.</Typography></Box><TableContainer><Table size="small"><TableHead><TableRow>{['Rule','Service','Metric','Condition','Severity','Enabled','Action'].map((v) => <TableCell key={v}>{v}</TableCell>)}</TableRow></TableHead><TableBody>{loading ? <TableRow><TableCell colSpan={7}><LoadingState /></TableCell></TableRow> : rules.map((r) => <TableRow key={r.id}><TableCell>{r.name}</TableCell><TableCell>{r.service_name || 'All services'}</TableCell><TableCell>{r.metric_name}</TableCell><TableCell>{r.operator || '>='} {r.threshold}</TableCell><TableCell><StatusPill value={r.severity} /></TableCell><TableCell><StatusPill value={r.enabled ? 'enabled' : 'disabled'} /></TableCell><TableCell><Button size="small" disabled={busyId === r.id} onClick={() => void toggleRule(r)}>{r.enabled ? 'Disable' : 'Enable'}</Button></TableCell></TableRow>)}</TableBody></Table></TableContainer>{!loading && !rules.length && <EmptyState title="No alert rules returned" detail="Alert rules can be created through the backend API; this UI lists and toggles existing rules." />}</CardContent></Card>
  </Box>
}
