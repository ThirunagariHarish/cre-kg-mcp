import React, { useState } from 'react'
import clsx from 'clsx'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import { ShieldOff, AlertTriangle } from 'lucide-react'

interface KillSwitchButtonProps {
  onActivate: () => void
  active?: boolean
  className?: string
}

export default function KillSwitchButton({
  onActivate,
  active = false,
  className,
}: KillSwitchButtonProps) {
  const [confirmInput, setConfirmInput] = useState('')
  const [open, setOpen] = useState(false)

  const handleConfirm = () => {
    if (confirmInput === 'KILL') {
      onActivate()
      setOpen(false)
      setConfirmInput('')
    }
  }

  const handleOpenChange = (newOpen: boolean) => {
    setOpen(newOpen)
    if (!newOpen) setConfirmInput('')
  }

  if (active) {
    return (
      <div
        className={clsx(
          'w-full py-3 flex flex-col items-center gap-1',
          'bg-negative-bg border border-negative rounded-sm',
          className
        )}
      >
        <ShieldOff size={18} className="text-negative animate-pulse" />
        <span className="font-mono text-[0.65rem] font-bold text-negative uppercase tracking-widest">
          KILL SWITCH ACTIVE
        </span>
        <span className="font-mono text-[0.55rem] text-negative-dim">
          All trading halted
        </span>
      </div>
    )
  }

  return (
    <AlertDialog.Root open={open} onOpenChange={handleOpenChange}>
      <AlertDialog.Trigger asChild>
        <button
          className={clsx(
            'w-full py-2.5 flex items-center justify-center gap-2',
            'bg-bg-panel border-2 border-negative rounded-sm',
            'font-mono text-[0.7rem] font-bold text-negative uppercase tracking-widest',
            'hover:bg-negative-bg transition-colors',
            'focus-visible:outline focus-visible:outline-1 focus-visible:outline-negative',
            'active:scale-[0.99]',
            className
          )}
        >
          <ShieldOff size={12} />
          KILL SWITCH
        </button>
      </AlertDialog.Trigger>

      <AlertDialog.Portal>
        <AlertDialog.Overlay
          className="fixed inset-0 bg-black/80 z-modal animate-fade-in"
        />
        <AlertDialog.Content
          className={clsx(
            'fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2',
            'z-modal w-full max-w-sm',
            'bg-bg-panel border border-negative rounded',
            'animate-slide-in-up shadow-[0_0_30px_rgba(239,68,68,0.3)]',
            'p-5'
          )}
        >
          {/* Header */}
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle size={18} className="text-negative flex-shrink-0" />
            <div>
              <AlertDialog.Title className="font-mono text-sm font-bold text-negative uppercase tracking-wider">
                ACTIVATE KILL SWITCH
              </AlertDialog.Title>
              <AlertDialog.Description className="font-mono text-[0.6rem] text-text-muted mt-0.5">
                This will immediately halt all trading and cancel pending orders.
              </AlertDialog.Description>
            </div>
          </div>

          {/* Warning list */}
          <div className="mb-4 p-3 bg-negative-bg border border-negative-dim rounded-sm space-y-1">
            {[
              'All pending orders will be CANCELLED',
              'New orders will be BLOCKED',
              'Open positions will NOT be closed automatically',
              'Manual intervention required to re-activate',
            ].map((warning, i) => (
              <div key={i} className="flex items-start gap-1.5">
                <span className="font-mono text-[0.6rem] text-negative flex-shrink-0 mt-px">•</span>
                <span className="font-mono text-[0.6rem] text-negative">{warning}</span>
              </div>
            ))}
          </div>

          {/* Confirmation input */}
          <div className="mb-4">
            <label className="block font-mono text-[0.6rem] text-text-muted uppercase tracking-widest mb-1">
              Type <span className="text-negative font-bold">KILL</span> to confirm
            </label>
            <input
              type="text"
              value={confirmInput}
              onChange={e => setConfirmInput(e.target.value.toUpperCase())}
              placeholder="KILL"
              className={clsx(
                'terminal-input h-8 text-sm font-mono font-bold text-center uppercase',
                confirmInput === 'KILL'
                  ? 'border-negative text-negative'
                  : 'border-border-subtle'
              )}
              autoFocus
              onKeyDown={e => {
                if (e.key === 'Enter') handleConfirm()
                if (e.key === 'Escape') handleOpenChange(false)
              }}
            />
          </div>

          {/* Actions */}
          <div className="flex gap-2">
            <AlertDialog.Cancel asChild>
              <button
                className="flex-1 py-2 font-mono text-[0.65rem] uppercase tracking-wider text-text-muted border border-border-subtle rounded-sm hover:border-border-active hover:text-text-primary transition-colors"
              >
                Cancel (Esc)
              </button>
            </AlertDialog.Cancel>
            <button
              onClick={handleConfirm}
              disabled={confirmInput !== 'KILL'}
              className={clsx(
                'flex-1 py-2 font-mono text-[0.65rem] font-bold uppercase tracking-wider rounded-sm border transition-colors',
                confirmInput === 'KILL'
                  ? 'bg-negative border-negative text-white hover:bg-[#dc2626]'
                  : 'bg-negative-bg border-negative-dim text-negative-dim opacity-50 cursor-not-allowed'
              )}
            >
              ⚡ ACTIVATE
            </button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  )
}
