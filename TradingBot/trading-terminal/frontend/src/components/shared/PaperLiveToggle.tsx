import React, { useState, useEffect, useRef } from 'react'
import clsx from 'clsx'
import { AlertTriangle } from 'lucide-react'

// ── Props ─────────────────────────────────────────────────────────────────────

type TradingMode = 'PAPER' | 'LIVE'

interface PaperLiveToggleProps {
  mode: TradingMode
  onModeChange?: (mode: TradingMode) => Promise<void>
}

const CONFIRM_WORD = 'CONFIRM'
const COUNTDOWN_SECONDS = 5

// ── Modal ─────────────────────────────────────────────────────────────────────

interface ConfirmModalProps {
  currentMode: TradingMode
  targetMode: TradingMode
  onConfirm: () => void
  onCancel: () => void
  switching: boolean
}

function ConfirmModal({ currentMode, targetMode, onConfirm, onCancel, switching }: ConfirmModalProps) {
  const isToLive = targetMode === 'LIVE'
  const [inputValue, setInputValue] = useState('')
  const [countdown, setCountdown] = useState(isToLive ? COUNTDOWN_SECONDS : 0)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (isToLive && countdown > 0) {
      const timer = setTimeout(() => setCountdown(c => c - 1), 1000)
      return () => clearTimeout(timer)
    }
    return undefined
  }, [countdown, isToLive])

  useEffect(() => {
    // Focus the input after countdown ends
    if (isToLive && countdown === 0) {
      inputRef.current?.focus()
    }
  }, [countdown, isToLive])

  const confirmEnabled = isToLive
    ? countdown === 0 && inputValue === CONFIRM_WORD
    : true

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') onCancel()
    if (e.key === 'Enter' && confirmEnabled) onConfirm()
  }

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-label={`Switch to ${targetMode} trading mode`}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onCancel}
      />

      {/* Modal */}
      <div
        className={clsx(
          'relative z-10 w-80 border rounded-sm shadow-panel',
          isToLive ? 'bg-negative-bg border-negative' : 'bg-bg-panel border-border-subtle',
        )}
        onKeyDown={handleKeyDown}
      >
        {/* Header */}
        <div className={clsx(
          'flex items-center gap-2 px-3 py-2.5 border-b',
          isToLive ? 'border-negative' : 'border-border-subtle',
        )}>
          {isToLive && <AlertTriangle size={12} className="text-negative flex-shrink-0" />}
          <span className={clsx(
            'font-mono text-[0.7rem] font-bold uppercase tracking-wide',
            isToLive ? 'text-negative' : 'text-text-primary',
          )}>
            {isToLive ? 'Switch to LIVE Trading' : 'Switch to PAPER Trading'}
          </span>
        </div>

        {/* Body */}
        <div className="px-3 py-3 space-y-3">
          {isToLive ? (
            <>
              <p className="font-mono text-[0.65rem] text-negative leading-relaxed">
                You are switching to <strong>LIVE trading</strong>. Real money will be at risk.
                All pending paper orders will be cancelled.
              </p>
              <p className="font-mono text-[0.6rem] text-text-secondary leading-relaxed">
                This action connects to your live brokerage account. Any orders placed will execute with real funds.
              </p>

              {countdown > 0 ? (
                <div className="text-center py-2">
                  <span className="font-mono text-[0.6rem] text-text-muted">
                    Please wait
                  </span>
                  <div className="font-mono text-2xl font-bold text-negative mt-1 tabular-nums">
                    {countdown}
                  </div>
                  <span className="font-mono text-[0.6rem] text-text-muted">
                    seconds before confirming
                  </span>
                </div>
              ) : (
                <div>
                  <label className="block font-mono text-[0.58rem] text-text-muted uppercase tracking-widest mb-1">
                    Type <span className="text-negative font-semibold">{CONFIRM_WORD}</span> to proceed
                  </label>
                  <input
                    ref={inputRef}
                    type="text"
                    value={inputValue}
                    onChange={e => setInputValue(e.target.value.toUpperCase())}
                    placeholder={CONFIRM_WORD}
                    className={clsx(
                      'terminal-input h-8 font-semibold uppercase tracking-widest text-center',
                      inputValue === CONFIRM_WORD ? 'border-negative text-negative' : '',
                    )}
                    maxLength={7}
                    autoComplete="off"
                  />
                </div>
              )}
            </>
          ) : (
            <p className="font-mono text-[0.65rem] text-text-secondary leading-relaxed">
              Switch to <strong className="text-text-primary">PAPER trading</strong>? Live positions will not be affected. New orders will be simulated only.
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-1.5 px-3 pb-3">
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 py-1.5 font-mono text-[0.62rem] border border-border-subtle text-text-muted rounded-sm hover:border-accent-cyan hover:text-text-secondary transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!confirmEnabled || switching}
            className={clsx(
              'flex-1 py-1.5 font-mono text-[0.68rem] font-bold uppercase tracking-wider rounded-sm border transition-colors',
              isToLive
                ? 'bg-negative border-negative text-white hover:bg-[#e01040] disabled:opacity-40 disabled:cursor-not-allowed'
                : 'bg-bg-panel-raised border-accent-cyan text-accent-cyan hover:bg-bg-panel disabled:opacity-40',
            )}
          >
            {switching ? 'Switching...' : isToLive ? 'Go Live' : 'Go Paper'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function PaperLiveToggle({ mode, onModeChange }: PaperLiveToggleProps) {
  const [showModal, setShowModal] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [currentMode, setCurrentMode] = useState<TradingMode>(mode)
  const targetMode: TradingMode = currentMode === 'PAPER' ? 'LIVE' : 'PAPER'

  async function handleConfirm() {
    setSwitching(true)
    try {
      await onModeChange?.(targetMode)
      setCurrentMode(targetMode)
      setShowModal(false)
    } finally {
      setSwitching(false)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setShowModal(true)}
        aria-label={`Current mode: ${currentMode}. Click to switch.`}
        className={clsx(
          'flex items-center gap-1.5 px-2.5 py-1 rounded-sm border font-mono text-[0.65rem] font-bold uppercase tracking-wider transition-all',
          currentMode === 'LIVE'
            ? 'bg-negative-bg border-negative text-negative animate-pulse-alert'
            : 'bg-bg-panel-raised border-border-subtle text-text-secondary hover:border-accent-cyan hover:text-text-primary',
        )}
      >
        <span
          className={clsx(
            'inline-block w-1.5 h-1.5 rounded-full flex-shrink-0',
            currentMode === 'LIVE' ? 'bg-negative animate-pulse' : 'bg-text-muted',
          )}
          aria-hidden="true"
        />
        {currentMode}
      </button>

      {showModal && (
        <ConfirmModal
          currentMode={currentMode}
          targetMode={targetMode}
          onConfirm={handleConfirm}
          onCancel={() => setShowModal(false)}
          switching={switching}
        />
      )}
    </>
  )
}
