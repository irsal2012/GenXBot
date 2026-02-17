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

type ChannelInboundResponse = {
  channel: 'slack' | 'telegram'
  event_type: string
  run?: RunSession | null
  command?: string | null
  outbound_text?: string | null
  outbound_delivery?: string | null
  session_key?: string | null
}

type ChannelSessionSnapshot = {
  session_key: string
  latest_run_id?: string | null
  run_ids: string[]
}

type ChannelTrustPolicy = {
  channel: 'slack' | 'telegram'
  dm_policy: 'pairing' | 'open'
  allow_from: string[]
}

type PendingPairingCode = {
  channel: 'slack' | 'telegram'
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
}

const pct = (value: number) => `${(value * 100).toFixed(1)}%`
const sec = (value: number) => `${value.toFixed(2)}s`

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
  const [repoPath, setRepoPath] = useState('/Users/irsalimran/Desktop/GenXAI-OSS')
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
  const [channelSessions, setChannelSessions] = useState<ChannelSessionSnapshot[]>([])
  const [adminChannel, setAdminChannel] = useState<'slack' | 'telegram'>('slack')
  const [adminDmPolicy, setAdminDmPolicy] = useState<'pairing' | 'open'>('pairing')
  const [adminAllowFrom, setAdminAllowFrom] = useState('')
  const [adminApproverUsers, setAdminApproverUsers] = useState('')
  const [adminPendingCodes, setAdminPendingCodes] = useState<PendingPairingCode[]>([])
  const [adminMetrics, setAdminMetrics] = useState<ChannelMetricsSnapshot | null>(null)
  const [adminRetryQueue, setAdminRetryQueue] = useState<OutboundRetryQueueSnapshot | null>(null)

  const apiBase = useMemo(() => import.meta.env.VITE_API_BASE ?? 'http://localhost:8000', [])

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
    const res = await fetch(`${apiBase}/api/v1/runs/channels/sessions`)
    if (!res.ok) {
      throw new Error(`Failed to load channel sessions (${res.status})`)
    }
    const data = (await res.json()) as ChannelSessionSnapshot[]
    setChannelSessions(data)
  }

  const loadAdminPanelData = async () => {
    const [policyRes, pendingRes, allowlistRes, metricsRes, retryRes] = await Promise.all([
      fetch(`${apiBase}/api/v1/runs/channels/${adminChannel}/trust-policy`),
      fetch(`${apiBase}/api/v1/runs/channels/${adminChannel}/pairing/pending`),
      fetch(`${apiBase}/api/v1/runs/channels/approver-allowlist`),
      fetch(`${apiBase}/api/v1/runs/channels/metrics`),
      fetch(`${apiBase}/api/v1/runs/channels/outbound-retry`),
    ])

    if (!policyRes.ok || !pendingRes.ok || !allowlistRes.ok || !metricsRes.ok || !retryRes.ok) {
      throw new Error('Failed to load admin panel data')
    }

    const policy = (await policyRes.json()) as ChannelTrustPolicy
    const pending = (await pendingRes.json()) as PendingPairingCode[]
    const allowlist = (await allowlistRes.json()) as { users: string[] }
    const metrics = (await metricsRes.json()) as ChannelMetricsSnapshot
    const retry = (await retryRes.json()) as OutboundRetryQueueSnapshot

    setAdminDmPolicy(policy.dm_policy)
    setAdminAllowFrom(policy.allow_from.join(','))
    setAdminPendingCodes(pending)
    setAdminApproverUsers(allowlist.users.join(','))
    setAdminMetrics(metrics)
    setAdminRetryQueue(retry)
  }

  const saveTrustPolicy = async () => {
    const allowFrom = adminAllowFrom
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean)
    const res = await fetch(`${apiBase}/api/v1/runs/channels/${adminChannel}/trust-policy`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
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
      headers: { 'Content-Type': 'application/json' },
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ users }),
    })
    if (!res.ok) {
      throw new Error(`Failed to update approver allowlist (${res.status})`)
    }
    await loadAdminPanelData()
  }

  const simulateChannelMessage = async () => {
    setChannelLoading(true)
    setError('')
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
      if (data.run) {
        setRun(data.run)
        await loadAuditLog(data.run.id)
        await loadMetrics()
      }
      await loadChannelSessions()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown channel simulation error')
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

  return (
    <main className="app">
      <h1>GenXBot — Autonomous Coding Workflow</h1>
      <p className="muted">Repo ingest → plan → edit → test with approval gates.</p>

      <section className="card">
        <div className="row spread">
          <h2>Evaluation Dashboard</h2>
          <button onClick={loadMetrics} disabled={metricsLoading}>
            {metricsLoading ? 'Refreshing…' : 'Refresh Metrics'}
          </button>
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
        <h2>Start Run</h2>
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
        <h2>Connector Trigger Run</h2>
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

      <section className="card">
        <h2>Channel Console (Simulation)</h2>
        <p className="muted">Simulate inbound Slack/Telegram chat commands and inspect session mapping.</p>
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
        </label>
        <div className="row">
          <button disabled={channelLoading} onClick={simulateChannelMessage}>
            {channelLoading ? 'Sending…' : 'Send Simulated Message'}
          </button>
          <button onClick={() => void loadChannelSessions()}>Refresh Sessions</button>
        </div>

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
      </section>

      <section className="card">
        <div className="row spread">
          <h2>Channel Admin Controls</h2>
          <button onClick={() => void loadAdminPanelData()}>Refresh Admin Data</button>
        </div>
        <div className="row">
          <label>
            Channel
            <select
              value={adminChannel}
              onChange={(e) => setAdminChannel(e.target.value as 'slack' | 'telegram')}
            >
              <option value="slack">slack</option>
              <option value="telegram">telegram</option>
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
      </section>

      {run && (
        <>
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
          </section>

          <section className="card">
            <h2>Plan</h2>
            <ul>
              {run.plan_steps.map((step) => (
                <li key={step.id}>
                  {step.title} <span className="pill">{step.status}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="card">
            <h2>Pending Actions</h2>
            {run.pending_actions.length === 0 ? (
              <p>No actions.</p>
            ) : (
              run.pending_actions.map((action) => (
                <div key={action.id} className="action">
                  <p>
                    <strong>{action.action_type.toUpperCase()}</strong>: {action.description}
                  </p>
                  <p className="muted">Status: {action.status}</p>
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
                    <div className="row">
                      <button onClick={() => rerunFailedAction(action.id)}>Re-run from failed step</button>
                    </div>
                  )}
                </div>
              ))
            )}
          </section>

          <section className="card">
            <h2>Live Timeline Stream</h2>
            <div className="log-stream">
              <ul>
                {[...run.timeline].reverse().map((event, idx) => (
                  <li key={`${event.timestamp}-${idx}`}>
                    <strong>{event.agent}</strong> · {event.event} — {event.content}
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <section className="card">
            <div className="row spread">
              <h2>Audit View</h2>
              <button onClick={() => void loadAuditLog(run.id)} disabled={auditLoading}>
                {auditLoading ? 'Refreshing…' : 'Refresh Audit'}
              </button>
            </div>
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

          <section className="card">
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
        </>
      )}
    </main>
  )
}

export default App
