import { useEffect, useMemo, useState } from 'react'
import './index.css'

type PlanStep = {
  id: string
  title: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  requires_approval: boolean
}

type TimelineEvent = {
  timestamp: string
  agent: string
  event: string
  content: string
}

type Artifact = {
  id: string
  kind: 'plan' | 'diff' | 'command_output' | 'summary'
  title: string
  content: string
}

type ProposedAction = {
  id: string
  action_type: 'edit' | 'command'
  description: string
  safe: boolean
  status: 'pending' | 'approved' | 'rejected' | 'executed'
  command?: string | null
  file_path?: string | null
  patch?: string | null
}

type RunSession = {
  id: string
  goal: string
  repo_path: string
  status: 'created' | 'awaiting_approval' | 'running' | 'completed' | 'failed'
  plan_steps: PlanStep[]
  timeline: TimelineEvent[]
  artifacts: Artifact[]
  pending_actions: ProposedAction[]
  memory_summary: string
}

type LatencyMetrics = {
  samples: number
  average_seconds: number
  p50_seconds: number
  p95_seconds: number
  max_seconds: number
}

type SafetyMetrics = {
  total_actions: number
  approved_actions: number
  rejected_actions: number
  executed_actions: number
  blocked_actions: number
  command_actions: number
  safe_command_actions: number
  approval_rate: number
  rejection_rate: number
  execution_rate_of_approved: number
  safe_command_ratio: number
}

type EvaluationMetrics = {
  generated_at: string
  total_runs: number
  completed_runs: number
  failed_runs: number
  active_runs: number
  terminal_runs: number
  run_success_rate: number
  run_completion_rate: number
  latency: LatencyMetrics
  safety: SafetyMetrics
}

type UserRole = 'viewer' | 'executor' | 'approver' | 'admin'

type AuditEntry = {
  id: string
  timestamp: string
  actor: string
  actor_role: UserRole
  action: string
  detail: string
}

type AdminAuditEntry = {
  id: string
  timestamp: string
  actor: string
  actor_role: UserRole
  action: string
  origin: string
  trace_id: string
  before: Record<string, unknown>
  after: Record<string, unknown>
}

type AdminAuditSnapshot = {
  entries: number
  max_entries: number
}

type ChannelInboundResponse = {
  channel: 'slack' | 'telegram' | 'web'
  event_type: string
  run?: RunSession | null
  command?: string | null
  outbound_text?: string | null
  outbound_delivery?: string | null
  response_mode?: 'llm' | 'fallback'
  session_key?: string | null
}

type ChannelSessionSnapshot = {
  session_key: string
  latest_run_id?: string | null
  run_ids: string[]
}

type ChannelTrustPolicy = {
  channel: 'slack' | 'telegram' | 'web'
  dm_policy: 'pairing' | 'open'
  allow_from: string[]
}

type PendingPairingCode = {
  channel: 'slack' | 'telegram' | 'web'
  code: string
  user_id: string
  created_at: string
}

type ChannelMetricsSnapshot = {
  total_inbound_events: number
  total_outbound_attempts: number
  total_outbound_success: number
  total_outbound_failed: number
  total_replays_blocked: number
  command_counts: Record<string, number>
}

type OutboundRetryQueueSnapshot = {
  queued: number
  dead_lettered: number
  dead_letters?: OutboundRetryJob[]
}

type OutboundRetryJob = {
  id: string
  channel: 'slack' | 'telegram'
  channel_id: string
  text: string
  thread_id?: string | null
  attempts: number
  max_attempts: number
  last_error?: string | null
}

type ChannelMaintenanceMode = {
  channel: 'slack' | 'telegram' | 'web'
  enabled: boolean
  reason: string
}

type ChannelTrustStatus = {
  channel: 'slack' | 'telegram' | 'web'
  policy: ChannelTrustPolicy
  pending_count: number
}

type ChatMessage = {
  id: string
  role: 'user' | 'bot'
  text: string
  timestamp: string
}

const pct = (value: number) => `${(value * 100).toFixed(1)}%`
const sec = (value: number) => `${value.toFixed(2)}s`

const channels: Array<'slack' | 'telegram' | 'web'> = ['slack', 'telegram', 'web']
const statusOrder: Array<ProposedAction['status']> = ['pending', 'approved', 'executed', 'rejected']
const timelineToneOrder: Array<'all' | 'ok' | 'warn' | 'error' | 'info'> = ['all', 'ok', 'warn', 'error', 'info']

