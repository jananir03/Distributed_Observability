import { Alert, Box, Button, Chip, CircularProgress, Stack, Typography } from '@mui/material'
import { Activity, AlertCircle, CheckCircle2, RefreshCw, WifiOff } from 'lucide-react'
import type { ReactNode } from 'react'

export function SectionHeading({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return <Stack direction={{ xs: 'column', sm: 'row' }} alignItems={{ xs: 'stretch', sm: 'center' }} justifyContent="space-between" gap={1.5} sx={{ mb: 2.5 }}>
    <Box><Typography variant="h5">{title}</Typography>{subtitle && <Typography color="text.secondary" variant="body2" sx={{ mt: .5 }}>{subtitle}</Typography>}</Box>
    {action}
  </Stack>
}

export function StatusPill({ value }: { value?: string | null }) {
  const v = (value || 'unknown').toLowerCase()
  const color = ['error', 'failed', 'failure', 'critical', 'high'].includes(v) ? 'error' :
    ['warning', 'slow', 'medium', 'pending'].includes(v) ? 'warning' :
    ['ok', 'healthy', 'success', 'resolved', 'info', 'completed'].includes(v) ? 'success' : 'default'
  return <Chip size="small" label={value || 'Unknown'} color={color} variant={color === 'default' ? 'outlined' : 'filled'} sx={{ fontWeight: 700, textTransform: 'capitalize' }} />
}

export function LoadingState({ label = 'Loading observability data…' }: { label?: string }) {
  return <Stack alignItems="center" justifyContent="center" gap={1.5} sx={{ minHeight: 190, color: 'text.secondary' }}><CircularProgress size={26} /><Typography variant="body2">{label}</Typography></Stack>
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <Alert severity="error" icon={<WifiOff size={19} />} action={onRetry ? <Button color="inherit" size="small" startIcon={<RefreshCw size={14} />} onClick={onRetry}>Retry</Button> : undefined}>{message}</Alert>
}

export function EmptyState({ title = 'No records found', detail = 'No matching data was returned by the API.' }: { title?: string; detail?: string }) {
  return <Stack alignItems="center" justifyContent="center" gap={1} sx={{ py: 6, textAlign: 'center' }}><Activity size={28} color="#98a2b3" /><Typography fontWeight={700}>{title}</Typography><Typography variant="body2" color="text.secondary">{detail}</Typography></Stack>
}

export function ConnectionBadge({ online }: { online: boolean | null }) {
  if (online === null) return <Chip size="small" label="Checking gateway" icon={<CircularProgress size={12} />} variant="outlined" />
  return <Chip size="small" label={online ? 'Gateway connected' : 'Gateway unreachable'} icon={online ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />} color={online ? 'success' : 'error'} variant="outlined" />
}

export function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export function formatDuration(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`
  return `${value.toFixed(value < 10 ? 2 : 1)} ms`
}

export function formatNumber(value: unknown, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
}
