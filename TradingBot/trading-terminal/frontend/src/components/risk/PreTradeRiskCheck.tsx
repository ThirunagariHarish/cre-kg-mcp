import React, { useState } from 'react'
import clsx from 'clsx'
import { CheckCircle, AlertTriangle, XCircle, Loader } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'
import { API } from '@/lib/api/endpoints'

// ── Inline types ──────────────────────────────────────────────────────────────

export type CheckStatus = 'PASS' | 'WARN' | 'FAIL'
export type OverallDecision = 'ALLOWED' | 'WARNING' | 'BLOCKED'

export interface IndividualCheck {
  name: string
  status: CheckStatus
  current: string
  limit: string
  reason?: string
}

export interface PreTradeCheckResult {
  decision: OverallDecision
  checks: IndividualCheck[]
  checkedAt: number
}


// ── Props ─────────────────────────────────────────────────────────────────────

interface PreTradeRiskCheckProps {
  result?: PreTradeCheckResult
  loading?: boolean
}

// ── Sub-components ────────────────────────────────────────────────────────────

function CheckIcon({ status }: { status: CheckStatus }) {
  if (status === 'PASS') return <CheckCircle size={10} className="text-positive flex-shrink-0" />
  if (status === 'WARN') return <AlertTriangle size={10} className="text-warning flex-shrink-0" />
  return <XCircle size={10} className="text-negative flex-shrink-0" />
}