const relativeTime = (timestamp: string) => {
  const now = Date.now()
  const then = new Date(timestamp).getTime()
  const diffSeconds = Math.max(0, Math.floor((now - then) / 1000))
  if (diffSeconds < 60) return `${diffSeconds}s ago`
  const minutes = Math.floor(diffSeconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function timelineEventTone(event: TimelineEvent): 'ok' | 'warn' | 'error' | 'info' {
  const text = `${event.event} ${event.content}`.toLowerCase()
  if (text.includes('fail') || text.includes('error') || text.includes('rejected')) return 'error'
  if (text.includes('approval') || text.includes('awaiting')) return 'warn'
  if (text.includes('complete') || text.includes('executed') || text.includes('approved')) return 'ok'
  return 'info'
}

function remediationHints(action: ProposedAction): { rootCause: string; suggestions: string[] } {
  const details = `${action.description} ${action.command ?? ''}`.toLowerCase()
  if (details.includes('npm') || details.includes('pytest') || details.includes('test')) {
    return {
      rootCause: 'Likely test or dependency mismatch in the target repository.',
      suggestions: ['Review command output artifact for first failing assertion.', 'Re-run after validating local dependencies and lockfile drift.'],
    }
  }
  if (details.includes('permission') || details.includes('denied') || details.includes('auth')) {
    return {
      rootCause: 'Likely permission or credential issue.',
      suggestions: ['Validate token/credential availability in environment.', 'Check channel trust policy and approver allowlist before retrying.'],
    }
  }
  if (action.action_type === 'edit') {
    return {
      rootCause: 'Patch may not match current file context or target file path.',
      suggestions: ['Inspect diff artifact and file path for stale context.', 'Retry with refreshed repository state or narrower patch scope.'],
    }
  }
  return {
    rootCause: 'Execution context drift or transient runtime issue.',
    suggestions: ['Re-run failed step after reviewing timeline around failure event.', 'If repeated, open maintenance mode and inspect retry/dead-letter queue.'],
  }
}

function stateTone(status: ProposedAction['status']): 'warn' | 'ok' | 'error' | 'info' {
  if (status === 'pending') return 'warn'
  if (status === 'approved' || status === 'executed') return 'ok'
  if (status === 'rejected') return 'error'
  return 'info'
}

function parseDiffArtifact(content: string): { before: string; after: string } | null {
  const beforeMarker = '--- before'
  const afterMarker = '--- after'
  const beforeIdx = content.indexOf(beforeMarker)
  const afterIdx = content.indexOf(afterMarker)
  if (beforeIdx === -1 || afterIdx === -1 || afterIdx <= beforeIdx) {
    return null
  }
  const before = content.slice(beforeIdx + beforeMarker.length, afterIdx).trim()
  const after = content.slice(afterIdx + afterMarker.length).trim()
  return { before, after }
}

function App() {
  const [goal, setGoal] = useState('Add endpoint-level tests for planner API and fix lint issues')
  const [repoPath, setRepoPath] = useState('/Users/iimran/Desktop/GenXBot')
  const [run, setRun] = useState<RunSession | null>(null)
  const [metrics, setMetrics] = useState<EvaluationMetrics | null>(null)
  const [auditLog, setAuditLog] = useState<AuditEntry[]>([])
  const [error, setError] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [metricsLoading, setMetricsLoading] = useState(false)
  const [runPolling, setRunPolling] = useState(false)
  const [auditLoading, setAuditLoading] = useState(false)
  const [actor, setActor] = useState('alice')
  const [actorRole, setActorRole] = useState<UserRole>('approver')
  const [triggerConnector, setTriggerConnector] = useState<'github' | 'jira' | 'slack'>('github')
  const [triggerEventType, setTriggerEventType] = useState('pull_request.opened')
  const [triggerPayload, setTriggerPayload] = useState(
    '{"repository":{"full_name":"genexsus-ai/genxai"},"pull_request":{"title":"Investigate failing tests"}}',
  )
  const [triggerLoading, setTriggerLoading] = useState(false)
  const [channelSim, setChannelSim] = useState<'slack' | 'telegram'>('slack')
  const [channelMessage, setChannelMessage] = useState('/run scaffold API smoke tests')
  const [channelThreadId, setChannelThreadId] = useState('')
  const [channelSimUserId, setChannelSimUserId] = useState('U-SIM-1')
  const [channelSimId, setChannelSimId] = useState('C-SIM-1')
  const [channelLoading, setChannelLoading] = useState(false)
  const [channelResponse, setChannelResponse] = useState<ChannelInboundResponse | null>(null)
  const [channelError, setChannelError] = useState('')
  const [channelStatus, setChannelStatus] = useState('')
  const [channelSessionsError, setChannelSessionsError] = useState('')
  const [channelSessionsStatus, setChannelSessionsStatus] = useState('')
  const [channelSessions, setChannelSessions] = useState<ChannelSessionSnapshot[]>([])
  const [adminChannel, setAdminChannel] = useState<'slack' | 'telegram' | 'web'>('slack')
  const [adminDmPolicy, setAdminDmPolicy] = useState<'pairing' | 'open'>('pairing')
  const [adminAllowFrom, setAdminAllowFrom] = useState('')
  const [adminApproverUsers, setAdminApproverUsers] = useState('')
  const [adminPendingCodes, setAdminPendingCodes] = useState<PendingPairingCode[]>([])
  const [adminMetrics, setAdminMetrics] = useState<ChannelMetricsSnapshot | null>(null)
  const [adminRetryQueue, setAdminRetryQueue] = useState<OutboundRetryQueueSnapshot | null>(null)
  const [adminDeadLetters, setAdminDeadLetters] = useState<OutboundRetryJob[]>([])
  const [adminAuditEntries, setAdminAuditEntries] = useState<AdminAuditEntry[]>([])
  const [adminAuditStats, setAdminAuditStats] = useState<AdminAuditSnapshot | null>(null)
  const [maintenanceModes, setMaintenanceModes] = useState<Record<string, ChannelMaintenanceMode>>({})
  const [maintenanceEnabledInput, setMaintenanceEnabledInput] = useState(false)
  const [maintenanceReasonInput, setMaintenanceReasonInput] = useState('')
  const [channelTrustStatuses, setChannelTrustStatuses] = useState<ChannelTrustStatus[]>([])
  const [operatorLoading, setOperatorLoading] = useState(false)
  const [operatorError, setOperatorError] = useState('')
  const [activeView, setActiveView] = useState<'overview' | 'chat' | 'runs'>('overview')
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [chatError, setChatError] = useState('')
  const [chatSessionKey, setChatSessionKey] = useState<string | null>(null)
  const [runsList, setRunsList] = useState<RunSession[]>([])
  const [runsLoading, setRunsLoading] = useState(false)
  const [runsError, setRunsError] = useState('')
  const [timelineToneFilter, setTimelineToneFilter] = useState<'all' | 'ok' | 'warn' | 'error' | 'info'>('all')
  const [timelineAgentFilter, setTimelineAgentFilter] = useState('all')
  const [timelineQuery, setTimelineQuery] = useState('')
  const [timelineSort, setTimelineSort] = useState<'newest' | 'oldest'>('newest')
  const [chatUserId] = useState(() => {
    const stored = window.localStorage.getItem('genxbot_user_id')
    if (stored) return stored
    const generated =
      globalThis.crypto?.randomUUID?.() ?? `web-${Date.now()}-${Math.floor(Math.random() * 10000)}`
    window.localStorage.setItem('genxbot_user_id', generated)
    return generated
  })

  const apiBase = useMemo(() => import.meta.env.VITE_API_BASE ?? 'http://localhost:8000', [])
  const adminHeaders = useMemo(
    () => ({
      'x-admin-actor': actor,
      'x-admin-role': actorRole,
    }),
    [actor, actorRole],
  )

  const actionStatusCounts = useMemo(() => {
    const counts: Record<ProposedAction['status'], number> = {
      pending: 0,
      approved: 0,
      executed: 0,
      rejected: 0,
    }
    if (!run) return counts
    for (const action of run.pending_actions) counts[action.status] += 1
    return counts
  }, [run])

  const remediationCandidates = useMemo(
    () => (run ? run.pending_actions.filter((action) => action.status === 'rejected') : []),
    [run],
  )

  const timelineAgents = useMemo(() => {
    if (!run) return []
    return [...new Set(run.timeline.map((event) => event.agent))]
  }, [run])

  const timelineCounts = useMemo(() => {
    const counts: Record<'ok' | 'warn' | 'error' | 'info', number> = {
      ok: 0,
      warn: 0,
      error: 0,
      info: 0,
    }
    if (!run) return counts
    for (const event of run.timeline) {
      counts[timelineEventTone(event)] += 1
    }
    return counts
  }, [run])

  const filteredTimeline = useMemo(() => {
    if (!run) return []
    let events = [...run.timeline]
    if (timelineToneFilter !== 'all') {
      events = events.filter((event) => timelineEventTone(event) === timelineToneFilter)
    }
    if (timelineAgentFilter !== 'all') {
      events = events.filter((event) => event.agent === timelineAgentFilter)
    }
    if (timelineQuery.trim()) {
      const query = timelineQuery.trim().toLowerCase()
      events = events.filter((event) => `${event.event} ${event.content}`.toLowerCase().includes(query))
    }
    events.sort((a, b) => {
      const diff = new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
      return timelineSort === 'oldest' ? diff : -diff
    })
    return events
  }, [run, timelineAgentFilter, timelineQuery, timelineSort, timelineToneFilter])

  const maintenanceEnabledCount = useMemo(
    () => Object.values(maintenanceModes).filter((mode) => mode.enabled).length,
    [maintenanceModes],
  )

  const openTrustChannels = useMemo(
    () => channelTrustStatuses.filter((status) => status.policy.dm_policy === 'open').length,
    [channelTrustStatuses],
  )

  const appendChatMessage = (message: ChatMessage) => {
    setChatMessages((prev) => [...prev, message])
  }

  const sendChatMessage = async () => {
    const trimmed = chatInput.trim()
    if (!trimmed || chatLoading) return
    const timestamp = new Date().toISOString()
    const userMessage: ChatMessage = {
      id: `user-${timestamp}`,
      role: 'user',
      text: trimmed,
      timestamp,
    }
    appendChatMessage(userMessage)
    setChatInput('')
    setChatLoading(true)
    setChatError('')

    try {
      const res = await fetch(`${apiBase}/api/v1/runs/channels/web`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel: 'web',
          event_type: 'message',
          default_repo_path: repoPath,
          payload: {
            user_id: chatUserId,
            channel_id: 'web-dashboard',
            text: trimmed,
            thread_id: chatSessionKey ?? undefined,
          },
        }),
      })
      if (!res.ok) {
        throw new Error(`Failed to send chat (${res.status})`)
      }
      const data = (await res.json()) as ChannelInboundResponse
      if (data.session_key) {
        setChatSessionKey(data.session_key)
      }
      if (data.outbound_text) {
        appendChatMessage({
          id: `bot-${Date.now()}`,
          role: 'bot',
          text: data.outbound_text,
          timestamp: new Date().toISOString(),
        })
      }
      if (data.run) {
        setRun(data.run)
        await loadAuditLog(data.run.id)
        await loadMetrics()
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Unknown chat error'
      setChatError(message)
    } finally {
      setChatLoading(false)
    }
  }

  const loadMetrics = async () => {
    setMetricsLoading(true)
    try {
      const res = await fetch(`${apiBase}/api/v1/runs/metrics`)
      if (!res.ok) {
        throw new Error(`Failed to load metrics (${res.status})`)
      }
      const data = (await res.json()) as EvaluationMetrics
      setMetrics(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown metrics error')
    } finally {
      setMetricsLoading(false)
    }
  }

  useEffect(() => {
    loadMetrics()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase])

  const loadRunsList = async () => {
    setRunsLoading(true)
    setRunsError('')
    try {
      const res = await fetch(`${apiBase}/api/v1/runs`)
      if (!res.ok) {
        throw new Error(`Failed to load runs (${res.status})`)
      }
      const data = (await res.json()) as RunSession[]
      setRunsList(data)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Unknown runs error'
      setRunsError(message)
    } finally {
      setRunsLoading(false)
    }
  }

  const createRun = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${apiBase}/api/v1/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal, repo_path: repoPath, requested_by: actor }),
      })
      if (!res.ok) {
        throw new Error(`Failed to create run (${res.status})`)
      }
      const data = (await res.json()) as RunSession
      setRun(data)
      await loadMetrics()
      await loadAuditLog(data.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  const decide = async (actionId: string, approve: boolean) => {
    if (!run) return
    const res = await fetch(`${apiBase}/api/v1/runs/${run.id}/approval`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action_id: actionId, approve, actor, actor_role: actorRole }),
    })
    if (!res.ok) {
      setError(`Failed to decide action (${res.status})`)
      return
    }
    const updated = (await res.json()) as RunSession
    setRun(updated)
    await loadMetrics()
    await loadAuditLog(updated.id)
  }

  const approveAllPending = async () => {
    if (!run) return
    const pending = run.pending_actions.filter((action) => action.status === 'pending')
    if (pending.length === 0) return
    setLoading(true)
    setError('')
    try {
      let updated: RunSession | null = run
      for (const action of pending) {
        const res = await fetch(`${apiBase}/api/v1/runs/${run.id}/approval`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action_id: action.id, approve: true, actor, actor_role: actorRole }),
        })
        if (!res.ok) {
          throw new Error(`Failed to approve action ${action.id} (${res.status})`)
        }
        updated = (await res.json()) as RunSession
        setRun(updated)
      }
      if (updated) {
        await loadMetrics()
        await loadAuditLog(updated.id)
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Unknown approval error'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  const loadAuditLog = async (runId: string) => {
    setAuditLoading(true)
    try {
      const res = await fetch(`${apiBase}/api/v1/runs/${runId}/audit`)
      if (!res.ok) {
        throw new Error(`Failed to load audit log (${res.status})`)
      }
      const data = (await res.json()) as AuditEntry[]
      setAuditLog(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown audit error')
    } finally {
      setAuditLoading(false)
    }
  }

  const refreshRun = async (runId: string) => {
    const res = await fetch(`${apiBase}/api/v1/runs/${runId}`)
    if (!res.ok) {
      return
    }
    const data = (await res.json()) as RunSession
    setRun(data)
    await loadAuditLog(runId)
  }

  const rerunFailedAction = async (actionId: string) => {
    if (!run) return
    const res = await fetch(`${apiBase}/api/v1/runs/${run.id}/rerun-failed-step`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action_id: actionId,
        comment: 'Re-run requested from UI',
        actor,
        actor_role: actorRole,
      }),
    })
    if (!res.ok) {
      setError(`Failed to re-run failed step (${res.status})`)
      return
    }
    const updated = (await res.json()) as RunSession
    setRun(updated)
    await loadMetrics()
    await loadAuditLog(updated.id)
  }

  const rerunAllRejectedActions = async () => {
    if (!run) return
    const rejected = run.pending_actions.filter((action) => action.status === 'rejected')
    if (rejected.length === 0) return
    setLoading(true)
    setError('')
    try {
      for (const action of rejected) {
        const res = await fetch(`${apiBase}/api/v1/runs/${run.id}/rerun-failed-step`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action_id: action.id,
            comment: 'Bulk re-run requested from remediation center',
            actor,
            actor_role: actorRole,
          }),
        })
        if (!res.ok) {
          throw new Error(`Failed to re-run failed step ${action.id} (${res.status})`)
        }
        const updated = (await res.json()) as RunSession
        setRun(updated)
      }
      await loadMetrics()
      await loadAuditLog(run.id)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Unknown bulk retry error'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  const triggerConnectorRun = async () => {
    setTriggerLoading(true)
    setError('')
    try {
      const payload = JSON.parse(triggerPayload)
      const res = await fetch(`${apiBase}/api/v1/runs/triggers/${triggerConnector}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          connector: triggerConnector,
          event_type: triggerEventType,
          payload,
          default_repo_path: repoPath,
        }),
      })
      if (!res.ok) {
        throw new Error(`Failed to trigger connector run (${res.status})`)
      }
      const data = (await res.json()) as { run: RunSession }
      setRun(data.run)
      await loadMetrics()
      await loadAuditLog(data.run.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown trigger error')
    } finally {
      setTriggerLoading(false)
    }
  }

  const loadChannelSessions = async () => {
    setChannelSessionsError('')
    setChannelSessionsStatus('')
    const res = await fetch(`${apiBase}/api/v1/runs/channels/sessions`)
    if (!res.ok) {
      throw new Error(`Failed to load channel sessions (${res.status})`)
    }
    const data = (await res.json()) as ChannelSessionSnapshot[]
    setChannelSessions(data)
    setChannelSessionsStatus('Sessions refreshed.')
  }

  const loadAdminPanelData = async () => {
    setOperatorLoading(true)
    setOperatorError('')
    try {
      const [policyRes, pendingRes, allowlistRes, metricsRes, retryRes, deadRes, auditRes, auditStatsRes] =
        await Promise.all([
          fetch(`${apiBase}/api/v1/runs/channels/${adminChannel}/trust-policy`, { headers: adminHeaders }),
          fetch(`${apiBase}/api/v1/runs/channels/${adminChannel}/pairing/pending`, { headers: adminHeaders }),
          fetch(`${apiBase}/api/v1/runs/channels/approver-allowlist`, { headers: adminHeaders }),
          fetch(`${apiBase}/api/v1/runs/channels/metrics`),
          fetch(`${apiBase}/api/v1/runs/channels/outbound-retry`),
          fetch(`${apiBase}/api/v1/runs/channels/outbound-retry/deadletters`),
          fetch(`${apiBase}/api/v1/runs/channels/admin-audit`, { headers: adminHeaders }),
          fetch(`${apiBase}/api/v1/runs/channels/admin-audit/stats`, { headers: adminHeaders }),
        ])

      if (
        !policyRes.ok ||
        !pendingRes.ok ||
        !allowlistRes.ok ||
        !metricsRes.ok ||
        !retryRes.ok ||
        !deadRes.ok ||
        !auditRes.ok ||
        !auditStatsRes.ok
      ) {
        throw new Error('Failed to load operator dashboard data')
      }

      const policy = (await policyRes.json()) as ChannelTrustPolicy
      const pending = (await pendingRes.json()) as PendingPairingCode[]
      const allowlist = (await allowlistRes.json()) as { users: string[] }
      const metrics = (await metricsRes.json()) as ChannelMetricsSnapshot
      const retry = (await retryRes.json()) as OutboundRetryQueueSnapshot
      const deadLetters = (await deadRes.json()) as OutboundRetryJob[]
      const adminAudit = (await auditRes.json()) as AdminAuditEntry[]
      const auditStats = (await auditStatsRes.json()) as AdminAuditSnapshot

      const trustStatuses = await Promise.all(
        channels.map(async (channel) => {
          const [policyResByChannel, pendingResByChannel] = await Promise.all([
            fetch(`${apiBase}/api/v1/runs/channels/${channel}/trust-policy`, { headers: adminHeaders }),
            fetch(`${apiBase}/api/v1/runs/channels/${channel}/pairing/pending`, { headers: adminHeaders }),
          ])
          if (!policyResByChannel.ok || !pendingResByChannel.ok) {
            throw new Error(`Failed to load trust status for ${channel}`)
          }
          const policyByChannel = (await policyResByChannel.json()) as ChannelTrustPolicy
          const pendingByChannel = (await pendingResByChannel.json()) as PendingPairingCode[]
          return {
            channel,
            policy: policyByChannel,
            pending_count: pendingByChannel.length,
          } as ChannelTrustStatus
        }),
      )

      const maintenanceEntries = await Promise.all(
        channels.map(async (channel) => {
          const res = await fetch(`${apiBase}/api/v1/runs/channels/${channel}/maintenance`, {
            headers: adminHeaders,
          })
          if (!res.ok) {
            throw new Error(`Failed to load maintenance mode for ${channel}`)
          }
          return (await res.json()) as ChannelMaintenanceMode
        }),
      )

      const maintenanceMap = maintenanceEntries.reduce<Record<string, ChannelMaintenanceMode>>((acc, mode) => {
        acc[mode.channel] = mode
        return acc
      }, {})

      setAdminDmPolicy(policy.dm_policy)
      setAdminAllowFrom(policy.allow_from.join(','))
      setAdminPendingCodes(pending)
      setAdminApproverUsers(allowlist.users.join(','))
      setAdminMetrics(metrics)
      setAdminRetryQueue(retry)
      setAdminDeadLetters(deadLetters)
      setAdminAuditEntries(adminAudit)
      setAdminAuditStats(auditStats)
      setChannelTrustStatuses(trustStatuses)
      setMaintenanceModes(maintenanceMap)
      const selected = maintenanceMap[adminChannel]
      if (selected) {
        setMaintenanceEnabledInput(selected.enabled)
        setMaintenanceReasonInput(selected.reason)
      }
    } catch (e) {
      setOperatorError(e instanceof Error ? e.message : 'Unknown operator dashboard error')
    } finally {
      setOperatorLoading(false)
    }
  }

  const saveTrustPolicy = async () => {
    const allowFrom = adminAllowFrom
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean)
    const res = await fetch(`${apiBase}/api/v1/runs/channels/${adminChannel}/trust-policy`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...adminHeaders },
      body: JSON.stringify({ dm_policy: adminDmPolicy, allow_from: allowFrom }),
    })
    if (!res.ok) {
      throw new Error(`Failed to save trust policy (${res.status})`)
    }
    await loadAdminPanelData()
  }

  const approvePairingCode = async (code: string) => {
    const res = await fetch(`${apiBase}/api/v1/runs/channels/${adminChannel}/pairing/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...adminHeaders },
      body: JSON.stringify({ code, actor }),
    })
    if (!res.ok) {
      throw new Error(`Failed to approve pairing code (${res.status})`)
    }
    await loadAdminPanelData()
  }

  const saveApproverAllowlist = async () => {
    const users = adminApproverUsers
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean)
    const res = await fetch(`${apiBase}/api/v1/runs/channels/approver-allowlist`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...adminHeaders },
      body: JSON.stringify({ users }),
    })
    if (!res.ok) {
      throw new Error(`Failed to update approver allowlist (${res.status})`)
    }
    await loadAdminPanelData()
  }

  const updateMaintenanceMode = async () => {
    const res = await fetch(`${apiBase}/api/v1/runs/channels/${adminChannel}/maintenance`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...adminHeaders },
      body: JSON.stringify({ enabled: maintenanceEnabledInput, reason: maintenanceReasonInput }),
    })
    if (!res.ok) {
      throw new Error(`Failed to update maintenance mode (${res.status})`)
    }
    await loadAdminPanelData()
  }

  const replayDeadLetter = async (jobId: string) => {
    const res = await fetch(`${apiBase}/api/v1/runs/channels/outbound-retry/replay/${jobId}`, {
      method: 'POST',
      headers: adminHeaders,
    })
    if (!res.ok) {
      throw new Error(`Failed to replay dead letter (${res.status})`)
    }
    await loadAdminPanelData()
  }

  const clearAdminAudit = async () => {
    const res = await fetch(`${apiBase}/api/v1/runs/channels/admin-audit/clear`, {
      method: 'POST',
      headers: adminHeaders,
    })
    if (!res.ok) {
      throw new Error(`Failed to clear admin audit (${res.status})`)
    }
    await loadAdminPanelData()
  }

  const simulateChannelMessage = async () => {
    setChannelLoading(true)
    setError('')
    setChannelError('')
    setChannelStatus('')
    setChannelResponse(null)
    try {
      const payload =
        channelSim === 'slack'
          ? {
              event: {
                type: 'message',
                user: channelSimUserId,
                channel: channelSimId,
                text: channelMessage,
                ...(channelThreadId ? { thread_ts: channelThreadId } : {}),
              },
            }
          : {
              message: {
                from: { id: channelSimUserId },
                chat: { id: channelSimId },
                text: channelMessage,
                ...(channelThreadId ? { message_thread_id: channelThreadId } : {}),
              },
            }

      const res = await fetch(`${apiBase}/api/v1/runs/channels/${channelSim}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel: channelSim,
          event_type: 'message',
          default_repo_path: repoPath,
          payload,
        }),
      })
      if (!res.ok) {
        throw new Error(`Failed to simulate channel message (${res.status})`)
      }
      const data = (await res.json()) as ChannelInboundResponse
      setChannelResponse(data)
      setChannelStatus('Message delivered. Response received from backend.')
      if (data.run) {
        setRun(data.run)
        await loadAuditLog(data.run.id)
        await loadMetrics()
      }
      await loadChannelSessions()
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Unknown channel simulation error'
      setChannelError(message)
      setChannelStatus('Message failed. See error below.')
    } finally {
      setChannelLoading(false)
    }
  }

  useEffect(() => {
    if (!run) return
    setRunPolling(true)
    const interval = setInterval(() => {
      void refreshRun(run.id)
    }, 2000)
    return () => {
      clearInterval(interval)
      setRunPolling(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id])

  useEffect(() => {
    const selected = maintenanceModes[adminChannel]
    if (!selected) return
    setMaintenanceEnabledInput(selected.enabled)
    setMaintenanceReasonInput(selected.reason)
  }, [adminChannel, maintenanceModes])

  useEffect(() => {
    void loadAdminPanelData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminChannel])

  return (
    <div className="dashboard">
      <aside className="sidebar">
        <div>
          <p className="eyebrow">OpenClaw Gateway</p>
          <h2 className="brand">GenXBot</h2>
          <p className="muted">Approval-first autonomous run control.</p>
        </div>
        <nav className="nav">
          <button
            className={`nav-item ${activeView === 'overview' ? 'active' : ''}`}
            type="button"
            onClick={() => setActiveView('overview')}
          >
            Overview
          </button>
          <button
            className={`nav-item ${activeView === 'chat' ? 'active' : ''}`}
            type="button"
            onClick={() => setActiveView('chat')}
          >
            Chat
          </button>
          <button
            className={`nav-item ${activeView === 'runs' ? 'active' : ''}`}
            type="button"
            onClick={() => {
              setActiveView('runs')
              void loadRunsList()
            }}
          >
            Runs
          </button>
          <button className="nav-item" type="button">
            Approvals
          </button>
          <button className="nav-item" type="button">
            Timeline
          </button>
          <button className="nav-item" type="button">
            Artifacts
          </button>
          <button className="nav-item" type="button">
            Advanced
          </button>
        </nav>
        <div className="sidebar-footer">
          <span className="pill">API</span>
          <span className="muted">{apiBase}</span>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div>
            <h1>GenXBot Control Center</h1>
            <p className="muted">Plan → approve → execute. Track every step of autonomous coding runs.</p>
          </div>
          <div className="topbar-actions">
            <button onClick={loadMetrics} disabled={metricsLoading}>
              {metricsLoading ? 'Refreshing…' : 'Refresh Metrics'}
            </button>
            {run && (
              <button onClick={() => void loadAuditLog(run.id)} disabled={auditLoading}>
                {auditLoading ? 'Refreshing…' : 'Refresh Audit'}
              </button>
            )}
          </div>
        </header>

        {activeView === 'chat' ? (
          <section className="card chat-panel">
            <div className="row spread">
              <div>
                <h2>GenXBot Chat</h2>
                <p className="muted">Chat directly with GenXBot. Use /run to start a new run.</p>
              </div>
              <span className="pill">Direct</span>
            </div>

            <div className="chat-stream">
              {chatMessages.length === 0 ? (
                <p className="muted">
                  No messages yet. Try: <strong>/run add login page tests</strong> or ask a question.
                </p>
              ) : (
                chatMessages.map((message) => (
                  <div key={message.id} className={`chat-bubble ${message.role}`}>
                    <div className="chat-meta">
                      <strong>{message.role === 'user' ? 'You' : 'GenXBot'}</strong>
                      <span>{new Date(message.timestamp).toLocaleTimeString()}</span>
                    </div>
                    <p>{message.text}</p>
                  </div>
                ))
              )}
            </div>

            {chatError && <p className="error">{chatError}</p>}

            <div className="chat-input">
              <input
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder="Message GenXBot (e.g., /run harden API tests)"
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    void sendChatMessage()
                  }
                }}
              />
              <button onClick={() => void sendChatMessage()} disabled={chatLoading}>
                {chatLoading ? 'Sending…' : 'Send'}
              </button>
            </div>
          </section>
        ) : activeView === 'runs' ? (
          <section className="card">
            <div className="row spread">
              <div>
                <h2>Runs</h2>
                <p className="muted">Browse recent runs and load one into the dashboard.</p>
              </div>
              <button onClick={() => void loadRunsList()} disabled={runsLoading}>
                {runsLoading ? 'Refreshing…' : 'Refresh'}
              </button>
            </div>
            {runsError && <p className="error">{runsError}</p>}
            {runsList.length === 0 ? (
              <p className="muted">No runs found yet.</p>
            ) : (
              <div className="log-stream">
                <ul>
                  {[...runsList].reverse().map((item) => (
                    <li key={item.id}>
                      <div className="row spread">
                        <div>
                          <strong>{item.id}</strong> · {item.status}
                          <div className="muted">Goal: {item.goal}</div>
                        </div>
                        <button onClick={() => setRun(item)}>Open</button>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        ) : (
          <section className="content-grid">
          <section className="card span-2">
            <div className="row spread">
              <h2>Gateway Metrics</h2>
              <span className="pill">Live</span>
            </div>

            {!metrics ? (
              <p className="muted">No metrics available yet.</p>
            ) : (
              <>
                <div className="metrics-grid">
                  <div className="metric-card">
                    <span className="metric-label">Total Runs</span>
                    <strong className="metric-value">{metrics.total_runs}</strong>
                  </div>
                  <div className="metric-card">
                    <span className="metric-label">Run Success Rate</span>
                    <strong className="metric-value">{pct(metrics.run_success_rate)}</strong>
                  </div>
                  <div className="metric-card">
                    <span className="metric-label">Run Completion Rate</span>
                    <strong className="metric-value">{pct(metrics.run_completion_rate)}</strong>
                  </div>
                  <div className="metric-card">
                    <span className="metric-label">Blocked Actions</span>
                    <strong className="metric-value">{metrics.safety.blocked_actions}</strong>
                  </div>
                </div>

                <div className="metrics-columns">
                  <div>
                    <h3>Latency</h3>
                    <ul>
                      <li>Samples: {metrics.latency.samples}</li>
                      <li>Average: {sec(metrics.latency.average_seconds)}</li>
                      <li>P50: {sec(metrics.latency.p50_seconds)}</li>
                      <li>P95: {sec(metrics.latency.p95_seconds)}</li>
                      <li>Max: {sec(metrics.latency.max_seconds)}</li>
                    </ul>
                  </div>

                  <div>
                    <h3>Safety</h3>
                    <ul>
                      <li>Total actions: {metrics.safety.total_actions}</li>
                      <li>Approved: {metrics.safety.approved_actions}</li>
                      <li>Rejected: {metrics.safety.rejected_actions}</li>
                      <li>Executed: {metrics.safety.executed_actions}</li>
                      <li>Approval rate: {pct(metrics.safety.approval_rate)}</li>
                      <li>Rejection rate: {pct(metrics.safety.rejection_rate)}</li>
                      <li>Exec rate of approved: {pct(metrics.safety.execution_rate_of_approved)}</li>
                      <li>Safe command ratio: {pct(metrics.safety.safe_command_ratio)}</li>
                    </ul>
                  </div>
                </div>
              </>
            )}
          </section>

          <section className="card">
            <h2>Start a Run</h2>
            <p className="muted">Create a gated autonomous workflow for a target repository.</p>
            <div className="row">
              <label>
                User
                <input value={actor} onChange={(e) => setActor(e.target.value)} />
              </label>
              <label>
                Role
                <select value={actorRole} onChange={(e) => setActorRole(e.target.value as UserRole)}>
                  <option value="viewer">viewer</option>
                  <option value="executor">executor</option>
                  <option value="approver">approver</option>
                  <option value="admin">admin</option>
                </select>
              </label>
            </div>
            <label>
              Goal
              <textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={3} />
            </label>
            <label>
              Repository Path
              <input value={repoPath} onChange={(e) => setRepoPath(e.target.value)} />
            </label>
            <button disabled={loading} onClick={createRun}>
              {loading ? 'Creating…' : 'Create Run'}
            </button>
            {error && <p className="error">{error}</p>}
          </section>

          <section className="card">
            <h2>Connector Trigger</h2>
            <p className="muted">Create runs from GitHub/Jira/Slack webhook-style payloads.</p>
            <div className="row">
              <label>
                Connector
                <select
                  value={triggerConnector}
                  onChange={(e) => setTriggerConnector(e.target.value as 'github' | 'jira' | 'slack')}
                >
                  <option value="github">github</option>
                  <option value="jira">jira</option>
                  <option value="slack">slack</option>
                </select>
              </label>
              <label>
                Event Type
                <input value={triggerEventType} onChange={(e) => setTriggerEventType(e.target.value)} />
              </label>
            </div>
            <label>
              Payload (JSON)
              <textarea value={triggerPayload} onChange={(e) => setTriggerPayload(e.target.value)} rows={5} />
            </label>
            <button disabled={triggerLoading} onClick={triggerConnectorRun}>
              {triggerLoading ? 'Triggering…' : 'Trigger Connector Run'}
            </button>
          </section>
          </section>
        )}

        {run && (
          <section className="content-grid">
            <section className="card">
              <h2>Run Status</h2>
              <p>
                <strong>ID:</strong> {run.id}
              </p>
              <p>
                <strong>Status:</strong> {run.status}
              </p>
              <p>
                <strong>Memory:</strong> {run.memory_summary}
              </p>
              <p>
                <strong>Active User:</strong> {actor} ({actorRole})
              </p>
              <p className="muted">Live log stream: {runPolling ? 'active (2s polling)' : 'idle'}</p>
              <p className="muted">
                Timeline footprint: {run.timeline.length} events · errors {timelineCounts.error} · warnings{' '}
                {timelineCounts.warn}
              </p>
            </section>

            <section className="card">
              <h2>Plan Steps</h2>
              <ul>
                {run.plan_steps.map((step) => (
                  <li key={step.id}>
                    {step.title} <span className="pill">{step.status}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="card span-2">
              <h2>Approval Queue</h2>
              <div className="row">
                {statusOrder.map((status) => (
                  <span key={status} className={`pill tone-${stateTone(status)}`}>
                    {status}: {actionStatusCounts[status]}
                  </span>
                ))}
              </div>
              <div className="transition-grid">
                <div className="transition-card">
                  <span className="metric-label">Pending</span>
                  <strong>{actionStatusCounts.pending}</strong>
                </div>
                <div className="transition-arrow">→</div>
                <div className="transition-card">
                  <span className="metric-label">Approved</span>
                  <strong>{actionStatusCounts.approved}</strong>
                </div>
                <div className="transition-arrow">→</div>
                <div className="transition-card">
                  <span className="metric-label">Executed</span>
                  <strong>{actionStatusCounts.executed}</strong>
                </div>
                <div className="transition-arrow">↘</div>
                <div className="transition-card tone-error-card">
                  <span className="metric-label">Rejected</span>
                  <strong>{actionStatusCounts.rejected}</strong>
                </div>
              </div>
              {run.pending_actions.length === 0 ? (
                <p className="muted">No actions awaiting approval.</p>
              ) : (
                <>
                  <div className="row" style={{ marginBottom: '1rem' }}>
                    <button onClick={approveAllPending} disabled={loading}>
                      {loading ? 'Approving…' : 'Approve All Pending'}
                    </button>
                  </div>
                  {run.pending_actions.map((action) => (
                    <div key={action.id} className="action">
                      {(() => {
                        const remediation = remediationHints(action)
                        return (
                          <>
                      <p>
                        <strong>{action.action_type.toUpperCase()}</strong>: {action.description}
                      </p>
                      <p className="muted">
                        Status: <span className={`pill tone-${stateTone(action.status)}`}>{action.status}</span>
                      </p>
                      {action.command && <code>{action.command}</code>}
                      {action.file_path && <code>{action.file_path}</code>}
                      {action.status === 'pending' && (
                        <div className="row">
                          <button onClick={() => decide(action.id, true)}>Approve</button>
                          <button className="danger" onClick={() => decide(action.id, false)}>
                            Reject
                          </button>
                        </div>
                      )}
                      {action.status === 'rejected' && (
                        <div className="remediation-box">
                          <p>
                            <strong>Root-cause hint:</strong> {remediation.rootCause}
                          </p>
                          <ul>
                            {remediation.suggestions.map((hint) => (
                              <li key={hint}>{hint}</li>
                            ))}
                          </ul>
                          <div className="row">
                            <button onClick={() => rerunFailedAction(action.id)}>Re-run from failed step</button>
                          </div>
                        </div>
                      )}
                          </>
                        )
                      })()}
                    </div>
                  ))}
                </>
              )}
              {remediationCandidates.length > 0 && (
                <p className="muted">{remediationCandidates.length} failed action(s) with remediation guidance.</p>
              )}
            </section>

            <section className="card span-2">
              <h2>Timeline</h2>
              <div className="timeline-toolbar">
                <label>
                  Tone
                  <select
                    value={timelineToneFilter}
                    onChange={(e) =>
                      setTimelineToneFilter(e.target.value as 'all' | 'ok' | 'warn' | 'error' | 'info')
                    }
                  >
                    {timelineToneOrder.map((tone) => (
                      <option key={tone} value={tone}>
                        {tone}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Agent
                  <select value={timelineAgentFilter} onChange={(e) => setTimelineAgentFilter(e.target.value)}>
                    <option value="all">all</option>
                    {timelineAgents.map((agentName) => (
                      <option key={agentName} value={agentName}>
                        {agentName}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Search
                  <input
                    value={timelineQuery}
                    onChange={(e) => setTimelineQuery(e.target.value)}
                    placeholder="event, failure, approval..."
                  />
                </label>
                <label>
                  Order
                  <select value={timelineSort} onChange={(e) => setTimelineSort(e.target.value as 'newest' | 'oldest')}>
                    <option value="newest">newest first</option>
                    <option value="oldest">oldest first</option>
                  </select>
                </label>
              </div>
              <div className="row">
                <span className="pill tone-info">info: {timelineCounts.info}</span>
                <span className="pill tone-ok">ok: {timelineCounts.ok}</span>
                <span className="pill tone-warn">warn: {timelineCounts.warn}</span>
                <span className="pill tone-error">error: {timelineCounts.error}</span>
              </div>
              <div className="log-stream">
                <ul>
                  {filteredTimeline.map((event, idx) => (
                    <li key={`${event.timestamp}-${idx}`} className={`timeline-item tone-${timelineEventTone(event)}`}>
                      <div className="row spread">
                        <strong>{event.agent}</strong>
                        <span className="muted">
                          {new Date(event.timestamp).toLocaleTimeString()} · {relativeTime(event.timestamp)}
                        </span>
                      </div>
                      <div>
                        <span className={`pill tone-${timelineEventTone(event)}`}>{event.event}</span> — {event.content}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </section>

            {remediationCandidates.length > 0 && (
              <section className="card span-2">
                <div className="row spread">
                  <div>
                    <h2>Failure Remediation Center</h2>
                    <p className="muted">
                      Guided recovery suggestions for rejected/failed steps with one-click re-run actions.
                    </p>
                  </div>
                  <button onClick={() => void rerunAllRejectedActions()} disabled={loading}>
                    {loading ? 'Retrying…' : 'Retry All Rejected'}
                  </button>
                </div>
                <div className="operator-grid">
                  {remediationCandidates.map((action) => {
                    const remediation = remediationHints(action)
                    return (
                      <div key={action.id} className="metric-card remediation-card">
                        <span className="metric-label">{action.action_type}</span>
                        <strong>{action.description}</strong>
                        <span className="muted">{remediation.rootCause}</span>
                        <ul>
                          {remediation.suggestions.map((hint) => (
                            <li key={hint}>{hint}</li>
                          ))}
                        </ul>
                        <button onClick={() => rerunFailedAction(action.id)}>Retry This Step</button>
                      </div>
                    )
                  })}
                </div>
              </section>
            )}

            <section className="card span-2">
              <h2>Audit View</h2>
              {auditLog.length === 0 ? (
                <p className="muted">No audit entries.</p>
              ) : (
                <div className="log-stream">
                  <ul>
                    {[...auditLog].reverse().map((entry) => (
                      <li key={entry.id}>
                        <strong>{entry.actor}</strong> ({entry.actor_role}) · {entry.action} — {entry.detail}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>

            <section className="card span-2">
              <h2>Artifacts</h2>
              {run.artifacts.map((artifact) => (
                <details key={artifact.id}>
                  <summary>
                    {artifact.title} <span className="pill">{artifact.kind}</span>
                  </summary>
                  {artifact.kind === 'diff' ? (
                    (() => {
                      const parsed = parseDiffArtifact(artifact.content)
                      if (!parsed) return <pre>{artifact.content}</pre>
                      return (
                        <div className="diff-grid">
                          <div>
                            <h4>Before</h4>
                            <pre>{parsed.before}</pre>
                          </div>
                          <div>
                            <h4>After</h4>
                            <pre>{parsed.after}</pre>
                          </div>
                        </div>
                      )
                    })()
                  ) : (
                    <pre>{artifact.content}</pre>
                  )}
                </details>
              ))}
            </section>
          </section>
        )}

        <section className="card advanced">
          <div className="row spread">
            <div>
              <h2>Advanced Operations</h2>
              <p className="muted">Simulation, channel policies, and admin-only observability tools.</p>
            </div>
            <button onClick={() => void loadAdminPanelData()} disabled={operatorLoading}>
              {operatorLoading ? 'Refreshing…' : 'Refresh Admin Data'}
            </button>
          </div>
          {operatorError && <p className="error">{operatorError}</p>}

          <div className="operator-grid">
            <div className="metric-card">
              <span className="metric-label">Admin audit events</span>
              <strong className="metric-value">{adminAuditStats?.entries ?? 0}</strong>
              <span className="muted">capacity: {adminAuditStats?.max_entries ?? 0}</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">Retry queue</span>
              <strong className="metric-value">{adminRetryQueue?.queued ?? 0}</strong>
              <span className="muted">dead letters: {adminRetryQueue?.dead_lettered ?? 0}</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">Maintenance mode</span>
              <strong className="metric-value">{maintenanceEnabledCount}</strong>
              <span className="muted">channels enabled</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">Channel trust posture</span>
              <strong className="metric-value">{openTrustChannels} open</strong>
              <span className="muted">{channelTrustStatuses.length - openTrustChannels} pairing-gated</span>
            </div>
          </div>

          <details>
            <summary>Channel Console (Simulation)</summary>
            <div className="detail-body">
              <p className="muted">
                Simulate inbound Slack/Telegram chat commands and inspect session mapping. Commands use
                <strong> /run</strong>, <strong>/status</strong>, <strong>/approve</strong>, and{' '}
                <strong>/reject</strong> prefixes.
              </p>
              <div className="row">
                <label>
                  Channel
                  <select
                    value={channelSim}
                    onChange={(e) => setChannelSim(e.target.value as 'slack' | 'telegram')}
                  >
                    <option value="slack">slack</option>
                    <option value="telegram">telegram</option>
                  </select>
                </label>
                <label>
                  User ID
                  <input value={channelSimUserId} onChange={(e) => setChannelSimUserId(e.target.value)} />
                </label>
                <label>
                  Channel/Chat ID
                  <input value={channelSimId} onChange={(e) => setChannelSimId(e.target.value)} />
                </label>
                <label>
                  Thread (optional)
                  <input value={channelThreadId} onChange={(e) => setChannelThreadId(e.target.value)} />
                </label>
              </div>
              <label>
                Message
                <input value={channelMessage} onChange={(e) => setChannelMessage(e.target.value)} />
                <span className="muted">Example: /run scaffold API smoke tests</span>
              </label>
              <div className="row">
                <button disabled={channelLoading} onClick={simulateChannelMessage}>
                  {channelLoading ? 'Sending…' : 'Send Simulated Message'}
                </button>
                <button
                  onClick={() =>
                    void loadChannelSessions().catch((e) => {
                      const message = e instanceof Error ? e.message : 'Unknown sessions error'
                      setChannelSessionsError(message)
                    })
                  }
                >
                  Refresh Sessions
                </button>
              </div>

              {channelStatus && <p className="muted">{channelStatus}</p>}
              {channelError && <p className="error">{channelError}</p>}
              {channelSessionsStatus && <p className="muted">{channelSessionsStatus}</p>}
              {channelSessionsError && <p className="error">{channelSessionsError}</p>}

              {channelResponse && (
                <div className="action">
                  <p>
                    <strong>Command:</strong> {channelResponse.command ?? 'n/a'}
                  </p>
                  <p>
                    <strong>Session:</strong> {channelResponse.session_key ?? 'n/a'}
                  </p>
                  <p>
                    <strong>Delivery:</strong> {channelResponse.outbound_delivery ?? 'n/a'}
                  </p>
                  <pre>{channelResponse.outbound_text ?? 'no outbound text'}</pre>
                </div>
              )}

              <div className="log-stream">
                <ul>
                  {channelSessions.map((s) => (
                    <li key={s.session_key}>
                      <strong>{s.session_key}</strong> → latest={s.latest_run_id ?? 'none'} · runs={s.run_ids.length}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </details>

          <details>
            <summary>Channel Admin Controls</summary>
            <div className="detail-body">
              <div className="operator-grid">
                {channelTrustStatuses.map((status) => (
                  <div key={status.channel} className="metric-card">
                    <span className="metric-label">{status.channel} trust</span>
                    <strong className="metric-value">{status.policy.dm_policy}</strong>
                    <span className="muted">pending pairing: {status.pending_count}</span>
                  </div>
                ))}
              </div>

              <div className="row">
                <label>
                  Channel
                  <select
                    value={adminChannel}
                    onChange={(e) => setAdminChannel(e.target.value as 'slack' | 'telegram' | 'web')}
                  >
                    <option value="slack">slack</option>
                    <option value="telegram">telegram</option>
                    <option value="web">web</option>
                  </select>
                </label>
                <label>
                  DM Policy
                  <select
                    value={adminDmPolicy}
                    onChange={(e) => setAdminDmPolicy(e.target.value as 'pairing' | 'open')}
                  >
                    <option value="pairing">pairing</option>
                    <option value="open">open</option>
                  </select>
                </label>
              </div>
              <label>
                allow_from (comma-separated)
                <input value={adminAllowFrom} onChange={(e) => setAdminAllowFrom(e.target.value)} />
              </label>
              <button onClick={() => void saveTrustPolicy()}>Save Trust Policy</button>

              <label>
                Command Approver Allowlist (comma-separated)
                <input value={adminApproverUsers} onChange={(e) => setAdminApproverUsers(e.target.value)} />
              </label>
              <button onClick={() => void saveApproverAllowlist()}>Save Approver Allowlist</button>

              <h3>Maintenance Mode</h3>
              <div className="row">
                <label>
                  Enabled
                  <select
                    value={maintenanceEnabledInput ? 'on' : 'off'}
                    onChange={(e) => setMaintenanceEnabledInput(e.target.value === 'on')}
                  >
                    <option value="off">off</option>
                    <option value="on">on</option>
                  </select>
                </label>
                <label style={{ minWidth: '320px' }}>
                  Reason
                  <input
                    value={maintenanceReasonInput}
                    onChange={(e) => setMaintenanceReasonInput(e.target.value)}
                    placeholder="Brief operator reason"
                  />
                </label>
              </div>
              <button onClick={() => void updateMaintenanceMode()}>Update Maintenance Mode</button>

              <h3>Pending Pairing Codes</h3>
              <div className="log-stream">
                <ul>
                  {adminPendingCodes.map((p) => (
                    <li key={`${p.channel}:${p.code}`}>
                      {p.user_id} · {p.code}
                      <button style={{ marginLeft: '0.5rem' }} onClick={() => void approvePairingCode(p.code)}>
                        Approve
                      </button>
                    </li>
                  ))}
                </ul>
              </div>

              <h3>Channel Observability</h3>
              {adminMetrics && (
                <ul>
                  <li>Inbound events: {adminMetrics.total_inbound_events}</li>
                  <li>Outbound attempts: {adminMetrics.total_outbound_attempts}</li>
                  <li>Outbound success: {adminMetrics.total_outbound_success}</li>
                  <li>Outbound failed: {adminMetrics.total_outbound_failed}</li>
                  <li>Replay blocked: {adminMetrics.total_replays_blocked}</li>
                </ul>
              )}
              {adminRetryQueue && (
                <ul>
                  <li>Outbound retry queued: {adminRetryQueue.queued}</li>
                  <li>Dead letters: {adminRetryQueue.dead_lettered}</li>
                </ul>
              )}

              <h3>Retry Dead-letter Queue</h3>
              {adminDeadLetters.length === 0 ? (
                <p className="muted">No dead-letter jobs.</p>
              ) : (
                <div className="log-stream">
                  <ul>
                    {adminDeadLetters.map((job) => (
                      <li key={job.id}>
                        <strong>{job.channel}</strong> · attempts {job.attempts}/{job.max_attempts}
                        <div className="muted">{job.last_error ?? 'unknown error'}</div>
                        <button onClick={() => void replayDeadLetter(job.id)}>Replay</button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <h3>Admin Audit</h3>
              {adminAuditStats && (
                <p className="muted">
                  entries: {adminAuditStats.entries}/{adminAuditStats.max_entries}
                </p>
              )}
              <button className="danger" onClick={() => void clearAdminAudit()}>
                Clear Admin Audit
              </button>
              <div className="log-stream">
                <ul>
                  {[...adminAuditEntries].reverse().slice(0, 30).map((entry) => (
                    <li key={entry.id}>
                      <strong>{entry.actor}</strong> ({entry.actor_role}) · {entry.action}
                      <div className="muted">origin={entry.origin} trace={entry.trace_id}</div>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </details>
        </section>
      </div>
    </div>
  )
}

export default App
