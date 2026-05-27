import React, { useState, useRef, useEffect } from 'react'
import clsx from 'clsx'
import { useAuthStore } from '@/stores/authStore'
import { API_BASE } from '@/lib/api/client'

const IS_MOCK = import.meta.env.VITE_MOCK_DATA === 'true'
const DEV_USER = 'harishkumart1994'
const DEV_PASS = 'MyRules@1994'

export default function LoginScreen() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const usernameRef = useRef<HTMLInputElement>(null)
  const login = useAuthStore(s => s.login)

  useEffect(() => { usernameRef.current?.focus() }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!username || !password) return
    setError(null)
    setLoading(true)

    // Dev mode: validate credentials locally, no backend needed
    if (IS_MOCK) {
      await new Promise(r => setTimeout(r, 400))
      if (username === DEV_USER && password === DEV_PASS) {
        login('dev-mock-token', username)
      } else {
        setError('Invalid credentials')
        setLoading(false)
      }
      return
    }

    try {
      const body = new URLSearchParams({ username, password })
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(data.detail ?? 'Authentication failed')
        return
      }
      const data = await res.json()
      login(data.access_token, data.username)
    } catch {
      setError('Cannot reach server — is the backend running?')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-bg-root font-mono overflow-hidden">
      {/* Scanline overlay */}
      <div
        className="pointer-events-none fixed inset-0 z-10 opacity-[0.03]"
        style={{ backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(255,255,255,0.5) 2px, rgba(255,255,255,0.5) 4px)' }}
      />

      <div className="relative z-20 w-full max-w-sm px-4">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="text-[0.6rem] tracking-[0.3em] text-text-muted uppercase mb-1">
            Trading Monk
          </div>
          <div className="text-[1.1rem] font-bold tracking-[0.15em] text-accent-cyan uppercase">
            Terminal
          </div>
          <div className="mt-2 h-px bg-gradient-to-r from-transparent via-border-active to-transparent" />
          {IS_MOCK && (
            <div className="mt-3 inline-block text-[0.55rem] uppercase tracking-widest px-2 py-0.5 border border-accent-amber text-accent-amber">
              Dev Mode — no backend required
            </div>
          )}
        </div>

        {/* Login form */}
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-[0.6rem] uppercase tracking-widest text-text-muted mb-1">
              User ID
            </label>
            <input
              ref={usernameRef}
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              autoComplete="username"
              spellCheck={false}
              className={clsx(
                'w-full bg-bg-panel border px-3 py-2 text-[0.75rem] text-text-primary',
                'focus:outline-none focus:border-accent-cyan transition-colors',
                'placeholder:text-text-dim',
                error ? 'border-negative' : 'border-border-subtle'
              )}
              placeholder="enter user id"
            />
          </div>

          <div>
            <label className="block text-[0.6rem] uppercase tracking-widest text-text-muted mb-1">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              autoComplete="current-password"
              className={clsx(
                'w-full bg-bg-panel border px-3 py-2 text-[0.75rem] text-text-primary',
                'focus:outline-none focus:border-accent-cyan transition-colors',
                'placeholder:text-text-dim',
                error ? 'border-negative' : 'border-border-subtle'
              )}
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div className="text-[0.65rem] text-negative bg-negativeBg border border-negativeDim px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !username || !password}
            className={clsx(
              'w-full py-2.5 text-[0.7rem] font-bold uppercase tracking-[0.2em] transition-all',
              'border focus:outline-none',
              loading || !username || !password
                ? 'border-border-subtle text-text-muted cursor-not-allowed'
                : 'border-accent-cyan text-accent-cyan hover:bg-accent-cyan hover:text-bg-root cursor-pointer'
            )}
          >
            {loading ? 'Authenticating...' : 'Authenticate'}
          </button>
        </form>

        {/* Footer */}
        <div className="mt-6 text-center text-[0.55rem] text-text-dim tracking-wider uppercase">
          Unauthorized access prohibited
        </div>
      </div>
    </div>
  )
}