function CheckRow({ check }: { check: IndividualCheck }) {
  const textColor =
    check.status === 'PASS' ? 'text-text-primary' :
    check.status === 'WARN' ? 'text-warning' :
    'text-negative'

  return (
    <div className={clsx(
      'flex items-center gap-2 py-1.5 px-2.5 border-b border-border-muted last:border-0',
      check.status === 'FAIL' && 'bg-negative-bg',
      check.status === 'WARN' && 'bg-warning-bg',
    )}>
      <CheckIcon status={check.status} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-1">
          <span className={clsx('font-mono text-[0.6rem] font-medium', textColor)}>
            {check.name}
          </span>
          <span className="font-mono text-[0.58rem] text-text-muted tabular-nums whitespace-nowrap">
            {check.current} / {check.limit}
          </span>
        </div>
        {check.reason && (
          <p className={clsx('font-mono text-[0.55rem] mt-0.5', textColor)}>
            {check.reason}
          </p>
        )}
      </div>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function PreTradeRiskCheck({
  result,
  loading = false,
}: PreTradeRiskCheckProps) {
  const [overrideConfirming, setOverrideConfirming] = useState(false)
  const [overridden, setOverridden] = useState(false)

  const { data: riskStatus } = useQuery({
    queryKey: ['risk-status-pretrade'],
    queryFn: () => apiGet<any>(API.riskStatus),
    refetchInterval: 10_000,
    enabled: !result,
  })

  const liveResult: PreTradeCheckResult | null = riskStatus ? {
    decision: riskStatus.emergency_stop ? 'BLOCKED' :
              riskStatus.halt_reason ? 'WARNING' : 'ALLOWED',
    checks: [
      {
        name: 'Emergency Stop',
        status: riskStatus.emergency_stop ? 'FAIL' : 'PASS',
        current: riskStatus.emergency_stop ? 'ACTIVE' : 'Inactive',
        limit: 'Must be inactive',
      },
      {
        name: 'Daily Loss',
        status: (riskStatus.daily_loss_pct ?? 0) > 2.5 ? 'WARN' : 'PASS',
        current: `${((riskStatus.daily_loss_pct ?? 0) * 100).toFixed(1)}% used`,
        limit: '3.0% limit',
      },
      {
        name: 'Position Count',
        status: (riskStatus.open_positions ?? 0) >= (riskStatus.max_open_positions ?? 10) ? 'WARN' : 'PASS',
        current: `${riskStatus.open_positions ?? 0} open`,
        limit: `${riskStatus.max_open_positions ?? 10} max`,
      },
    ],
    checkedAt: Date.now(),
  } : null

  const displayResult = result ?? liveResult

  if (!displayResult) {
    return (
      <div className="border border-border-subtle rounded-sm">
        <div className="flex items-center gap-2 px-2.5 py-2 border-b border-border-subtle bg-bg-panel-raised">
          <Loader size={10} className="text-text-muted animate-spin" />
          <span className="font-mono text-[0.6rem] text-text-muted uppercase tracking-wide">
            Loading Risk Status...
          </span>
        </div>
      </div>
    )
  }

  const isBlocked = displayResult.decision === 'BLOCKED'
  const isWarning = displayResult.decision === 'WARNING'
  const isAllowed = displayResult.decision === 'ALLOWED'

  const headerBg = isBlocked
    ? 'bg-negative-bg border-b border-negative'
    : isWarning
      ? 'bg-warning-bg border-b border-warning'
      : 'bg-positive-bg border-b border-positive'

  const decisionIcon = isBlocked
    ? <XCircle size={12} className="text-negative flex-shrink-0" />
    : isWarning
      ? <AlertTriangle size={12} className="text-warning flex-shrink-0" />
      : <CheckCircle size={12} className="text-positive flex-shrink-0" />

  const decisionText = isBlocked
    ? 'BLOCKED — Trade Rejected'
    : isWarning
      ? 'WARNING — Near Risk Limits'
      : 'ALLOWED — All Checks Passed'

  const decisionColor = isBlocked ? 'text-negative' : isWarning ? 'text-warning' : 'text-positive'

  if (loading) {
    return (
      <div className="border border-border-subtle rounded-sm">
        <div className="flex items-center gap-2 px-2.5 py-2 border-b border-border-subtle bg-bg-panel-raised">
          <Loader size={10} className="text-text-muted animate-spin" />
          <span className="font-mono text-[0.6rem] text-text-muted uppercase tracking-wide">
            Running Risk Checks...
          </span>
        </div>
        <div className="p-2 space-y-1.5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-5 skeleton rounded-sm" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className={clsx(
      'border rounded-sm overflow-hidden',
      isBlocked ? 'border-negative' : isWarning ? 'border-warning' : 'border-positive',
    )}>
      {/* Decision header */}
      <div className={clsx('flex items-center gap-2 px-2.5 py-2', headerBg)}>
        {decisionIcon}
        <span className={clsx('font-mono text-[0.65rem] font-bold uppercase tracking-wide flex-1', decisionColor)}>
          {decisionText}
        </span>
        <span className="font-mono text-[0.5rem] text-text-muted tabular-nums">
          {new Date(displayResult.checkedAt).toLocaleTimeString('en-US', { hour12: false })}
        </span>
      </div>

      {/* Check rows */}
      <div>
        {displayResult.checks.map((check, i) => (
          <CheckRow key={i} check={check} />
        ))}
      </div>

      {/* Override section */}
      {!isAllowed && (
        <div className="px-2.5 py-2 border-t border-border-subtle">
          {!overrideConfirming && !overridden && (
            <button
              type="button"
              disabled={isBlocked}
              onClick={() => setOverrideConfirming(true)}
              className={clsx(
                'w-full py-1.5 font-mono text-[0.62rem] uppercase tracking-wide border rounded-sm transition-colors',
                isBlocked
                  ? 'border-border-subtle text-text-dim cursor-not-allowed'
                  : 'border-warning text-warning hover:bg-warning-bg',
              )}
              title={isBlocked ? 'Override not available for blocked orders' : 'Override risk warning'}
            >
              {isBlocked ? 'Override Disabled' : 'Override Warning'}
            </button>
          )}

          {overrideConfirming && !overridden && (
            <div className="space-y-1.5">
              <p className="font-mono text-[0.6rem] text-warning">
                Confirm override? This bypasses risk controls and will be logged.
              </p>
              <div className="flex gap-1">
                <button
                  type="button"
                  onClick={() => setOverrideConfirming(false)}
                  className="flex-1 py-1 font-mono text-[0.6rem] border border-border-subtle text-text-muted rounded-sm hover:border-accent-cyan transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => { setOverridden(true); setOverrideConfirming(false) }}
                  className="flex-1 py-1 font-mono text-[0.6rem] font-semibold bg-warning border border-warning text-bg-root rounded-sm hover:bg-warning-dim transition-colors"
                >
                  Confirm Override
                </button>
              </div>
            </div>
          )}

          {overridden && (
            <div className="flex items-center gap-1.5 py-1">
              <CheckCircle size={10} className="text-warning" />
              <span className="font-mono text-[0.6rem] text-warning">Override applied — proceed with caution</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
